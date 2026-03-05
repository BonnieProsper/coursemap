import requests
from bs4 import BeautifulSoup

CATALOG_URL = "https://www.massey.ac.nz/study/courses/"
BASE = "https://www.massey.ac.nz"


def discover_course_links():
    r = requests.get(CATALOG_URL, timeout=20)
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")

    links = set()

    for a in soup.find_all("a", href=True):

        href = str(a.get("href", ""))

        if "/study/courses/" in href and href.count("/") >= 3:

            if href.startswith("http"):
                links.add(href)
            else:
                links.add(BASE + href)

    return sorted(links)


if __name__ == "__main__":

    links = discover_course_links()

    print("Discovered", len(links), "course pages\n")

    for l in links[:20]:
        print(l)