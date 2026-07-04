"""
Prerequisite format coverage: how much of the dataset has structured
AND/OR prerequisite data versus the old flat-list format or nothing at all.

Extracted because this exact computation (a Counter over the four possible
shapes of the raw `prerequisites` field) was independently written twice:
once in coursemap/cli/main.py's data-quality command, once in
coursemap/api/server.py's /api/data-quality endpoint. Two copies of a
four-branch Counter loop are unlikely to silently diverge in a way that
produces wrong output, but they're still two places that need updating in
step if the raw format ever changes, and one already had (see
CHANGELOG.md, the CLI's --json flag was a dead argument for exactly this
reason before being fixed and consolidated here).
"""
from __future__ import annotations

from collections import Counter


def prereq_format_distribution(raw_courses: list[dict]) -> dict[str, int]:
    """
    Count each course's raw `prerequisites` field by shape.

    Returns a dict with keys:
        and_or_structured  : dict or single-string form (current scraper)
        flat_list          : list of code strings (old scraper, noisy)
        null                : never scraped
    """
    counts = Counter()
    for c in raw_courses:
        pval = c.get("prerequisites")
        if pval is None:
            counts["null"] += 1
        elif isinstance(pval, list):
            counts["flat_list"] += 1
        elif isinstance(pval, (dict, str)):
            counts["and_or_structured"] += 1
        else:
            counts[f"unknown_{type(pval).__name__}"] += 1
    return dict(counts)


def prereq_coverage_summary(raw_courses: list[dict]) -> dict:
    """
    Build the full coverage summary both the CLI and the API report from:
    format distribution, coverage percentage, and how many courses still
    need re-scraping.
    """
    total = len(raw_courses)
    dist = prereq_format_distribution(raw_courses)
    structured = dist.get("and_or_structured", 0)
    flat_list  = dist.get("flat_list", 0)
    null_count = dist.get("null", 0)
    to_rescrape = flat_list + null_count

    return {
        "total_courses": total,
        "and_or_structured": structured,
        "flat_list": flat_list,
        "null": null_count,
        "coverage_pct": round(100 * structured / total) if total else 0,
        "to_rescrape": to_rescrape,
        "recommendation": (
            f"Run `python -m coursemap.ingestion.refresh_prerequisites` to "
            f"upgrade {to_rescrape} courses to structured AND/OR prerequisites."
            if to_rescrape > 0
            else "All courses use structured prerequisite format."
        ),
    }
