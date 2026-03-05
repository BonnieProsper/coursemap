import re
from bs4 import BeautifulSoup


CODE_PATTERN = re.compile(r"([A-Z]{3,4}\d{3})")


def parse_course(html):

    soup = BeautifulSoup(html, "html.parser")

    text = soup.get_text("\n")

    # course code
    code_match = CODE_PATTERN.search(text)

    code = code_match.group(1) if code_match else None

    # title
    title_tag = soup.find("h1")
    title = title_tag.get_text(strip=True) if title_tag else None

    # credits
    credits_match = re.search(r"(\d+)\s*credits", text, re.I)
    credits = int(credits_match.group(1)) if credits_match else None

    # level
    level_match = re.search(r"Level\s*(\d+)", text)
    level = int(level_match.group(1)) if level_match else None

    # offerings
    offerings = []

    if "Semester 1" in text:
        offerings.append("S1")

    if "Semester 2" in text:
        offerings.append("S2")

    if "Summer School" in text:
        offerings.append("SS")

    # prerequisites
    prereq_match = re.search(r"Prerequisite[s]?:\s*(.+)", text)

    prereqs = prereq_match.group(1) if prereq_match else None

    return {
        "code": code,
        "title": title,
        "credits": credits,
        "level": level,
        "offerings": offerings,
        "prerequisites": prereqs
    }