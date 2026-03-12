import re
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

COURSE_RE = r"\b\d{6}\b"


def scrape_prerequisites(url):

    try:

        r = requests.get(url, timeout=5)

        if r.status_code != 200:
            return []

        text = r.text

        matches = re.findall(COURSE_RE, text)

        return list(set(matches))

    except Exception:
        return []


def scrape_all(courses):

    results = {}

    with ThreadPoolExecutor(max_workers=20) as executor:

        futures = {
            executor.submit(scrape_prerequisites, c["url"]): c["course_code"]
            for c in courses
            if c.get("url")
        }

        total = len(futures)
        completed = 0

        for future in as_completed(futures):

            code = futures[future]
            completed += 1

            if completed % 50 == 0:
                print(f"Prereqs scraped {completed}/{total}")

            try:
                results[code] = future.result()
            except Exception:
                results[code] = []

    return results