"""
Prerequisite scraper: fetch course pages and extract structured prerequisite trees.

Old behaviour: regex over the full page text, producing a flat list of all
six-digit codes found anywhere -- this lost AND/OR structure and introduced
noise from codes in navigation, headers, and related-course sections.

New behaviour: BeautifulSoup finds the Prerequisite(s) section specifically,
extracts only that section's text, then a recursive-descent parser builds a
structured tree:

    "115230 or 115233"  ->  {"op": "OR",  "args": ["115230", "115233"]}

    "(115230 or 115231) and 115100"
    ->  {"op": "AND", "args": [{"op": "OR", "args": ["115230", "115231"]}, "115100"]}
                    →  {"op": "AND", "args": [
                            {"op": "OR", "args": ["115230", "115231"]},
                            "115100"
                       ]}

                A plain string means a single required course.
                None means no prerequisites found.

The output format (None | str | dict) is stored in courses.json and consumed by
dataset_loader.parse_prereqs, which converts it to a PrerequisiteExpression tree.
The old flat-list format is still supported by parse_prereqs for backward
compatibility with un-re-scraped datasets.

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
import requests
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Matches a 6-digit course code, optionally dotted (115.230 → 115230).
_DOTTED_CODE_RE = re.compile(r'\b(\d{3})\.(\d{3})\b')
# Matches a plain 6-digit code after dot-normalisation.
_CODE_RE = re.compile(r'\b\d{6}\b')
# Strips the 'Prerequisite(s):' header from the extracted text.
_HEADER_RE = re.compile(r'prerequisites?\s*\(s\)?\s*:?\s*', re.IGNORECASE)


# ---------------------------------------------------------------------------
# HTML: locate the prerequisite text on a course page
# ---------------------------------------------------------------------------

def find_prereq_text(soup: BeautifulSoup) -> str | None:
    """
    Search for the prerequisite section in a BeautifulSoup-parsed page and
    return its text, or None if not found.

    Four strategies are tried in order:

    1. ``<details>`` accordion — Massey's post-2024 page structure moves course
       metadata into collapsible blocks. Search each ``<details>`` element for
       a ``<dt>``/``<dd>`` pair or inline "Prerequisite(s):" label inside it.

    2. Top-level ``<dt>`` element containing "prerequisite" → the next sibling
       ``<dd>``. Pre-redesign structure, still present on some pages.

    3. Any ``<p>``/``<div>``/``<span>``/``<li>`` whose text starts with
       "Prerequisite(s):". Inline-label format.

    4. A heading (``<h2>``–``<h4>``, ``<strong>``, ``<b>``) containing
       "prerequisite" → its next sibling paragraph or list.
    """
    # Strategy 1: <details> accordion (post-2024 Massey redesign)
    for details in soup.find_all("details"):
        for dt in details.find_all("dt"):
            if "prerequisite" in dt.get_text(strip=True).lower():
                dd = dt.find_next_sibling("dd")
                if dd:
                    return dd.get_text(separator=" ", strip=True)
        for tag in details.find_all(["p", "div", "span", "li"]):
            text = tag.get_text(strip=True)
            if re.match(r"prerequisites?\s*\(s\)?\s*:", text, re.IGNORECASE):
                return text

    # Strategy 2: <dt>/<dd> pattern (pre-redesign)
    for dt in soup.find_all("dt"):
        if "prerequisite" in dt.get_text(strip=True).lower():
            dd = dt.find_next_sibling("dd")
            if dd:
                return dd.get_text(separator=" ", strip=True)

    # Strategy 3: inline "Prerequisite(s):" label
    for tag in soup.find_all(["p", "div", "span", "li"]):
        text = tag.get_text(strip=True)
        if re.match(r"prerequisites?\s*\(s\)?\s*:", text, re.IGNORECASE):
            return text

    # Strategy 4: heading → following sibling
    for heading in soup.find_all(["h2", "h3", "h4", "strong", "b"]):
        if "prerequisite" in heading.get_text(strip=True).lower():
            sibling = heading.find_next_sibling(["p", "div", "ul", "dd"])
            if sibling:
                return sibling.get_text(separator=" ", strip=True)

    return None


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------

def tokenize(text: str) -> list:
    """
    Tokenize prerequisite text into a flat list of:
      - six-digit course codes (after dot-normalisation)
      - 'and'  (from literal 'and' or comma)
      - 'or'
      - '('
      - ')'

    The prerequisite header ("Prerequisite(s):") is stripped first.
    Dotted codes ("115.230") are normalised to "115230".
    Unknown characters are silently skipped.
    """
    # Normalise dotted course codes: '115.230' → '115230'
    text = _DOTTED_CODE_RE.sub(lambda m: m.group(1) + m.group(2), text)
    # Remove leading "Prerequisite(s):" header
    text = _HEADER_RE.sub("", text)

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
    """
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


# ---------------------------------------------------------------------------
# Batch scraper
# ---------------------------------------------------------------------------

def scrape_all(courses: list, concurrency: int = 8, timeout: int = 10) -> dict:
    """
    Scrape prerequisites for all courses in parallel.

    Args:
        courses:     List of course dicts with 'course_code' and 'url' keys.
        concurrency: Number of parallel workers. Keep low (≤10) to avoid
                     overwhelming the Massey CDN and triggering rate limits.
        timeout:     Per-request timeout in seconds.

    Returns a dict mapping course_code → structured prerequisite tree (or None).
    """
    results: dict[str, Any] = {}

    def _fetch(code: str, url: str) -> tuple[str, Any]:
        # Small random jitter so concurrent workers don't all fire simultaneously.
        time.sleep(random.uniform(0.05, 0.3))
        return code, scrape_prerequisites(url, timeout=timeout)

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
                logger.debug("Prereqs scraped %d/%d", done, total)

            try:
                result_code, prereqs = future.result()
                results[result_code] = prereqs
            except Exception as exc:
                logger.warning("Prerequisite scrape failed for %s: %s", code, exc)
                results[code] = None

    return results
