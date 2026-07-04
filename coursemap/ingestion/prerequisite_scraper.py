"""
Prerequisite/restriction/corequisite scraper: fetch course pages and extract
structured prerequisite trees plus flat restriction/corequisite code lists.

Old behaviour: regex over the full page text, producing a flat list of all
six-digit codes found anywhere, this lost AND/OR structure and introduced
noise from codes in navigation, headers, and related-course sections.

New behaviour: BeautifulSoup finds the Prerequisite/Restriction/Corequisite
section specifically, extracts only that section's text, then a
recursive-descent parser builds a structured prerequisite tree (restrictions
and corequisites are flat lists, see parse_code_list_text):

    "115230 or 115233"
    -> {"op": "OR", "args": ["115230", "115233"]}

    "(115230 or 115231) and 115100"
    -> {"op": "AND", "args": [{"op": "OR", "args": ["115230", "115231"]}, "115100"]}

A plain string means a single required course. None means no prerequisites found.

The output format (None | str | dict) is stored in courses.json and consumed by
dataset_loader.parse_prereqs, which converts it to a PrerequisiteExpression tree.
The old flat-list format is still supported by parse_prereqs for backward
compatibility with un-re-scraped datasets.

Verified live page structure (July 2026, see _find_labelled_text's Strategy 1):
each section is a <div class="course-intro__col-header"> (heading + sub-label)
followed by a sibling <div class="rich-text"> holding the actual code(s). The
heading and the code are NOT siblings of each other, a naive "heading -> next
sibling" search lands on the sub-label instead and silently finds nothing.

Grammar (EBNF):
    expr   ::= term  (AND term)*
    term   ::= factor (OR factor)*
    factor ::= '(' expr ')' | CODE
    AND    ::= 'and' | ','
    OR     ::= 'or'
    CODE   ::= 6-digit sequence (e.g. "115230" or "115.230")
"""

from __future__ import annotations
import logging
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Matches a 6-digit course code, optionally dotted (115.230 → 115230).
_DOTTED_CODE_RE = re.compile(r'\b(\d{3})\.(\d{3})\b')
# Matches a plain 6-digit code after dot-normalisation.
_CODE_RE = re.compile(r'\b\d{6}\b')

# Header label regexes, keyed by the same keyword used to find the section.
# Both "Prerequisite(s):"-style inline labels and the plain "Restrictions" /
# "Corequisites" heading text used on Massey's post-2024 pages need to match.
_HEADER_RE = {
    "prerequisite": re.compile(r'prerequisites?\s*\(s\)?\s*:?\s*', re.IGNORECASE),
    "restriction":  re.compile(r'restrictions?\s*\(s\)?\s*:?\s*', re.IGNORECASE),
    "corequisite":  re.compile(r'corequisites?\s*\(s\)?\s*:?\s*', re.IGNORECASE),
}
_INLINE_LABEL_RE = {
    "prerequisite": re.compile(r"prerequisites?\s*\(s\)?\s*:", re.IGNORECASE),
    "restriction":  re.compile(r"restrictions?\s*\(s\)?\s*:", re.IGNORECASE),
    "corequisite":  re.compile(r"corequisites?\s*\(s\)?\s*:", re.IGNORECASE),
}


# ---------------------------------------------------------------------------
# HTML: locate a labelled section (prerequisite / restriction / corequisite)
# on a course page
# ---------------------------------------------------------------------------

