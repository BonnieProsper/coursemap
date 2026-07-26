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

# Matches a flat "one of X, Y, Z or W" / "any of X, Y, Z or W" enumeration:
# a "one of"/"any of" marker followed by a comma-separated run of course
# codes ending in "or CODE", either bare or wrapped in a matched pair of
# parentheses. Matched as an alternation between "fully parenthesized"
# and "fully flat" rather than two independently-optional paren markers,
# so a paren is always genuinely paired or entirely absent - never a
# partial match that could leave an unbalanced "(" or ")" in the
# tokenized output if an unrelated paren happens to sit near the clause.
# This is the one shape of comma that means OR (a single enumerated
# choice), not AND (a genuine conjunction of separate requirements), the
# exact phrasing Massey normally uses to express a plain-English "pick
# one of these" list without bothering to write out "A or B or C or D"
# with real "or"s. Textbook examples: "One of 161122, 297101, 161220,
# 161221, 161250 or 161251", "One of 158222, 125340, 125342", and
# (live-verified against course 123305's actual page) "One of (123101,
# 123102, 123104, 123105, 123171, 123172) and one of (247111, 247112,
# 247113, 247114)".
_ONE_OF_FLAT_RE = re.compile(
    r"\b(?:one|any)\s+of\s+"
    r"(\(\s*(?:\d{3}\.?\d{3}\s*,\s*)+\d{3}\.?\d{3}(?:\s+or\s+\d{3}\.?\d{3})?\s*\)"
    r"|(?:\d{3}\.?\d{3}\s*,\s*)+\d{3}\.?\d{3}(?:\s+or\s+\d{3}\.?\d{3})?)",
    re.IGNORECASE,
)


