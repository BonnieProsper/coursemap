import requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0"}


def scrape_course(url):

    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")

    title = None
    code = None

    h1 = soup.find("h1")

    if h1:
        title = h1.get_text(strip=True)

    text = soup.get_text(" ", strip=True)

    credits = None
    level = None
    prerequisites = None
    restrictions = None

    for line in text.split("."):

        l = line.lower()

        if "credit" in l and credits is None:
            credits = line.strip()

        if "level" in l and level is None:
            level = line.strip()

        if "prerequisite" in l and prerequisites is None:
            prerequisites = line.strip()

        if "restriction" in l and restrictions is None:
            restrictions = line.strip()

    semesters = []

    for li in soup.find_all("li"):

        t = li.get_text(strip=True)

        if "semester" in t.lower():
            semesters.append(t)

    return {
        "title": title,
        "credits": credits,
        "level": level,
        "prerequisites": prerequisites,
        "restrictions": restrictions,
        "semesters": semesters
    }