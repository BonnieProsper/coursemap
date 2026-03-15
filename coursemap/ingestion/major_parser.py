"""
Parse major/specialisation pages into requirement node tree structure (dict form).
Output matches the JSON dataset format used by requirement_serialization.
"""
import re
from typing import Any, Dict, List

from bs4 import BeautifulSoup

COURSE_CODE_RE = re.compile(r"\b\d{6}\b")
# Match "45 credits", "Choose 45 credits", "45 credit" etc.
CREDITS_RE = re.compile(r"(?:choose\s+)?(\d+)\s*credits?", re.IGNORECASE)


def extract_course_codes(text: str) -> List[str]:
    return COURSE_CODE_RE.findall(text)


def _parse_credits_from_summary(summary_el) -> int:
    """Extract credit amount from a schedule summary element (e.g. 'Choose 45 credits')."""
    if not summary_el:
        return 0
    text = summary_el.get_text()
    match = CREDITS_RE.search(text)
    return int(match.group(1)) if match else 0


def parse_major_page(html: str) -> Dict[str, Any]:
    """
    Parse a major/specialisation page into a requirement tree (dict).
    Returns a single root node dict: {"type": "ALL_OF", "children": [...]}.
    """
    soup = BeautifulSoup(html, "html.parser")

    required_codes: List[str] = []
    elective_children: List[Dict[str, Any]] = []

    # -------------------------
    # Courses section schedules
    # -------------------------

    schedules = soup.select(".course-schedules")

    for schedule in schedules:
        summary = schedule.select_one(".course-schedules__header-credit-summary")
        courses = [
            c.get_text(strip=True)
            for c in schedule.select(".course-schedules__summary-code")
        ]

        if not courses:
            continue

        if summary and "Choose" in summary.get_text():
            credits = _parse_credits_from_summary(summary)
            elective_children.append({
                "type": "CHOOSE_CREDITS",
                "credits": credits,
                "course_codes": courses,
            })
        else:
            required_codes.extend(courses)

    # -------------------------
    # Planning information (additional required courses)
    # -------------------------

    planning = soup.find(id="planning-information")
    if planning:
        planning_block = planning.find_parent("details")
        if planning_block:
            codes = extract_course_codes(planning_block.get_text())
            required_codes.extend(codes)

    # Deduplicate required while preserving order for stable output
    seen = set()
    unique_required = []
    for c in required_codes:
        if c not in seen:
            seen.add(c)
            unique_required.append(c)

    # Build tree: ALL_OF( required COURSE nodes + elective CHOOSE_CREDITS nodes )
    course_children = [
        {"type": "COURSE", "course_code": code}
        for code in sorted(unique_required)
    ]
    children = course_children + elective_children

    return {
        "type": "ALL_OF",
        "children": children,
    }
