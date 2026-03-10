import time
from swiftype_client import search


def discover_qualifications():

    page = 1
    quals = []
    specs = []

    while True:

        print(f"Fetching qualification page {page}")

        payload = {
            "per_page": 100,
            "page": page,
            "sort_direction": {"course-qual": "asc"},
            "sort_field": {"course-qual": "title"},
            "filters": {
                "course-qual": {
                    "sub_type": {
                        "values": ["qual", "spec"]
                    }
                }
            },
            "fetch_fields": {
                "course-qual": [
                    "title",
                    "intro",
                    "url",
                    "sub_type",
                    "qual_code",
                    "qual_type",
                    "qual_title",
                    "qual_length",
                    "max_duration",
                    "nzqf_level"
                ]
            },
            "q": ""
        }

        data = search(payload)

        results = data["records"]["course-qual"]

        if not results:
            break

        for r in results:

            def safe(v):
                if isinstance(v, list):
                    return v[0] if v else None
                return v

            item = {
                "title": safe(r.get("title")),
                "url": safe(r.get("url")),
                "qual_code": safe(r.get("qual_code")),
                "type": safe(r.get("sub_type")),
                "level": safe(r.get("nzqf_level")),
                "length": safe(r.get("qual_length")),
                "max_duration": safe(r.get("max_duration")),
                "intro": safe(r.get("intro"))
            }

            if item["type"] == "qual":
                quals.append(item)
            else:
                specs.append(item)

        page += 1
        time.sleep(0.5)

    return quals, specs