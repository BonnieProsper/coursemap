"""
Refresh prerequisite data in datasets/courses.json using the HTML-aware scraper.

Reads the existing courses.json, fetches each course's Massey page to extract
structured prerequisites (AND/OR logic), then writes the updated file back.

No Swiftype API key required -- only direct HTTP fetches to Massey's site.

Run from the repo root:

    python -m coursemap.ingestion.refresh_prerequisites

Options:
    --concurrency N   Parallel fetch workers (default: 20).
    --timeout N       Per-request timeout in seconds (default: 10).
    --limit N         Only process the first N courses (useful for testing).
    --dry-run         Parse and report without writing courses.json.
    --log-level       DEBUG | INFO | WARNING | ERROR (default: INFO).
"""
from __future__ import annotations
import argparse
import json
import logging
import os
import random
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from coursemap.ingestion.prerequisite_scraper import find_prereq_text, parse_prerequisite_text

logger = logging.getLogger(__name__)

_DATASETS_DIR = Path(__file__).resolve().parents[2] / "datasets"
_COURSES_PATH = _DATASETS_DIR / "courses.json"


def _fetch_prerequisites(code: str, url: str, timeout: int) -> tuple[str, object]:
    """
    Fetch one course page and return (code, parsed_prerequisite_tree).

    Returns (code, None) on any fetch or parse failure.
    """
    # Jitter prevents all workers from hammering the server simultaneously
    # at the start of each batch, which would trigger CDN rate limits.
    time.sleep(random.uniform(0.1, 0.5))
    try:
        r = requests.get(url, timeout=timeout,
                         headers={"User-Agent": (
                             "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                             "AppleWebKit/537.36 (KHTML, like Gecko) "
                             "Chrome/122.0.0.0 Safari/537.36"
                         )})
        if r.status_code != 200:
            logger.debug("HTTP %d for %s", r.status_code, url)
            return code, None
        soup = BeautifulSoup(r.text, "html.parser")
        text = find_prereq_text(soup)
        if not text:
            return code, None
        return code, parse_prerequisite_text(text)
    except Exception as exc:
        logger.debug("Failed to scrape prerequisites for %s: %s", code, exc)
        return code, None


def refresh_prerequisites(
    courses_path: Path = _COURSES_PATH,
    concurrency: int = 20,
    timeout: int = 10,
    limit: int | None = None,
    dry_run: bool = False,
    only_missing: bool = False,
) -> None:
    """
    Re-scrape prerequisites for all courses and update courses.json.

    Args:
        courses_path:  Path to courses.json.
        concurrency:   Number of parallel HTTP workers.
        timeout:       Per-request timeout in seconds.
        limit:         Cap on courses to process (None = all).
        dry_run:       If True, report changes without writing.
        only_missing:  If True, skip courses already using structured
                       (dict or str) format — only re-scrape flat-list
                       and null entries.
    """
    with open(courses_path, encoding="utf-8") as f:
        courses = json.load(f)

    # Build a map of code -> index for fast update
    index: dict[str, int] = {
        c["course_code"]: i
        for i, c in enumerate(courses)
        if c.get("course_code") and c.get("url")
    }

    to_process = [
        (c["course_code"], c["url"])
        for c in courses
        if c.get("course_code") and c.get("url")
        and (not only_missing or not isinstance(c.get("prerequisites"), (dict, str)))
    ]

    if limit:
        to_process = to_process[:limit]

    total = len(to_process)
    logger.info("Scraping prerequisites for %d courses (concurrency=%d)...", total, concurrency)

    updated = 0
    done = 0

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = {
            executor.submit(_fetch_prerequisites, code, url, timeout): code
            for code, url in to_process
        }
        for future in as_completed(futures):
            code = futures[future]
            done += 1
            if done % 100 == 0:
                logger.info("Progress: %d/%d", done, total)

            try:
                result_code, prereqs = future.result()
            except Exception as exc:
                logger.warning("Unexpected error for %s: %s", code, exc)
                continue

            if result_code in index:
                courses[index[result_code]]["prerequisites"] = prereqs
                if prereqs is not None:
                    updated += 1

    logger.info("Scraped %d courses; %d have prerequisites.", total, updated)

    if dry_run:
        logger.info("Dry run — courses.json not modified.")
        return

    # Atomic write
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=courses_path.parent,
        suffix=".tmp",
        delete=False,
    ) as tmp:
        tmp_path = Path(tmp.name)
        json.dump(courses, tmp, indent=2, ensure_ascii=False)

    os.replace(tmp_path, courses_path)
    logger.info("Wrote updated courses.json.")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--concurrency", type=int, default=8, metavar="N",
        help="Parallel fetch workers (default: 8). Keep low to avoid CDN rate limits.",
    )
    parser.add_argument(
        "--timeout", type=int, default=10, metavar="N",
        help="Per-request timeout in seconds (default: 10).",
    )
    parser.add_argument(
        "--limit", type=int, default=None, metavar="N",
        help="Only process the first N courses (for testing).",
    )
    parser.add_argument(
        "--dry-run", action="store_true", default=False,
        help="Parse and report without writing courses.json.",
    )
    parser.add_argument(
        "--only-missing", action="store_true", default=False,
        help=(
            "Skip courses that already have structured (AND/OR dict or single-code str) "
            "prerequisite data. Useful for incremental updates after a partial run."
        ),
    )
    parser.add_argument(
        "--log-level", default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO).",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s: %(message)s",
    )
    refresh_prerequisites(
        concurrency=args.concurrency,
        timeout=args.timeout,
        limit=args.limit,
        dry_run=args.dry_run,
        only_missing=args.only_missing,
    )
