import json
from pathlib import Path

from .massey_scraper import scrape_all_courses


DATA_DIR = Path("datasets")
DATA_DIR.mkdir(exist_ok=True)


def build_dataset():

    courses = scrape_all_courses()

    file = DATA_DIR / "courses.json"

    file.write_text(json.dumps(courses, indent=2), encoding="utf-8")

    print("\nSaved", len(courses), "courses to", file)


if __name__ == "__main__":
    build_dataset()