def _normalize_one_of_commas(text: str) -> str:
    """
    Rewrite a flat "one of A, B, C or D" clause's commas into "or" before
    tokenization, so the recursive-descent parser (which otherwise always
    treats a comma as AND, see tokenize's docstring) builds an OR expression
    for it instead of an AND. Without this, "One of 161122, 297101, 161220,
    161221, 161250 or 161251" parsed as
    AND(161122, 297101, 161220, 161221, OR(161250, 161251)), i.e. "all of
    these five, plus one of the last two", when the real requirement is
    "any single one of these six". A course whose prerequisite tree is
    wrong in this direction looks artificially harder to satisfy than it
    really is, which can make it permanently unschedulable even when the
    student has met the real (much weaker) requirement.

    Rewrites a flat comma run whether or not it's wrapped in a single pair
    of parentheses directly after "one of"/"any of" - both were confirmed
    on Massey's live pages to mean the same thing (course 123305's actual
    prerequisite text uses exactly this parenthesized form for two
    separate "one of" clauses joined by "and"). Does not attempt to
    handle deeper/nested parenthesisation or explicit "or"-spelled-out
    groups like "(One of (161122 or 161220 or 233214) and one of (160101
    or 160102 or 160105))" - those already tokenize correctly on their
    own since they use real "or"s, so rewriting them isn't needed and
    isn't attempted here.
    """
    def _replace_commas_with_or(match: re.Match) -> str:
        clause = match.group(1)
        return match.group(0)[: match.start(1) - match.start(0)] + clause.replace(",", " or ")

    return _ONE_OF_FLAT_RE.sub(_replace_commas_with_or, text)


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
    A flat "one of A, B, C or D" enumeration has its commas normalised to
    "or" before the rest of tokenization runs, see
    _normalize_one_of_commas. Dotted codes ("115.230") are normalised to
    "115230". Any other word (including phrases like "One of" in
    corequisite text) is skipped character by character rather than
    tokenized, so unexpected phrasing degrades to "no structure found"
    instead of raising.
    """
    # Remove leading section header, e.g. "Prerequisite(s):" or "Restrictions"
    text = _HEADER_RE[header].sub("", text)
    # Rewrite "one of A, B, C or D" before dot-normalisation, since the
    # regex above matches dotted or plain codes either way.
    text = _normalize_one_of_commas(text)
    # Normalise dotted course codes: '115.230' → '115230'
    text = _DOTTED_CODE_RE.sub(lambda m: m.group(1) + m.group(2), text)

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
            # Comma acts as implicit AND, UNLESS it's immediately followed
            # (after whitespace) by a literal 'and' or 'or' -- the common
            # Oxford-comma phrasing "A, B, C or D, and E" ends its
            # enumeration with a real connector word right after the
            # comma. Emitting a token for the comma there would produce
            # two adjacent connector tokens ("and", "and"), which the
            # grammar has no rule for: the second one falls through
            # _parse_factor's "skip unexpected token" fallback and comes
            # back as a bare None operand, silently deleting whatever
            # follows it once _build_expr_from_struct drops the None
            # child. Skip the comma itself here and let the real word
            # supply the one connector token that's actually meant.
            j = i + 1
            while j < n and text[j].isspace():
                j += 1
            nxt3 = text[j : j + 3].lower()
            nxt2 = text[j : j + 2].lower()
            is_and = nxt3 == "and" and (j + 3 >= n or not text[j + 3].isalnum())
            is_or = nxt2 == "or" and (j + 2 >= n or not text[j + 2].isalnum())
            if not (is_and or is_or):
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


def _extract_prerequisite_codes(node: Any) -> set[str]:
    """
    Flatten a prerequisite tree (None | str | {"op": "AND"|"OR", "args": [...]})
    into the flat set of every course code appearing anywhere in it,
    regardless of AND/OR structure or nesting depth.

    Used by refresh_prerequisites.py to compare a freshly-scraped result
    against a course's currently-stored value: if the fresh set is a
    strict subset of the stored set, that's treated as a suspicious
    regression rather than trusted data (see DATA_QUALITY.md - a real
    production incident where sustained scraping returned an apparently
    healthy HTTP 200 response containing fewer prerequisite codes than
    were already known-correct, for several different courses, byte-for-
    byte identically across two separate runs).

    Deliberately structure-blind: does not distinguish "A or B" from
    "A and B" if both mention the same codes. Every real corrupted case
    found in that incident was a straightforward subset (fewer codes,
    same meaning otherwise), never a structural swap with the same code
    set - so structure-blindness is a known, accepted scope boundary,
    not an oversight. A tree that keeps the same codes but changes AND
    to OR (or vice versa) would not be caught by this function.
    """
    if node is None:
        return set()
    if isinstance(node, str):
        return {node}
    if isinstance(node, dict):
        codes: set[str] = set()
        for arg in node.get("args", []):
            codes |= _extract_prerequisite_codes(arg)
        return codes
    return set()


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


def scrape_course_relations(
    url: str, timeout: int = 10, include_diagnostics: bool = False,
) -> dict[str, Any]:
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
    genuinely-empty section is indistinguishable from a fetch failure here
    UNLESS include_diagnostics=True (default False, so every existing
    caller's exact 3-key return shape is completely unchanged).

    When include_diagnostics=True, two extra keys are added:
        "_status_code":    int | None   (None means a request exception,
                                          not a non-200 response)
        "_content_length":  int          (len(r.text); 0 on total failure)

    This closes a real gap found in production: a full refresh_prerequisites
    run silently corrupted several courses' data under sustained concurrent
    load, and not always via an HTTP error - one confirmed case came back
    HTTP 200 with a truncated page body (a complete OR-group choice cut
    short, and a second required course silently missing entirely), which
    an error-only check wouldn't have caught. _content_length lets a
    caller compare against the ~9800-11100 byte range every genuinely
    healthy Massey course page was observed at throughout this
    investigation, and retry anything drastically smaller as suspected
    truncation, not just outright failures.
    """
    import requests
    from bs4 import BeautifulSoup

    empty: dict[str, Any] = {"prerequisites": None, "restrictions": [], "corequisites": []}
    try:
        r = requests.get(url, timeout=timeout, headers=_DEFAULT_HEADERS)
        if r.status_code != 200:
            logger.debug("HTTP %d for %s", r.status_code, url)
            result = dict(empty)
            if include_diagnostics:
                result["_status_code"] = r.status_code
                result["_content_length"] = len(r.text)
            return result

        soup = BeautifulSoup(r.text, "html.parser")

        prereq_text = find_prereq_text(soup)
        restriction_text = find_restriction_text(soup)
        coreq_text = find_corequisite_text(soup)

        result = {
            "prerequisites": parse_prerequisite_text(prereq_text) if prereq_text else None,
            "restrictions": parse_code_list_text(restriction_text, header="restriction") if restriction_text else [],
            "corequisites": parse_code_list_text(coreq_text, header="corequisite") if coreq_text else [],
        }
        if include_diagnostics:
            result["_status_code"] = 200
            result["_content_length"] = len(r.text)
        return result

    except Exception as exc:
        logger.debug("Failed to scrape course relations from %s: %s", url, exc)
        result = dict(empty)
        if include_diagnostics:
            result["_status_code"] = None
            result["_content_length"] = 0
            # Surfaced up to _fetch_relations' WARNING-level log so an
            # operator watching a normal run can tell a timeout apart from
            # a connection error apart from a bug in this function itself,
            # instead of every request-level failure looking identically
            # opaque ("status=None, content_length=0") unless they happen
            # to be running with debug logging enabled.
            result["_error"] = f"{type(exc).__name__}: {exc}"
        return result


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
