import requests
import time

BASE = "https://www.massey.ac.nz"

API = BASE + "/search/api/"

PARAMS = {
    "size": 100,
    "from": 0,
    "filters[0][field]": "__search_type",
    "filters[0][values][0]": "course-qual",
    "filters[0][type]": "any",
    "filters[1][field]": "sub_type",
    "filters[1][values][0]": "course",
    "filters[1][type]": "all",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0",
}


def fetch_page(offset: int):

    params = PARAMS.copy()
    params["from"] = offset

    r = requests.get(API, headers=HEADERS, params=params, timeout=30)
    r.raise_for_status()

    return r.json()


def discover_courses():

    courses = []
    offset = 0

    while True:

        print("Fetching offset", offset)

        data = fetch_page(offset)

        results = data["results"]

        if not results:
            break

        for r in results:

            if r["sub_type"] != "course":
                continue

            courses.append({
                "title": r["title"],
                "url": BASE + r["url"],
                "code": r["course_code"]
            })

        offset += 100
        time.sleep(0.3)

    return courses


if __name__ == "__main__":

    courses = discover_courses()

    print("\nDiscovered", len(courses), "courses\n")

    for c in courses[:10]:
        print(c)