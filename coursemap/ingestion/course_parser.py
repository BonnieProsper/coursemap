import re
from bs4 import BeautifulSoup


def parse_course(html):

    soup = BeautifulSoup(html, "html.parser")

    text = soup.get_text("\n")

    # title
    title_match = re.search(r"([A-Z]{4}\d{3})\s+(.+)", text)

    # credits
    credits_match = re.search(r"(\d+)\s+credits", text, re.I)

    # level
    level_match = re.search(r"Level\s*(\d+)", text)

    # offerings
    offerings = []
    if "Semester 1" in text:
        offerings.append("S1")
    if "Semester 2" in text:
        offerings.append("S2")

    # prerequisites
    prereq_match = re.search(r"Prerequisite[s]?:\s*(.+)", text)

    return {
        "title": title_match.group(2) if title_match else None,
        "credits": int(credits_match.group(1)) if credits_match else None,
        "level": int(level_match.group(1)) if level_match else None,
        "offerings": offerings,
        "prerequisites": prereq_match.group(1) if prereq_match else None
    }