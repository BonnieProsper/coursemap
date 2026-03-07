import requests
import time

BASE = "https://www.massey.ac.nz"

SEARCH_API = "https://www.massey.ac.nz/api/search"

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json"
}


PARAMS = {
    "size": 100,
    "filters[0][field]": "__search_type",
    "filters[0][values][0]": "course-qual",
    "filters[0][type]": "any",
    "filters[1][field]": "sub_type",
    "filters[1][values][0]": "course",
    "filters[1][type]": "all"
}


def fetch_page(start_rank: int):

    params = PARAMS.copy()
    params["start_rank"] = start_rank

    r = requests.get(
        SEARCH_API,
        headers=HEADERS,
        params=params,
        timeout=30
    )

    r.raise_for_status()

    return r.json()


def discover_courses():

    all_courses = []

    start = 0

    while True:

        print("Fetching", start)

        data = fetch_page(start)

        results = data.get("results", [])

        if not results:
            break

        for r in results:

            title = r.get("title")

            url = r.get("url")

            if url and not url.startswith("http"):
                url = BASE + url

            all_courses.append({
                "title": title,
                "url": url
            })

        start += 100

        time.sleep(0.5)

    return all_courses


if __name__ == "__main__":

    courses = discover_courses()

    print("\nTotal courses:", len(courses))

    for c in courses[:10]:
        print(c)