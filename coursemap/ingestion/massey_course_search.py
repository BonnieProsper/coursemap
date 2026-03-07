import requests
import time
from bs4 import BeautifulSoup
from urllib.parse import urljoin

BASE = "https://www.massey.ac.nz"

SEARCH_URL = BASE + "/search/"

PARAMS = {
    "size": "n_100_n",
    "filters[0][field]": "__search_type",
    "filters[0][values][0]": "course-qual",
    "filters[0][type]": "any",
    "filters[1][field]": "sub_type",
    "filters[1][values][0]": "course",
    "filters[1][type]": "all",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}


def fetch_page(page: int):

    params = PARAMS.copy()

    # pagination
    params["from"] = str(page * 100)

    r = requests.get(
        SEARCH_URL,
        headers=HEADERS,
        params=params,
        timeout=30
    )

    r.raise_for_status()

    return r.text

import re

def parse_courses(html):

    soup = BeautifulSoup(html, "html.parser")

    courses = []

    pattern = re.compile(r"\b\d{6}\b")

    for element in soup.find_all(string=pattern):

        match = pattern.search(element)

        if match:

            code = match.group()

            title = element.strip()

            url = f"{BASE}/course/{code}"

            courses.append({
                "title": title,
                "url": url,
                "code": code
            })

    return courses


def discover_courses():

    all_courses = []

    for page in range(30):

        print("Scanning page", page)

        html = fetch_page(page)

        courses = parse_courses(html)

        print("Found", len(courses))

        all_courses.extend(courses)

        time.sleep(0.5)

    # remove duplicates
    unique = {c["url"]: c for c in all_courses}

    return list(unique.values())


if __name__ == "__main__":

    courses = discover_courses()

    print("\nDiscovered", len(courses), "course pages\n")

    for c in courses[:10]:
        print(c)