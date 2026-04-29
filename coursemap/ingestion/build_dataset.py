"""
Build script: assembles the full dataset from scraped sources.

Run from the repo root:

    python -m coursemap.ingestion.build_dataset

Writes:
    datasets/courses.json         -- 2,766 courses with offerings
    datasets/qualifications.json  -- 176 qualification records
    datasets/specialisations.json -- 380 specialisation (major) records

Prerequisites are scraped separately via prerequisite_scraper, then merged
into courses.json by this script.
"""
from __future__ import annotations
import json
import logging

from coursemap.ingestion.fetch_courses import discover_courses
from coursemap.ingestion.fetch_qualifications import discover_qualifications
from coursemap.ingestion.prerequisite_scraper import scrape_all
from pathlib import Path

logger = logging.getLogger(__name__)

_DATASETS_DIR = Path(__file__).resolve().parents[2] / "datasets"


def build_dataset() -> None:
    """Scrape all data sources and write the three dataset JSON files."""
    logger.info("Fetching courses...")
    courses = discover_courses()

    logger.info("Scraping prerequisites for %d courses...", len(courses))
    prereqs = scrape_all(courses)
    for course in courses:
        course["prerequisites"] = prereqs.get(course["course_code"], [])

    logger.info("Fetching qualifications and specialisations...")
    quals, specs = discover_qualifications()

    with open(_DATASETS_DIR / "courses.json", "w", encoding="utf-8") as f:
        json.dump(courses, f, indent=2)
    logger.info("Wrote datasets/courses.json (%d courses)", len(courses))

    with open(_DATASETS_DIR / "qualifications.json", "w", encoding="utf-8") as f:
        json.dump(quals, f, indent=2)
    logger.info("Wrote datasets/qualifications.json (%d qualifications)", len(quals))

    with open(_DATASETS_DIR / "specialisations.json", "w", encoding="utf-8") as f:
        json.dump(specs, f, indent=2)
    logger.info("Wrote datasets/specialisations.json (%d specialisations)", len(specs))

    logger.info("Dataset build complete.")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s: %(message)s",
    )
    build_dataset()
