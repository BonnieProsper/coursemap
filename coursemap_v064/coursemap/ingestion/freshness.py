"""
Dataset freshness checking.

Reports when the bundled datasets were scraped and whether they may be stale.
Massey's course catalogue changes each semester (new courses, retired courses,
prerequisite updates). This module reads the scrape timestamp embedded in the
dataset files and warns if data is older than a configurable threshold.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_DATASETS_DIR = Path(__file__).resolve().parents[2] / "datasets"

# After this many days without a refresh, emit a warning.
STALE_THRESHOLD_DAYS = 180   # ~1 semester


def dataset_scrape_date() -> date | None:
    """
    Return the date the courses.json dataset was last scraped, or None if
    the timestamp is absent (older dataset format).

    The scrape date is stored in the top-level ``_meta`` key that
    ``fetch_courses.py`` writes when it builds the dataset:

        [{"_meta": {"scraped_at": "2026-04-21T10:04:00"}, ...}, ...]

    For backwards compatibility, the function accepts both a ``_meta`` object
    at position 0 in the array and a ``scraped_at`` key in any top-level dict.
    """
    path = _DATASETS_DIR / "courses.json"
    if not path.exists():
        return None

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

    # Try _meta record at index 0
    if isinstance(raw, list) and raw:
        first = raw[0]
        if isinstance(first, dict):
            meta = first.get("_meta") or {}
            scraped_at = meta.get("scraped_at") or first.get("scraped_at")
            if scraped_at:
                try:
                    return datetime.fromisoformat(scraped_at).date()
                except ValueError:
                    pass

    # Try top-level dict (alternative format)
    if isinstance(raw, dict):
        scraped_at = raw.get("scraped_at")
        if scraped_at:
            try:
                return datetime.fromisoformat(scraped_at).date()
            except ValueError:
                pass

    # Fall back to the file's mtime as a proxy for when it was last written
    try:
        mtime = path.stat().st_mtime
        return datetime.fromtimestamp(mtime).date()
    except OSError:
        return None


def freshness_report(threshold_days: int = STALE_THRESHOLD_DAYS) -> dict:
    """
    Return a freshness report dict with the following keys:

        scrape_date:   date | None   — when datasets were last scraped
        age_days:      int | None    — days since scrape (None if unknown)
        is_stale:      bool          — True if age > threshold_days
        threshold_days: int
        message:       str           — human-readable summary

    The report is also logged at WARNING level when the data is stale.
    """
    scrape_date = dataset_scrape_date()
    today = date.today()

    if scrape_date is None:
        return {
            "scrape_date":     None,
            "age_days":        None,
            "is_stale":        False,
            "threshold_days":  threshold_days,
            "message":         "Dataset scrape date unknown — no timestamp in courses.json.",
        }

    age_days = (today - scrape_date).days
    is_stale = age_days > threshold_days

    if is_stale:
        msg = (
            f"Dataset is {age_days} days old (scraped {scrape_date}). "
            f"Course offerings and prerequisites may have changed. "
            f"Run 'python -m coursemap.ingestion.refresh_prerequisites' to update."
        )
        logger.warning(msg)
    else:
        msg = f"Dataset scraped {scrape_date} ({age_days} days ago) — within the {threshold_days}-day freshness window."

    return {
        "scrape_date":    str(scrape_date),
        "age_days":       age_days,
        "is_stale":       is_stale,
        "threshold_days": threshold_days,
        "message":        msg,
    }
