"""
Backfill elective pool credit values in datasets/majors.json.

Background
----------
majors.json stores elective pools as bare lists of course codes because the
original scraper did not capture the "Choose N credits from the following"
header text from each major's Massey page.  As a result, every CHOOSE_CREDITS
node produced at runtime has ``credits=0``, making the solver treat each pool
as an unrestricted pick-any elective rather than a structured requirement.

What this script does
---------------------
For each major in majors.json:

1. Fetch the major's URL (already stored in the dataset).
2. Parse the HTML with ``major_parser.parse_major_page``, which extracts
   CHOOSE_CREDITS nodes including the credit value from the page header.
3. Match each parsed elective pool to an existing pool entry using Jaccard
   similarity of course codes (threshold 0.5; at least half the codes must
   overlap).
4. Convert the matched pool from the old list format::

       ["Course code:214213", "Course code:214215", ...]

   to the new backfilled dict format::

       {"credits": 45, "courses": ["Course code:214213", "Course code:214215", ...]}

5. Write majors.json back atomically (write to a temp file then rename so a
   crash mid-write does not corrupt the dataset).

Idempotency
-----------
Pools already in the dict format are detected by ``isinstance(pool, dict)``.
Running the script again:
- Pools that have been backfilled: skipped (already correct).
- Pools still in list format: re-attempted (useful if a previous run was
  interrupted or a page fetch failed).

Safety
------
- Pools whose parsed credit value is 0 (no "Choose N credits" header found)
  are skipped (a credits=0 backfill is indistinguishable from the default
  and provides no improvement.
- Pools with Jaccard similarity < 0.5 between parsed and stored codes are
  skipped; ambiguous matches are left unchanged rather than potentially
  corrupted.
- Skipped pools remain in their original list format so they continue to work
  as before (unrestricted pools).
- The dataset file is never partially written; atomic rename guarantees
  either the full new version or the full old version is on disk.

Running
-------
From the repository root::

    python -m coursemap.ingestion.backfill_elective_credits

Optional flags::

    --dry-run     Print planned changes without writing anything.
    --concurrency N  Parallel fetch workers (default: 10).
    --timeout N   HTTP timeout in seconds per request (default: 20).
    --majors-path PATH  Path to majors.json (default: datasets/majors.json).
"""

from __future__ import annotations
import argparse
import json
import logging
import os
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import re
import requests

from coursemap.ingestion.major_parser import parse_major_page

# Matches any bare 6-digit course code in a raw string.
_COURSE_CODE_RE = re.compile(r'\b(\d{6})\b')

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Minimum Jaccard similarity between parsed and stored course-code sets for a
# pool match to be considered confident.
MATCH_THRESHOLD = 0.5

# Default path: resolved relative to this file so the script can be run from
# any working directory.
_THIS_DIR = Path(__file__).resolve().parent
_DEFAULT_MAJORS_PATH = _THIS_DIR.parents[1] / "datasets" / "majors.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalise_codes(raw_codes: list[str]) -> set:
    """
    Extract bare six-digit course codes from a list of raw strings.

    Handles both 'Course code:214213' and '214213' formats.
    """
    result = set()
    for raw in raw_codes:
        for code in _COURSE_CODE_RE.findall(raw):
            result.add(code)
    return result


def _pool_codes(pool: Any) -> set:
    """Return the set of course codes for a pool in either old or new format."""
    if isinstance(pool, dict):
        return _normalise_codes(pool.get("courses", []))
    return _normalise_codes(pool)


def _jaccard(a: set, b: set) -> float:
    """Jaccard similarity between two sets (0.0–1.0)."""
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def _is_backfilled(pool: Any) -> bool:
    """Return True if the pool has already been converted to the dict format."""
    return isinstance(pool, dict)


# ---------------------------------------------------------------------------
# Per-major processing
# ---------------------------------------------------------------------------

