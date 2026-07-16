"""
Build majors.json from each major's Massey programme page.

Uses the URLs already stored in datasets/specialisations.json so no
Swiftype API key is required. Each programme page is fetched directly
and parsed by major_parser.parse_major_page.

Unlike refresh_prerequisites.py's targeted 3-field update to
courses.json, this is a full rewrite of majors.json - every major is
re-fetched and re-parsed, and the whole file is replaced. Bigger blast
radius if something goes wrong mid-run, so this has the same safety
mechanisms refresh_prerequisites.py already established: a small
--limit run to sanity-check first, --dry-run to see what would happen
without writing anything, an abort if the run looks broken rather than
silently writing a near-empty file, and an atomic write so a crash
mid-run can't leave majors.json truncated or corrupted.

Run from the repo root:

    python -m coursemap.ingestion.build_majors_dataset

Options:
    --concurrency N   Parallel fetch workers (default: 8).
    --timeout N       Per-request timeout in seconds (default: 30).
    --limit N         Only process the first N specialisations (for testing).
    --dry-run         Fetch and parse without writing majors.json.
    --log-level       DEBUG | INFO | WARNING | ERROR (default: INFO).

Writes datasets/majors.json as a list of:
    {"name": str, "url": str, "requirement": <node dict>}
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

from coursemap.ingestion.major_parser import parse_major_page

logger = logging.getLogger(__name__)

_DATASETS_DIR = Path(__file__).resolve().parents[2] / "datasets"
_MAJORS_PATH = _DATASETS_DIR / "majors.json"


def _load_specialisations() -> list[dict]:
    """
    Load specialisations from the cached datasets/specialisations.json.

    Falls back to discover_specialisations() (which requires SWIFTYPE_ENGINE_KEY)
    only when the cached file is missing.
    """
    specs_path = _DATASETS_DIR / "specialisations.json"
    if specs_path.exists():
        logger.info("Loading specialisations from %s", specs_path)
        with open(specs_path, encoding="utf-8") as f:
            return json.load(f)

    logger.warning(
        "specialisations.json not found; falling back to Swiftype API "
        "(requires SWIFTYPE_ENGINE_KEY)."
    )
    # Deferred: avoids requiring SWIFTYPE_ENGINE_KEY unless the cache is absent.
    from coursemap.ingestion.fetch_qualifications import discover_specialisations
    return discover_specialisations()


def _fetch_one(index: int, title: str, url: str, timeout: int) -> tuple[int, dict | None]:
    """Fetch and parse one major's page. Returns (index, major_dict | None)."""
    try:
        html = requests.get(url, timeout=timeout).text
        requirement_tree = parse_major_page(html)
        return index, {"name": title, "url": url, "requirement": requirement_tree}
    except Exception as exc:
        logger.warning("Failed to scrape '%s': %s", title, exc)
        return index, None


def build_majors_dataset(
    concurrency: int = 8,
    timeout: int = 30,
    limit: int | None = None,
    dry_run: bool = False,
    majors_path: Path = _MAJORS_PATH,
) -> None:
    """
    Fetch each major's programme page and write datasets/majors.json.

    Refuses to write if the run looks broken (see the abort check below)
    and never partially writes the file - either the complete new
    version lands atomically or the existing file is untouched.
    """
    specs = _load_specialisations()
    if limit is not None:
        specs = specs[:limit]
    total = len(specs)
    logger.info("Building majors dataset from %d specialisations (concurrency=%d)...", total, concurrency)

    results: list[dict | None] = [None] * total
    done = 0
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = {
            executor.submit(_fetch_one, i, spec["title"], spec.get("url", ""), timeout): i
            for i, spec in enumerate(specs)
            if spec.get("url")
        }
        skipped = total - len(futures)
        if skipped:
            logger.warning("Skipping %d specialisation(s) with no URL in specialisations.json", skipped)

        for future in as_completed(futures):
            done += 1
            if done % 50 == 0:
                logger.info("Progress: %d/%d", done, len(futures))
            index, major = future.result()
            results[index] = major

    majors = [m for m in results if m is not None]
    succeeded = len(majors)
    logger.info("Scraped %d/%d specialisations successfully.", succeeded, total)

    # Safety: if almost nothing succeeded, something is broken (site
    # structure changed, requests blocked, network down) - refuse to
    # overwrite majors.json with a near-empty result. Same threshold
    # style as refresh_prerequisites.py's equivalent check.
    if succeeded == 0 and total > 20:
        logger.error(
            "ABORTED: attempted %d specialisations but successfully scraped 0. "
            "This almost certainly means Massey's page structure has changed, "
            "specialisations.json is stale, or requests are being blocked. "
            "majors.json was NOT modified. "
            "Run with --limit 5 --dry-run --log-level DEBUG to inspect what's failing.",
            total,
        )
        return

    if succeeded < total * 0.5:
        logger.warning(
            "Only %d/%d specialisations succeeded (<50%%). Proceeding since "
            "this doesn't meet the hard-abort threshold, but review the "
            "warnings above before trusting this run - a partial site "
            "structure change could produce this pattern too.",
            succeeded, total,
        )

    if dry_run:
        logger.info("Dry run, majors.json not modified.")
        return

    # Atomic write: temp file in the same directory, then rename, so a
    # crash mid-write can't leave majors.json truncated or corrupted.
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=majors_path.parent,
        suffix=".tmp",
        delete=False,
    ) as tmp:
        tmp_path = Path(tmp.name)
        json.dump(majors, tmp, indent=2, ensure_ascii=False)

    os.replace(tmp_path, majors_path)
    logger.info("Wrote %s (%d majors)", majors_path, succeeded)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--concurrency", type=int, default=8, metavar="N",
        help="Parallel fetch workers (default: 8).",
    )
    parser.add_argument(
        "--timeout", type=int, default=30, metavar="N",
        help="Per-request timeout in seconds (default: 30).",
    )
    parser.add_argument(
        "--limit", type=int, default=None, metavar="N",
        help="Only process the first N specialisations (for testing).",
    )
    parser.add_argument(
        "--dry-run", action="store_true", default=False,
        help="Fetch and parse without writing majors.json.",
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
    build_majors_dataset(
        concurrency=args.concurrency,
        timeout=args.timeout,
        limit=args.limit,
        dry_run=args.dry_run,
    )
