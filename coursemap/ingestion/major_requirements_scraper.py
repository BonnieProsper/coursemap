import requests
from bs4 import BeautifulSoup


def scrape_major_requirements(url):

    r = requests.get(url)
    soup = BeautifulSoup(r.text, "html.parser")

    text = soup.get_text(" ", strip=True)

    courses = []

    import re

    codes = re.findall(r"\b\d{6}\b", text)

    for c in codes:
        courses.append(c)

    return sorted(set(courses))