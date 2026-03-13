import re
from bs4 import BeautifulSoup


COURSE_CODE_RE = re.compile(r"\b\d{6}\b")


def extract_course_codes(text: str) -> list[str]:
    """Extract 6-digit course codes."""
    return COURSE_CODE_RE.findall(text)


def parse_major_page(html: str) -> dict:
    """
    Parse a Massey major/specialisation page and extract
    required courses and elective pools.
    """
    soup = BeautifulSoup(html, "html.parser")

    required = set()
    elective_pools = []

    # -------------------------
    # 1. Parse planning section
    # -------------------------

    planning = soup.find(id="planning-information")

    if planning:
        planning_block = planning.find_parent("details")

        if planning_block:
            codes = extract_course_codes(planning_block.get_text())
            required.update(codes)

    # -------------------------
    # 2. Parse course schedules
    # -------------------------

    schedules = soup.select(".course-schedules")

    for schedule in schedules:

        summary = schedule.select_one(".course-schedules__header-credit-summary")

        courses = [
            code.get_text(strip=True)
            for code in schedule.select(".course-schedules__summary-code")
        ]

        if not courses:
            continue

        if summary and "Choose" in summary.get_text():
            elective_pools.append(courses)
        else:
            required.update(courses)

    return {
        "required": sorted(required),
        "elective_pools": elective_pools,
    }