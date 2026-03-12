import json

from coursemap.ingestion.fetch_courses import discover_courses
from coursemap.ingestion.fetch_qualifications import discover_qualifications
from coursemap.ingestion.prerequisite_scraper import scrape_all


def build_dataset():

    print("Fetching courses...")
    courses = discover_courses()

    print("Scraping prerequisites...")
    prereqs = scrape_all(courses)

    for c in courses:
        c["prerequisites"] = prereqs.get(c["course_code"], [])

    print("Fetching qualifications...")
    quals, specs = discover_qualifications()

    with open("datasets/courses.json", "w", encoding="utf8") as f:
        json.dump(courses, f, indent=2)

    with open("datasets/qualifications.json", "w", encoding="utf8") as f:
        json.dump(quals, f, indent=2)

    with open("datasets/specialisations.json", "w", encoding="utf8") as f:
        json.dump(specs, f, indent=2)

    print("Dataset build complete")


if __name__ == "__main__":
    build_dataset()