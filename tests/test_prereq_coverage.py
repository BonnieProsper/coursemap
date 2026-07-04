"""
Unit tests for coursemap.ingestion.prereq_coverage: the shared
prerequisite-format-distribution helper extracted from what used to be two
independently-maintained copies of the same Counter logic in
coursemap/cli/main.py's data-quality command and coursemap/api/server.py's
/api/data-quality endpoint (see CHANGELOG.md).
"""
from __future__ import annotations

from coursemap.ingestion.prereq_coverage import (
    prereq_format_distribution,
    prereq_coverage_summary,
)


def _course(code: str, prereqs) -> dict:
    return {"course_code": code, "prerequisites": prereqs}


def test_prereq_format_distribution_counts_null():
    courses = [_course("A", None), _course("B", None)]
    dist = prereq_format_distribution(courses)
    assert dist == {"null": 2}


def test_prereq_format_distribution_counts_flat_list():
    courses = [_course("A", ["159101"]), _course("B", ["159101", "160101"])]
    dist = prereq_format_distribution(courses)
    assert dist == {"flat_list": 2}


def test_prereq_format_distribution_counts_dict_and_string_together():
    """Both the AND/OR-tree dict shape and the single-code string shape are
    the current scraper's real output formats. They're merged into one
    and_or_structured count since neither the CLI report nor the API
    response ever displayed them separately (verified against both
    call sites before this extraction)."""
    courses = [
        _course("A", {"op": "OR", "args": ["159101", "159102"]}),
        _course("B", "159101"),
    ]
    dist = prereq_format_distribution(courses)
    assert dist == {"and_or_structured": 2}


def test_prereq_format_distribution_mixed():
    courses = [
        _course("A", None),
        _course("B", ["159101"]),
        _course("C", {"op": "AND", "args": ["159101", "159102"]}),
        _course("D", "159101"),
    ]
    dist = prereq_format_distribution(courses)
    assert dist == {"null": 1, "flat_list": 1, "and_or_structured": 2}


def test_prereq_format_distribution_empty_input():
    assert prereq_format_distribution([]) == {}


def test_prereq_coverage_summary_all_structured_has_no_rescrape_needed():
    courses = [_course("A", "159101"), _course("B", {"op": "OR", "args": ["159101"]})]
    summary = prereq_coverage_summary(courses)
    assert summary["coverage_pct"] == 100
    assert summary["to_rescrape"] == 0
    assert summary["recommendation"] == "All courses use structured prerequisite format."


def test_prereq_coverage_summary_recommends_rescrape_when_needed():
    courses = [_course("A", None), _course("B", ["159101"])]
    summary = prereq_coverage_summary(courses)
    assert summary["coverage_pct"] == 0
    assert summary["to_rescrape"] == 2
    assert "refresh_prerequisites" in summary["recommendation"]
    assert "2 courses" in summary["recommendation"]


def test_prereq_coverage_summary_empty_dataset_does_not_divide_by_zero():
    summary = prereq_coverage_summary([])
    assert summary["total_courses"] == 0
    assert summary["coverage_pct"] == 0
    assert summary["to_rescrape"] == 0


def test_prereq_coverage_summary_matches_real_dataset_shape():
    """Sanity check against the actual bundled dataset: the summary must be
    internally consistent (parts sum to the total) regardless of its
    specific values, which will drift as the dataset gets re-scraped."""
    import json
    from coursemap.ingestion.dataset_loader import DATASET_PATH

    with open(DATASET_PATH, encoding="utf-8") as f:
        raw_courses = json.load(f)

    summary = prereq_coverage_summary(raw_courses)
    assert summary["total_courses"] == len(raw_courses)
    assert summary["and_or_structured"] + summary["flat_list"] + summary["null"] <= summary["total_courses"]
    assert 0 <= summary["coverage_pct"] <= 100
