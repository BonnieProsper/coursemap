import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import time

BASE = "https://www.massey.ac.nz"

# actual course listing pages
INDEX_PAGES = [
    "https://www.massey.ac.nz/study/courses/",
    "https://www.massey.ac.nz/study/courses/?page=2",
    "https://www.massey.ac.nz/study/courses/?page=3",
    "https://www.massey.ac.nz/study/courses/?page=4",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}


def fetch(url):

    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.text


def parse_course_links(html):

    soup = BeautifulSoup(html, "html.parser")

    courses = []

    for a in soup.find_all("a", href=True):

        href = str(a["href"])

        if "/course/" in href:

            url = urljoin(BASE, href)

            code = href.split("/")[-2] if href.endswith("/") else href.split("/")[-1]

            if code.isdigit():

                courses.append({
                    "code": code,
                    "url": url
                })

    return courses


def discover_courses():

    all_courses = []

    for page in INDEX_PAGES:

        print("Scanning", page)

        html = fetch(page)

        courses = parse_course_links(html)

        print("Found", len(courses))

        all_courses.extend(courses)

        time.sleep(0.5)

    unique = {c["code"]: c for c in all_courses}

    return list(unique.values())


if __name__ == "__main__":

    courses = discover_courses()

    print("\nDiscovered", len(courses), "courses\n")

    for c in courses[:10]:
        print(c)