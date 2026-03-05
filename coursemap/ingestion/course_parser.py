import re
from bs4 import BeautifulSoup


def parse_course(html: str):
    soup = BeautifulSoup(html, "html.parser")

    text = soup.get_text("\n")

    credits = re.search(r"(\d+)\s+credits", text, re.I)
    level = re.search(r"Level\s*(\d+)", text)

    offerings = []
    if "Semester 1" in text:
        offerings.append("S1")
    if "Semester 2" in text:
        offerings.append("S2")

    return {
        "credits": int(credits.group(1)) if credits else None,
        "level": int(level.group(1)) if level else None,
        "offerings": offerings,
    }