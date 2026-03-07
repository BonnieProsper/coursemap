import time
import requests
from pathlib import Path

from .massey_api_scraper import discover_courses
from .course_parser import parse_course


CACHE_DIR = Path("datasets/raw_pages")
CACHE_DIR.mkdir(parents=True, exist_ok=True)


HEADERS = {
    "User-Agent": "Mozilla/5.0"
}


def fetch_page(url):

    code = url.split("/")[-2].split("-")[0]

    cache_file = CACHE_DIR / f"{code}.html"

    if cache_file.exists():
        return cache_file.read_text(encoding="utf-8")

    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()

    html = r.text

    cache_file.write_text(html, encoding="utf-8")

    time.sleep(0.4)

    return html


def scrape_all_courses():

    links = discover_courses()

    courses = []

    print(f"\nDiscovered {len(links)} course pages\n")

    for url in links:

        try:

            html = fetch_page(url)

            parsed = parse_course(html)

            parsed["url"] = url

            courses.append(parsed)

            print("Scraped", parsed["code"])

        except Exception as e:

            print("Failed:", url, e)

    return courses


if __name__ == "__main__":

    scrape_all_courses()