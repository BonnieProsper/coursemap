import re
import requests
from bs4 import BeautifulSoup

CODE_RE = re.compile(r"\b\d{6}\b")


def extract_codes(text):
    return CODE_RE.findall(text)


def fetch_html(url: str) -> BeautifulSoup:
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")


def parse_major_page(url: str):
    soup = fetch_html(url)

    required = set()
    elective_pools = []

    current_level = None

    for header in soup.find_all(["h2", "h3", "h4"]):

        title = header.get_text(strip=True).lower()

        if "100-level" in title:
            current_level = 100
        elif "200-level" in title:
            current_level = 200
        elif "300-level" in title:
            current_level = 300
        else:
            continue

        ul = header.find_next("ul")
        if not ul:
            continue

        pool_codes = set()

        for li in ul.find_all("li"):
            text = li.get_text(" ", strip=True)
            codes = extract_codes(text)

            if not codes:
                continue

            if "choose" in text.lower():
                pool_codes.update(codes)
            else:
                required.update(codes)

        if pool_codes:
            elective_pools.append({
                "level": current_level,
                "codes": list(pool_codes)
            })

    return {
        "required": sorted(required),
        "elective_pools": elective_pools
    }


def scrape_majors():
    majors = {
        "statistics": "https://www.massey.ac.nz/study/all-qualifications-and-degrees/bachelor-of-science-UBSCN/statistics-UBSCN2JSTTS1/",
        "computer_science": "https://www.massey.ac.nz/study/all-qualifications-and-degrees/bachelor-of-science-UBSCN/computer-science-UBSCN2JCOMP1/",
    }

    data = {}

    for name, url in majors.items():
        print("Scraping", name)
        data[name] = parse_major_page(url)

    return data