import time
import json

from coursemap.ingestion.swiftype_client import search

BASE = "https://www.massey.ac.nz"


def safe(v):

    if isinstance(v, list):
        return v[0] if v else None
    return v


def parse_offerings(v):

    if not v:
        return []

    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:
            return []

    return v


def discover_courses():

    page = 1
    courses = []

    while True:

        print(f"Fetching course page {page}")

        payload = {
            "per_page": 100,
            "page": page,
            "filters": {
                "course-qual": {
                    "sub_type": {"values": ["course"]}
                }
            },
            "fetch_fields": {
                "course-qual": [
                    "title",
                    "intro",
                    "url",
                    "course_code",
                    "course_credit_float",
                    "subject_areas",
                    "course_level",
                    "nzqf_level",
                    "locations",
                    "delivery_mode",
                    "year",
                    "semester",
                    "offerings_json"
                ]
            },
            "q": ""
        }

        data = search(payload)

        results = data["records"]["course-qual"]

        if not results:
            break

        for r in results:

            url = safe(r.get("url"))

            course = {

                "course_code": safe(r.get("course_code")),

                "title": safe(r.get("title")),

                "url": BASE + url if url else None,

                "credits": r.get("course_credit_float"),

                "level": safe(r.get("nzqf_level")),

                "course_level": safe(r.get("course_level")),

                "subjects": r.get("subject_areas"),

                "intro": safe(r.get("intro")),

                "offerings": parse_offerings(r.get("offerings_json")),

                "prerequisites": [],

                "corequisites": [],

                "restrictions": []
            }

            courses.append(course)

        page += 1

        time.sleep(0.4)

    return courses