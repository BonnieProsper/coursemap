import requests
from bs4 import BeautifulSoup

BASE = "https://www.massey.ac.nz"

SEARCH_URL = "https://www.massey.ac.nz/search/"

PARAMS = {
    "size": "n_100_n",
    "filters[0][field]": "__search_type",
    "filters[0][type]": "all",
    "filters[0][values][0]": "course-qual",
    "filters[1][field]": "sub_type",
    "filters[1][values][0]": "course",
    "filters[1][type]": "any"
}

HEADERS = {"User-Agent": "Mozilla/5.0"}


def discover_courses():

    r = requests.get(SEARCH_URL, params=PARAMS, headers=HEADERS)

    soup = BeautifulSoup(r.text, "html.parser")

    courses = []

    for a in soup.select("a[href]"):

        href = str(a.get("href"))

        if "/study/courses/" in href:

            if not href.startswith("http"):
                href = BASE + href

            courses.append(href)

    return sorted(set(courses))


if __name__ == "__main__":

    links = discover_courses()

    print("Discovered", len(links), "courses\n")

    for l in links[:20]:
        print(l)