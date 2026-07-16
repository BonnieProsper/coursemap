"""
Parse major/specialisation pages into requirement node tree structure (dict form).
Output matches the JSON dataset format used by requirement_serialization.

Current Massey page structure (as of 2026):
- Required courses: inside a <details> block with heading "Planning information",
  listed as <li><a href="/study/courses/XXXXXX/">XXXXXX</a> Title</li>
- Elective pools: inside .course-schedules blocks with a "Choose N credits from"
  header in .course-schedules__header-credit-summary

Fallback strategies handle older page layouts and postgrad pages that lack a
Planning information block.
"""
from __future__ import annotations
import re
from typing import Any

from bs4 import BeautifulSoup

# Matches a 6-digit course code in a Massey course URL path.
COURSE_URL_RE = re.compile(r'/study/courses/(\d{6})/', re.IGNORECASE)
# Matches "Choose N credits" or "N credits" in a schedule summary.
CREDITS_RE = re.compile(r'(?:choose\s+)?(\d+)\s*credits?', re.IGNORECASE)
# Strips "Course code:" prefix that appears in .course-schedules__summary-code text.
_CODE_PREFIX_RE = re.compile(r'^[Cc]ourse\s+[Cc]ode:\s*', re.IGNORECASE)
# A bare 6-digit course code in plain prose text (as opposed to COURSE_URL_RE,
# which matches inside a URL path). Used to pull codes out of a "Planning
# information" bullet's own wording, not its links, since a choice clause's
# codes appear as visible text right after the trigger phrase (see
# _PLANNING_CHOICE_RE below) and the bullet's <a> tags don't distinguish
# "part of the choice" from "mentioned afterward as an aside".
_COURSE_CODE_TEXT_RE = re.compile(r'\b\d{6}\b')
# Live-verified phrasing (course "Computer Science - Bachelor of Information
# Sciences") for a choice expressed in a Planning information bullet's prose,
# rather than Massey's structured .course-schedules "Choose N credits" widget
# handled by Step 2 below: "one or more of 160105, 160101, 160102" and
# "one of 161111 or 297101". Same restrained scope as the "one of"/"any of"
# regex in prerequisite_scraper.py and for the same reason: only rewrite
# phrasing actually observed on a live page, not phrasing guessed at.
_PLANNING_CHOICE_RE = re.compile(
    r'\b(?:one or more of|at least one of|one of|any of)\b', re.IGNORECASE,
)


def _clean_code(raw: str) -> str:
    """Strip 'Course code:' prefix and whitespace from a raw code string."""
    return _CODE_PREFIX_RE.sub('', raw).strip()


