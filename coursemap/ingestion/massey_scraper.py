import time
import requests
from pathlib import Path

from .massey_catalog_crawler import discover_course_links
from .course_parser import parse_course


CACHE_DIR = Path("datasets/raw_pages")
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def fetch_page(url):

    code = url.split("/")[-2]

    cache_file = CACHE_DIR / f"{code}.html"

    if cache_file.exists():
        return cache_file.read_text(encoding="utf-8")

    r = requests.get(url, timeout=20)
    r.raise_for_status()

    html = r.text

    cache_file.write_text(html, encoding="utf-8")

    time.sleep(0.4)

    return html


def scrape_all_courses():

    links = discover_course_links()

    courses = []

    print(f"Found {len(links)} course links\n")

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