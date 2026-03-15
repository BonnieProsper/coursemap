"""
Build majors.json: list of { "name", "url", "requirement" } where requirement
is a requirement node tree (dict) matching domain/requirement_serialization format.
"""
import json
import requests

from coursemap.ingestion.fetch_qualifications import discover_specialisations
from coursemap.ingestion.major_parser import parse_major_page


def build_majors_dataset() -> None:
    specs = discover_specialisations()
    majors = []

    print(f"Found {len(specs)} specialisations")

    for i, spec in enumerate(specs):
        title = spec["title"]
        url = spec["url"]

        print(f"Scraping {i+1}/{len(specs)}: {title}")

        try:
            html = requests.get(url, timeout=30).text
            requirement_tree = parse_major_page(html)
            majors.append({
                "name": title,
                "url": url,
                "requirement": requirement_tree,
            })
        except Exception as e:
            print(f"Failed: {title} ({e})")

    with open("datasets/majors.json", "w", encoding="utf-8") as f:
        json.dump(majors, f, indent=2)

    print("Majors dataset written")


if __name__ == "__main__":
    build_majors_dataset()