def _find_labelled_text(soup: BeautifulSoup, keyword: str) -> str | None:
    """
    Search for a section whose label contains `keyword` ("prerequisite",
    "restriction", or "corequisite") and return its text, or None if not found.

    Five strategies are tried in order:

    1. Massey's current (verified live, 2026) course page structure: each
       section is a ``<div>`` containing a ``<div class="course-intro__col-header">``
       (itself holding a ``<h3 class="course-intro__col-heading">`` label like
       "Prerequisite courses" or "Restrictions", plus a
       ``<div class="course-intro__col-subheading">`` sub-label like "Complete
       first" or "Similar content"), followed by a SIBLING
       ``<div class="rich-text">`` holding the actual course code(s) (as
       ``<a>`` links for prerequisites, plain text for restrictions).
       The heading and the code are NOT siblings of each other, the code is a
       sibling of the heading's *parent* (`.course-intro__col-header`), one
       level further out. A naive "heading -> next sibling" search (Strategy
       5 below) lands on the sub-heading div instead, which has no course
       code in it, and silently returns nothing instead of raising, which is
       exactly why this was wrong for a long time without ever erroring: it
       found the "Complete first"/"Similar content" text, saw no CODE tokens
       in it, and returned None, indistinguishable from "this course
       genuinely has none." Confirmed against masesy.ac.nz's live page for
       159201 (Algorithms and Data Structures), which has both a real
       prerequisite (159102) and a real restriction (159271); prior to this
       strategy, both came back None/[] instead.

    2. ``<details>`` accordion: an older Massey page structure that moves
       course metadata into collapsible blocks. Search each ``<details>``
       element for a ``<dt>``/``<dd>`` pair or inline "Label:" text inside it.

    3. Top-level ``<dt>`` element containing the keyword -> the next sibling
       ``<dd>``. Pre-redesign structure, still present on some pages.

    4. Any ``<p>``/``<div>``/``<span>``/``<li>`` whose text starts with
       "Label:". Inline-label format.

    5. A heading (``<h2>``-``<h4>``, ``<strong>``, ``<b>``) containing the
       keyword -> its next sibling paragraph or list. Covers plain headings
       with no colon. Kept as a last-resort fallback for page structures
       that don't match any of the above, even though it's the strategy
       that silently failed for the current live structure (see Strategy 1).
    """
    inline_re = _INLINE_LABEL_RE[keyword]

    # Strategy 1: current Massey structure (course-intro__col-header + rich-text)
    for header_div in soup.find_all("div", class_="course-intro__col-header"):
        heading = header_div.find(class_="course-intro__col-heading")
        if heading and keyword in heading.get_text(strip=True).lower():
            code_div = header_div.find_next_sibling("div", class_="rich-text")
            if code_div:
                return code_div.get_text(separator=" ", strip=True)

    # Strategy 2: <details> accordion (older Massey redesign)
    for details in soup.find_all("details"):
        for dt in details.find_all("dt"):
            if keyword in dt.get_text(strip=True).lower():
                dd = dt.find_next_sibling("dd")
                if dd:
                    return dd.get_text(separator=" ", strip=True)
        for tag in details.find_all(["p", "div", "span", "li"]):
            text = tag.get_text(strip=True)
            if inline_re.match(text):
                return text

    # Strategy 3: <dt>/<dd> pattern (pre-redesign)
    for dt in soup.find_all("dt"):
        if keyword in dt.get_text(strip=True).lower():
            dd = dt.find_next_sibling("dd")
            if dd:
                return dd.get_text(separator=" ", strip=True)

    # Strategy 4: inline "Label:" text
    for tag in soup.find_all(["p", "div", "span", "li"]):
        text = tag.get_text(strip=True)
        if inline_re.match(text):
            return text

    # Strategy 5: heading → following sibling (last resort, see docstring)
    for heading in soup.find_all(["h2", "h3", "h4", "strong", "b"]):
        if keyword in heading.get_text(strip=True).lower():
            sibling = heading.find_next_sibling(["p", "div", "ul", "dd"])
            if sibling:
                return sibling.get_text(separator=" ", strip=True)

    return None


def find_prereq_text(soup: BeautifulSoup) -> str | None:
    """Return the prerequisite section's text, or None if not found."""
    return _find_labelled_text(soup, "prerequisite")