def _fetch_html(url: str, timeout: int, retries: int = 2) -> str | None:
    """
    Fetch a URL and return the response text, or None on failure.

    Retries up to ``retries`` times on transient errors with a 1-second delay.
    """
    for attempt in range(retries + 1):
        try:
            resp = requests.get(url, timeout=timeout)
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as exc:
            if attempt < retries:
                logger.debug("Fetch attempt %d failed for %s: %s; retrying", attempt + 1, url, exc)
                time.sleep(1.0)
            else:
                logger.warning("Failed to fetch %s after %d attempts: %s", url, retries + 1, exc)
                return None


def _match_pools(
    parsed_pools: list[dict[str, Any]],
    existing_pools: list[Any],
) -> dict[int, int]:
    """
    Match parsed CHOOSE_CREDITS pools to existing pool indices.

    Returns a dict mapping existing_pool_index -> credits extracted from the
    parsed pool.  Only confident matches (Jaccard >= MATCH_THRESHOLD) are
    included.  When multiple parsed pools could match the same existing pool,
    the highest-similarity one wins.
    """
    # Build candidate scores: (existing_idx, parsed_idx) -> jaccard
    scores: dict[tuple[int, int], float] = {}
    for p_idx, parsed in enumerate(parsed_pools):
        p_codes = set(parsed.get("course_codes", []))
        for e_idx, existing in enumerate(existing_pools):
            e_codes = _pool_codes(existing)
            j = _jaccard(p_codes, e_codes)
            if j >= MATCH_THRESHOLD:
                scores[(e_idx, p_idx)] = j

    # Greedy assignment: highest Jaccard first; each existing pool and each
    # parsed pool is assigned at most once.
    assigned_existing: set = set()
    assigned_parsed: set = set()
    result: dict[int, int] = {}

    for (e_idx, p_idx), score in sorted(scores.items(), key=lambda x: -x[1]):
        if e_idx in assigned_existing or p_idx in assigned_parsed:
            continue
        parsed_credits = parsed_pools[p_idx].get("credits", 0)
        result[e_idx] = parsed_credits
        assigned_existing.add(e_idx)
        assigned_parsed.add(p_idx)

    return result


