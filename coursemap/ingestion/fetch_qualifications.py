import time
from coursemap.ingestion.swiftype_client import search

BASE = "https://www.massey.ac.nz"


def safe(v):
    if isinstance(v, list):
        return v[0] if v else None
    return v


def discover_qualifications():

    page = 1
    quals = []
    specs = []

    while True:

        print(f"Fetching qualification page {page}")

        payload = {
            "per_page": 100,
            "page": page,
            "filters": {
                "course-qual": {
                    "sub_type": {"values": ["qual", "spec"]}
                }
            },
            "fetch_fields": {
                "course-qual": [
                    "title",
                    "intro",
                    "url",
                    "sub_type",
                    "qual_code",
                    "qual_length",
                    "max_duration",
                    "nzqf_level",
                ]
            },
            "q": "",
        }

        data = search(payload)

        results = data["records"]["course-qual"]

        if not results:
            break

        for r in results:

            url = safe(r.get("url"))

            item = {
                "title": safe(r.get("title")),
                "url": BASE + url if url else None,
                "qual_code": safe(r.get("qual_code")),
                "type": safe(r.get("sub_type")),
                "level": safe(r.get("nzqf_level")),
                "length": safe(r.get("qual_length")),
                "max_duration": safe(r.get("max_duration")),
                "intro": safe(r.get("intro")),
            }

            if item["type"] == "qual":
                quals.append(item)
            elif item["type"] == "spec":
                specs.append(item)

        page += 1
        time.sleep(0.4)

    print(f"Discovered {len(quals)} qualifications")
    print(f"Discovered {len(specs)} specialisations")

    return quals, specs


def discover_specialisations():
    _, specs = discover_qualifications()
    return specs


if __name__ == "__main__":
    discover_qualifications()