def parse_major_page(html: str) -> dict[str, Any]:
    """
    Parse a major/specialisation page into a requirement tree (dict).

    Returns a single root node dict: {"type": "ALL_OF", "children": [...]}.

    Children are a mix of:
    - {"type": "COURSE", "course_code": "XXXXXX"} for individually required courses
    - {"type": "CHOOSE_CREDITS", "credits": N, "course_codes": [...]} for elective pools

    Parsing strategy (tried in order):

    1. Required courses from the "Planning information" <details> block:
       Massey's current specialisation pages include a collapsible "Planning
       information" section that lists required courses year-by-year as
       <li><a href="/study/courses/XXXXXX/">XXXXXX</a> Title</li> items.

    2. Elective pools from .course-schedules blocks with "Choose N credits from"
       headers. These are present on all current Massey pages.

    3. Non-choose .course-schedules blocks as required courses (older layout).

    4. Fallback: if no required codes found after steps 1-3, scan all
       <li><a href="/study/courses/XXXXXX/"> links outside .course-schedules.
       This handles postgrad pages and any page without a planning block.

    Courses that appear in elective pools are excluded from the required list
    to avoid double-scheduling.
    """
    soup = BeautifulSoup(html, 'html.parser')

    required_codes: list[str] = []
    elective_children: list[dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Step 1: Required courses from "Planning information" <details> block
    # ------------------------------------------------------------------
    planning_details = None
    for d in soup.find_all('details'):
        # Check the <summary> tag or first heading inside
        summary_tag = d.find('summary') or d.find(['h2', 'h3', 'h4'])
        if summary_tag and 'planning information' in summary_tag.get_text().lower():
            planning_details = d
            break

    if planning_details:
        for li in planning_details.find_all('li'):
            # Skip items inside .course-schedules (elective pool entries)
            if li.find_parent(class_='course-schedules'):
                continue

            li_text = li.get_text(' ', strip=True)
            choice_match = _PLANNING_CHOICE_RE.search(li_text)
            if choice_match:
                # Only the codes in the same sentence as the trigger phrase
                # are part of the choice. A bullet can go on to mention
                # another code afterward as a mere aside (live example:
                # "one or more of 160105, 160101, 160102. Note: you can
                # also take 160104 as an elective in your degree") -
                # 160104 must NOT be pulled into the requirement just for
                # being linked in the same <li>.
                period_pos = li_text.find('.', choice_match.end())
                span_end = period_pos if period_pos != -1 else len(li_text)
                span_text = li_text[choice_match.end():span_end]
                choice_codes = _COURSE_CODE_TEXT_RE.findall(span_text)
                if choice_codes:
                    elective_children.append({
                        'type': 'CHOOSE_CREDITS',
                        # No credit figure is ever stated for this prose
                        # form (unlike .course-schedules' explicit "Choose
                        # N credits" header, handled in Step 2 below) - 15
                        # is the credit value of every course observed
                        # anywhere in this codebase's data, not a
                        # page-stated fact for this specific pool. Flagged
                        # in DATA_QUALITY.md for spot-verification once
                        # pools like this exist in a fresh scrape.
                        'credits': 15,
                        'course_codes': choice_codes,
                    })
                    continue

            a = li.find('a', href=COURSE_URL_RE)
            if a:
                m = COURSE_URL_RE.search(a.get('href', ''))
                if m:
                    code = m.group(1)
                    if code not in required_codes:
                        required_codes.append(code)

    # ------------------------------------------------------------------
    # Step 2: Elective pools from .course-schedules (all page layouts)
    # ------------------------------------------------------------------
    for schedule in soup.select('.course-schedules'):
        summary = schedule.select_one('.course-schedules__header-credit-summary')
        raw_codes = [
            c.get_text(strip=True)
            for c in schedule.select('.course-schedules__summary-code')
        ]
        if not raw_codes:
            continue

        if summary and 'choose' in summary.get_text().lower():
            credits = 0
            m = CREDITS_RE.search(summary.get_text())
            if m:
                credits = int(m.group(1))
            elective_children.append({
                'type': 'CHOOSE_CREDITS',
                'credits': credits,
                'course_codes': raw_codes,
            })
        else:
            # Non-choose schedule block = required courses
            for raw in raw_codes:
                code = _clean_code(raw)
                if code and code not in required_codes:
                    required_codes.append(code)

    # ------------------------------------------------------------------
    # Step 3: fallback, scan all <li><a href="/study/courses/XXXXXX/">
    # Used when no planning block found (postgrad, older layouts).
    # ------------------------------------------------------------------
    if not required_codes:
        for li in soup.find_all('li'):
            if li.find_parent(class_='course-schedules'):
                continue
            a = li.find('a', href=COURSE_URL_RE)
            if a:
                m = COURSE_URL_RE.search(a.get('href', ''))
                if m:
                    code = m.group(1)
                    if code not in required_codes:
                        required_codes.append(code)

    # ------------------------------------------------------------------
    # Build tree: required COURSE nodes + elective CHOOSE_CREDITS nodes.
    # Courses that appear in elective pools are excluded from the required
    # list. The planner will select them as electives instead.
    # ------------------------------------------------------------------
    elective_pool_codes: set[str] = set()
    for e in elective_children:
        for raw in e.get('course_codes', []):
            elective_pool_codes.add(_clean_code(raw))

    course_children = [
        {'type': 'COURSE', 'course_code': code}
        for code in dict.fromkeys(required_codes)   # deduplicate, preserve order
        if code not in elective_pool_codes
    ]

    return {
        'type': 'ALL_OF',
        'children': course_children + elective_children,
    }
