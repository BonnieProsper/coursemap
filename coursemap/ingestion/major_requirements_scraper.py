import re
import requests
from bs4 import BeautifulSoup

CODE_RE = re.compile(r"\b\d{6}\b")


def scrape_major(url: str, name: str):

    r = requests.get(url, timeout=20)
    soup = BeautifulSoup(r.text, "html.parser")

    core_courses = []
    elective_pools = []

    for header in soup.find_all(["h2", "h3", "h4"]):

        title = header.get_text(strip=True).lower()

        ul = header.find_next("ul")

        if not ul:
            continue

        codes = []

        for li in ul.find_all("li"):
            text = li.get_text(" ", strip=True)
            matches = CODE_RE.findall(text)
            codes.extend(matches)

        if not codes:
            continue

        # core courses
        if "compulsory" in title or "core" in title:
            core_courses.extend(codes)

        # electives
        elif "choose" in title or "elective" in title:
            elective_pools.append({
                "courses": codes,
                "min_courses": 1
            })

        # level blocks often contain core courses
        elif "100-level" in title or "200-level" in title or "300-level" in title:
            core_courses.extend(codes)

    return {
        "name": name,
        "core_courses": sorted(set(core_courses)),
        "elective_pools": elective_pools
    }