import re
from bs4 import BeautifulSoup

COURSE_CODE_RE = re.compile(r"\b\d{6}\b")


def extract_course_codes(text: str):
    return COURSE_CODE_RE.findall(text)


def parse_major_page(html: str):

    soup = BeautifulSoup(html, "html.parser")

    required = set()
    elective_pools = []

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
            elective_pools.append(courses)
        else:
            required.update(courses)

    # -------------------------
    # Planning information
    # -------------------------

    planning = soup.find(id="planning-information")

    if planning:

        planning_block = planning.find_parent("details")

        if planning_block:

            codes = extract_course_codes(planning_block.get_text())

            required.update(codes)

    return {
        "required": sorted(required),
        "elective_pools": elective_pools,
    }