def find_restriction_text(soup: BeautifulSoup) -> str | None:
    """
    Return the restriction section's text, or None if not found.

    Restrictions are courses that permanently block enrolment once already
    completed (similar-content pairs, e.g. "159201 R 159271"). Massey's
    post-2024 pages label this with a plain "Restrictions" heading rather
    than "Restriction(s):", which is why strategy 4 (heading, no colon)
    matters more here than it does for prerequisites.
    """
    return _find_labelled_text(soup, "restriction")


def find_corequisite_text(soup: BeautifulSoup) -> str | None:
    """
    Return the corequisite section's text, or None if not found.

    Corequisites are courses that must be taken in the same semester as (or
    already passed before) this one. Rare compared to prerequisites and
    restrictions; most courses have none.
    """
    return _find_labelled_text(soup, "corequisite")


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------

def tokenize(text: str, header: str = "prerequisite") -> list:
    """
    Tokenize section text into a flat list of:
      - six-digit course codes (after dot-normalisation)
      - 'and'  (from literal 'and' or comma)
      - 'or'
      - '('
      - ')'

    The section header (e.g. "Prerequisite(s):", "Restrictions") is stripped
    first, using the regex for `header` ("prerequisite", "restriction", or
    "corequisite"; defaults to "prerequisite" for backward compatibility).
    Dotted codes ("115.230") are normalised to "115230". Any other word
    (including phrases like "One of" in corequisite text) is skipped
    character by character rather than tokenized, so unexpected phrasing
    degrades to "no structure found" instead of raising.
    """
    # Normalise dotted course codes: '115.230' → '115230'
    text = _DOTTED_CODE_RE.sub(lambda m: m.group(1) + m.group(2), text)
    # Remove leading section header, e.g. "Prerequisite(s):" or "Restrictions"
    text = _HEADER_RE[header].sub("", text)

    tokens = []
    i = 0
    n = len(text)

    while i < n:
        ch = text[i]

        if ch.isspace():
            i += 1

        elif ch == "(":
            tokens.append("(")
            i += 1

        elif ch == ")":
            tokens.append(")")
            i += 1

        elif ch == ",":
            # Comma acts as implicit AND
            tokens.append("and")
            i += 1

        elif text[i : i + 3].lower() == "and" and (
            i + 3 >= n or not text[i + 3].isalnum()
        ):
            tokens.append("and")
            i += 3

        elif text[i : i + 2].lower() == "or" and (
            i + 2 >= n or not text[i + 2].isalnum()
        ):
            tokens.append("or")
            i += 2

        else:
            m = _CODE_RE.match(text, i)
            if m:
                tokens.append(m.group())
                i += 6
            else:
                i += 1  # skip unrecognised character

    return tokens


# ---------------------------------------------------------------------------
# Recursive-descent parser
# ---------------------------------------------------------------------------
#
# Grammar:
#   expr   ::= term  ('and' term)*
#   term   ::= factor ('or' factor)*
#   factor ::= '(' expr ')' | CODE
#
# AND binds more loosely than OR (OR is evaluated first), which matches how
# Massey writes requirements: "(A or B) and C" groups A|B before &-ing with C.

def _parse_expr(tokens: list, pos: int) -> tuple:
    """Parse an AND-level expression.  Returns (node, new_pos)."""
    node, pos = _parse_term(tokens, pos)
    children = [node]
    while pos < len(tokens) and tokens[pos] == "and":
        pos += 1
        right, pos = _parse_term(tokens, pos)
        children.append(right)
    if len(children) == 1:
        return children[0], pos
    return {"op": "AND", "args": children}, pos


def _parse_term(tokens: list, pos: int) -> tuple:
    """Parse an OR-level term.  Returns (node, new_pos)."""
    node, pos = _parse_factor(tokens, pos)
    children = [node]
    while pos < len(tokens) and tokens[pos] == "or":
        pos += 1
        right, pos = _parse_factor(tokens, pos)
        children.append(right)
    if len(children) == 1:
        return children[0], pos
    return {"op": "OR", "args": children}, pos


