"""Fetch and normalise course data from the Massey catalogue API."""
from __future__ import annotations
import json
import logging
import time

from coursemap.ingestion.swiftype_client import search

BASE = "https://www.massey.ac.nz"
logger = logging.getLogger(__name__)


def _safe(v: object) -> object:
    """Return the first element of a list, or the value itself."""
    if isinstance(v, list):
        return v[0] if v else None
    return v


def _parse_offerings_json(v: object) -> list:
    """Parse an offerings value that may arrive as a JSON string or a list."""
    if not v:
        return []
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception as exc:
            logger.debug("Could not parse offerings JSON %r: %s", v[:80], exc)
            return []
    return v


def discover_courses() -> list[dict]:
    """
    Page through the Massey Swiftype API and return a flat list of course dicts.

    Each dict contains the raw fields needed by build_dataset.py: course_code,
    title, url, credits, level, offerings, prerequisites, corequisites,
    restrictions.
    """
    page = 1
    courses = []

    while True:
        logger.debug("Fetching course page %d", page)

        payload = {
            "per_page": 100,
            "page": page,
            "filters": {
                "course-qual": {
                    "sub_type": {"values": ["course"]}
                }
            },
            "fetch_fields": {
                "course-qual": [
                    "title",
                    "intro",
                    "url",
                    "course_code",
                    "course_credit_float",
                    "subject_areas",
                    "course_level",
                    "nzqf_level",
                    "locations",
                    "delivery_mode",
                    "year",
                    "semester",
                    "offerings_json",
                ]
            },
            "q": "",
        }

        data = search(payload)
        results = data["records"]["course-qual"]

        if not results:
            break

        for r in results:
            url = _safe(r.get("url"))
            courses.append({
                "course_code":  _safe(r.get("course_code")),
                "title":        _safe(r.get("title")),
                "url":          BASE + url if url else None,
                "credits":      r.get("course_credit_float"),
                "level":        _safe(r.get("nzqf_level")),
                "course_level": _safe(r.get("course_level")),
                "subjects":     r.get("subject_areas"),
                "intro":        _safe(r.get("intro")),
                "offerings":    _parse_offerings_json(r.get("offerings_json")),
                "prerequisites":  [],
                "corequisites":   [],
                "restrictions":   [],
            })

        page += 1
        time.sleep(0.4)

    return courses
