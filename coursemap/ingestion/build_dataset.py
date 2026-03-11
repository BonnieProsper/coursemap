import json

from coursemap.ingestion.fetch_courses import discover_courses
from coursemap.ingestion.fetch_qualifications import discover_qualifications
from coursemap.ingestion.prerequisite_scraper import scrape_prerequisites


def build_dataset():

    print("Fetching courses...")

    courses = discover_courses()

    print("Scraping prerequisites...")

    for c in courses:

        if c["url"]:

            prereqs = scrape_prerequisites(c["url"])

            c["prerequisites"] = prereqs

    print("Fetching qualifications...")

    quals, specs = discover_qualifications()

    with open("datasets/courses.json", "w", encoding="utf8") as f:
        json.dump(courses, f, indent=2)

    with open("datasets/qualifications.json", "w", encoding="utf8") as f:
        json.dump(quals, f, indent=2)

    with open("datasets/specialisations.json", "w", encoding="utf8") as f:
        json.dump(specs, f, indent=2)

    print("Saved", len(courses), "courses")


if __name__ == "__main__":
    build_dataset()