def _parse_factor(tokens: list, pos: int) -> tuple:
    """Parse a parenthesised group or a bare course code."""
    if pos >= len(tokens):
        return None, pos

    if tokens[pos] == "(":
        pos += 1
        node, pos = _parse_expr(tokens, pos)
        if pos < len(tokens) and tokens[pos] == ")":
            pos += 1
        return node, pos

    if _CODE_RE.match(tokens[pos]):
        return tokens[pos], pos + 1

    # Skip an unexpected token (e.g. a stray ')' without matching '(')
    return None, pos + 1


def parse_prerequisite_text(text: str) -> Any:
    """
    Parse a prerequisite text string into a structured tree.

    Returns:
        None:         no prerequisites found
        str:          a single required course code
        dict:         {"op": "AND"|"OR", "args": [node, ...]}
                      where each node is recursively str | dict

    Examples::

        parse_prerequisite_text("115230")
        # → "115230"

        parse_prerequisite_text("115230 or 115233")
        # → {"op": "OR", "args": ["115230", "115233"]}

        parse_prerequisite_text("(115230 or 115231) and 115100")
        # → {"op": "AND", "args": [
        #       {"op": "OR", "args": ["115230", "115231"]},
        #       "115100"
        #    ]}
    """
    if not text:
        return None
    tokens = tokenize(text)
    if not tokens:
        return None
    result, _ = _parse_expr(tokens, 0)
    return result


def parse_code_list_text(text: str, header: str = "restriction") -> list[str]:
    """
    Parse restriction or corequisite text into a flat, order-preserving,
    deduplicated list of course codes.

    Unlike prerequisites, `courses.json` stores restrictions and corequisites
    as flat lists with no AND/OR structure (see `dataset_loader._parse_code_set`),
    so this discards the tokenizer's 'and'/'or'/'('/')' tokens and keeps only
    the course codes. This also means a "Corequisites: One of X, Y, Z"
    choose-one requirement collapses to a flat [X, Y, Z], the same
    choose-N-of-M simplification already documented for prerequisites in
    DATA_QUALITY.md, since nothing downstream models a choice within this
    field.

    Examples::

        parse_code_list_text("159271")
        # → ["159271"]

        parse_code_list_text("159271, 159272", header="restriction")
        # → ["159271", "159272"]

        parse_code_list_text("One of 110380, 125340, 125342", header="corequisite")
        # → ["110380", "125340", "125342"]
    """
    if not text:
        return []
    tokens = tokenize(text, header=header)
    seen: set[str] = set()
    codes: list[str] = []
    for tok in tokens:
        if tok in ("and", "or", "(", ")"):
            continue
        if tok not in seen:
            seen.add(tok)
            codes.append(tok)
    return codes


# ---------------------------------------------------------------------------
# Page-level scraper
# ---------------------------------------------------------------------------

# Mimics a real browser enough to pass most CDN bot checks. The Massey site
# requires at minimum a non-empty User-Agent; without it most requests return 403.
_DEFAULT_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-NZ,en;q=0.9",
}


def scrape_prerequisites(url: str, timeout: int = 10) -> Any:
    """
    Fetch a course page and return a structured prerequisite tree, or None.

    Returns:
        None:   no prerequisites found or fetch failed
        str:    single required course code
        dict:   {"op": "AND"|"OR", "args": [...]} tree

    Kept for backward compatibility with anything that only wants
    prerequisites. New code that needs restrictions and/or corequisites too
    should use `scrape_course_relations`, which extracts all three from a
    single page fetch instead of fetching the same URL repeatedly.
    """
    import requests  # lazy: only this function needs network access, so the
                      # rest of the module (parsing functions, tokenizer)
                      # stays importable without the `ingestion` extra installed.
    from bs4 import BeautifulSoup
    try:
        r = requests.get(url, timeout=timeout, headers=_DEFAULT_HEADERS)
        if r.status_code != 200:
            logger.debug("HTTP %d for %s", r.status_code, url)
            return None

        soup = BeautifulSoup(r.text, "html.parser")
        prereq_text = find_prereq_text(soup)
        if not prereq_text:
            return None

        return parse_prerequisite_text(prereq_text)

    except Exception as exc:
        logger.debug("Failed to scrape prerequisites from %s: %s", url, exc)
        return None


