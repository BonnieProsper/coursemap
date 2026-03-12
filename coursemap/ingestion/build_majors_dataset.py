import json
from pathlib import Path

from coursemap.ingestion.major_requirements_scraper import scrape_major
from coursemap.ingestion.massey_majors import MAJOR_PAGES

DATASET = Path("datasets/majors.json")


def build_majors():

    majors = {}

    for name, url in MAJOR_PAGES.items():

        print(f"Scraping {name}")

        major = scrape_major(url, name)

        majors[name] = {
            "core_courses": major["core_courses"],
            "elective_pools": major["elective_pools"],
        }

    DATASET.parent.mkdir(exist_ok=True)

    with open(DATASET, "w") as f:
        json.dump(majors, f, indent=2)

    print("Majors dataset written")


if __name__ == "__main__":
    build_majors()