def _process_major(
    name: str,
    entry: dict[str, Any],
    timeout: int,
) -> tuple[str, dict[str, Any], int, str]:
    """
    Fetch and process a single major.

    Returns (name, updated_entry, pools_updated, status_message).
    """
    url = entry.get("url", "")
    if not url:
        return name, entry, 0, "no URL"

    existing_pools = entry.get("elective_pools", [])
    if not existing_pools:
        return name, entry, 0, "no elective pools"

    # Check if all pools are already backfilled
    pending = [p for p in existing_pools if not _is_backfilled(p)]
    if not pending:
        return name, entry, 0, "already complete"

    html = _fetch_html(url, timeout)
    if html is None:
        return name, entry, 0, "fetch failed"

    try:
        parsed_tree = parse_major_page(html)
    except Exception as exc:
        logger.warning("Failed to parse %s: %s", url, exc)
        return name, entry, 0, f"parse error: {exc}"

    parsed_pools = [
        child for child in parsed_tree.get("children", [])
        if child.get("type") == "CHOOSE_CREDITS"
    ]

    if not parsed_pools:
        return name, entry, 0, "no CHOOSE_CREDITS found in parsed page"

    match_map = _match_pools(parsed_pools, existing_pools)

    if not match_map:
        return name, entry, 0, "no pools matched above threshold"

    # Build updated pool list
    updated_pools = list(existing_pools)
    updated_count = 0

    for e_idx, credits in match_map.items():
        if credits <= 0:
            logger.debug(
                "%s pool[%d]: skipping (parsed credits=0 (header not found on page))",
                name, e_idx,
            )
            continue

        existing = existing_pools[e_idx]
        if _is_backfilled(existing):
            continue  # already done in a previous run

        # Convert from list format to dict format
        raw_codes = list(existing)
        updated_pools[e_idx] = {"credits": credits, "courses": raw_codes}
        updated_count += 1

        logger.debug(
            "%s pool[%d]: backfilled credits=%d (%d courses)",
            name, e_idx, credits, len(raw_codes),
        )

    if updated_count == 0:
        return name, entry, 0, "no pools updated (all credits=0 or already done)"

    updated_entry = {**entry, "elective_pools": updated_pools}
    return name, updated_entry, updated_count, f"updated {updated_count} pool(s)"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def backfill_elective_credits(
    majors_path: Path,
    dry_run: bool = False,
    concurrency: int = 10,
    timeout: int = 20,
) -> None:
    """
    Backfill elective pool credit values in majors.json.

    Args:
        majors_path:  Path to majors.json.
        dry_run:      If True, log planned changes without writing.
        concurrency:  Number of parallel HTTP workers.
        timeout:      HTTP request timeout in seconds.
    """
    with open(majors_path, encoding="utf-8") as f:
        raw = json.load(f)

    if not isinstance(raw, dict):
        logger.error(
            "majors.json is not in the expected dict format (got %s). "
            "This script only supports the old scraper output format.",
            type(raw).__name__,
        )
        return

    total_majors = len(raw)
    total_pools = sum(len(e.get("elective_pools", [])) for e in raw.values())
    already_done = sum(
        1 for e in raw.values()
        for p in e.get("elective_pools", [])
        if _is_backfilled(p)
    )

    logger.info(
        "majors.json: %d majors, %d elective pools (%d already backfilled, %d pending)",
        total_majors, total_pools, already_done, total_pools - already_done,
    )

    if total_pools - already_done == 0:
        logger.info("Nothing to do; all pools already backfilled.")
        return

    # Submit all majors for parallel processing.
    updated_data = dict(raw)  # shallow copy; entries are replaced as updated
    stats = {"fetched": 0, "updated_majors": 0, "updated_pools": 0, "skipped": 0}

    futures = {}
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        for name, entry in raw.items():
            if not any(not _is_backfilled(p) for p in entry.get("elective_pools", [])):
                continue  # skip fully-done majors immediately
            fut = executor.submit(_process_major, name, entry, timeout)
            futures[fut] = name

        for fut in as_completed(futures):
            name = futures[fut]
            try:
                result_name, updated_entry, pools_updated, status = fut.result()
            except Exception as exc:
                logger.warning("Unexpected error processing %s: %s", name, exc)
                stats["skipped"] += 1
                continue

            stats["fetched"] += 1

            if pools_updated > 0:
                if dry_run:
                    logger.info("[DRY RUN] Would update %s: %s", name, status)
                else:
                    updated_data[result_name] = updated_entry
                    stats["updated_majors"] += 1
                    stats["updated_pools"] += pools_updated
                    logger.info("Updated %s: %s", name, status)
            else:
                logger.debug("Skipped %s: %s", name, status)
                stats["skipped"] += 1

    logger.info(
        "Backfill complete: %d fetched, %d majors updated, "
        "%d pools backfilled, %d skipped/failed",
        stats["fetched"],
        stats["updated_majors"],
        stats["updated_pools"],
        stats["skipped"],
    )

    if dry_run:
        logger.info("Dry run; no changes written.")
        return

    if stats["updated_pools"] == 0:
        logger.info("No changes to write.")
        return

    # Atomic write: temp file in the same directory then rename
    majors_dir = majors_path.parent
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=majors_dir,
        suffix=".tmp",
        delete=False,
    ) as tmp:
        tmp_path = Path(tmp.name)
        json.dump(updated_data, tmp, indent=2, ensure_ascii=False)

    os.replace(tmp_path, majors_path)
    logger.info("majors.json written: %d pools backfilled.", stats["updated_pools"])


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Print planned changes without writing majors.json.",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=10,
        metavar="N",
        help="Number of parallel HTTP fetch workers (default: 10).",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=20,
        metavar="N",
        help="HTTP request timeout in seconds (default: 20).",
    )
    parser.add_argument(
        "--majors-path",
        type=Path,
        default=_DEFAULT_MAJORS_PATH,
        metavar="PATH",
        help=f"Path to majors.json (default: {_DEFAULT_MAJORS_PATH}).",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO).",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    backfill_elective_credits(
        majors_path=args.majors_path,
        dry_run=args.dry_run,
        concurrency=args.concurrency,
        timeout=args.timeout,
    )