def scrape_course_relations(url: str, timeout: int = 10) -> dict[str, Any]:
    """
    Fetch a course page once and extract prerequisites, restrictions, and
    corequisites together.

    Returns a dict:
        {
            "prerequisites": None | str | dict,  # AND/OR tree, see parse_prerequisite_text
            "restrictions":  list[str],           # flat, see parse_code_list_text
            "corequisites":  list[str],           # flat, see parse_code_list_text
        }

    All three fall back to their empty value (None / [] / []) on fetch
    failure, a non-200 response, or a parse error, so a course with a
    genuinely-empty section is indistinguishable from a fetch failure here.
    Callers that need to tell those apart should check the HTTP status
    separately; this dataset does not currently track that distinction (see
    DATA_QUALITY.md's note that "no data recorded" means "unverified," not
    "confirmed none").
    """
    import requests
    from bs4 import BeautifulSoup

    empty: dict[str, Any] = {"prerequisites": None, "restrictions": [], "corequisites": []}
    try:
        r = requests.get(url, timeout=timeout, headers=_DEFAULT_HEADERS)
        if r.status_code != 200:
            logger.debug("HTTP %d for %s", r.status_code, url)
            return empty

        soup = BeautifulSoup(r.text, "html.parser")

        prereq_text = find_prereq_text(soup)
        restriction_text = find_restriction_text(soup)
        coreq_text = find_corequisite_text(soup)

        return {
            "prerequisites": parse_prerequisite_text(prereq_text) if prereq_text else None,
            "restrictions": parse_code_list_text(restriction_text, header="restriction") if restriction_text else [],
            "corequisites": parse_code_list_text(coreq_text, header="corequisite") if coreq_text else [],
        }

    except Exception as exc:
        logger.debug("Failed to scrape course relations from %s: %s", url, exc)
        return empty


# ---------------------------------------------------------------------------
# Batch scraper
# ---------------------------------------------------------------------------

def scrape_all(courses: list, concurrency: int = 8, timeout: int = 10) -> dict:
    """
    Scrape prerequisites, restrictions, and corequisites for all courses in
    parallel, one page fetch per course.

    Args:
        courses:     List of course dicts with 'course_code' and 'url' keys.
        concurrency: Number of parallel workers. Keep low (≤10) to avoid
                     overwhelming the Massey CDN and triggering rate limits.
        timeout:     Per-request timeout in seconds.

    Returns a dict mapping course_code -> the dict shape documented in
    `scrape_course_relations` (prerequisites / restrictions / corequisites).
    """
    results: dict[str, Any] = {}

    def _fetch(code: str, url: str) -> tuple[str, dict[str, Any]]:
        # Small random jitter so concurrent workers don't all fire simultaneously.
        time.sleep(random.uniform(0.05, 0.3))
        return code, scrape_course_relations(url, timeout=timeout)

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = {
            executor.submit(_fetch, c["course_code"], c["url"]): c["course_code"]
            for c in courses
            if c.get("url")
        }

        total = len(futures)
        done = 0

        for future in as_completed(futures):
            code = futures[future]
            done += 1

            if done % 50 == 0:
                logger.debug("Course relations scraped %d/%d", done, total)

            try:
                result_code, relations = future.result()
                results[result_code] = relations
            except Exception as exc:
                logger.warning("Course relations scrape failed for %s: %s", code, exc)
                results[code] = {"prerequisites": None, "restrictions": [], "corequisites": []}

    return results
