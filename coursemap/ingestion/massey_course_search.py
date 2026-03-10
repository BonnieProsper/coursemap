import requests
import time
import json


API_URL = "https://search-api.swiftype.com/api/v1/public/engines/search.json"

ENGINE_KEY = "8gdyLPudn1LsT169k6g6"

HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0"
}


def fetch_page(page):

    payload = {
        "engine_key": ENGINE_KEY,
        "per_page": 100,
        "page": page,
        "sort_direction": {"course-qual": "asc"},
        "sort_field": {"course-qual": "title"},
        "facets": {
            "course-qual": [
                "sub_type",
                "qual_type",
                "study_level",
                "campus_code",
                "course_level",
                "delivery_mode",
                "semester",
                "subject_areas",
                "year",
                "location",
                "is_international_available"
            ]
        },
        "fetch_fields": {
            "course-qual": [
                "title",
                "intro",
                "url",
                "sub_type",
                "qual_code",
                "course_code",
                "qual_type",
                "qual_title",
                "credits",
                "course_credit_float",
                "locations",
                "qual_length",
                "max_duration",
                "nzqf_level",
                "offerings_json"
            ]
        },
        "highlight_fields": {
            "course-qual": {
                "title": {"size": 100, "fallback": True},
                "course_code": {"size": 100}
            }
        },
        "q": ""
    }

    r = requests.post(API_URL, json=payload, headers=HEADERS, timeout=30)
    r.raise_for_status()

    return r.json()


def discover_courses():

    page = 1
    courses = []

    while True:

        print(f"Fetching page {page}")

        data = fetch_page(page)

        results = data["records"]["course-qual"]

        if not results:
            break

        for r in results:

            def safe(v):
                if isinstance(v, list):
                    return v[0] if v else None
                return v
            
            def parse_offerings(v):
                if not v:
                    return []
                if isinstance(v, str):
                    return json.loads(v)
                return v


            course = {
                "title": safe(r.get("title")),
                "url": safe(r.get("url")),
                "course_code": safe(r.get("course_code")),
                "credits": r.get("course_credit_float"),
                "level": r.get("nzqf_level"),
                "intro": safe(r.get("intro")),
                "offerings": parse_offerings(r.get("offerings_json", []))
            }

            courses.append(course)

        page += 1

        time.sleep(0.5)

    return courses


if __name__ == "__main__":

    courses = discover_courses()

    print("\nDiscovered", len(courses), "courses")

    for c in courses[:10]:
        print(c)