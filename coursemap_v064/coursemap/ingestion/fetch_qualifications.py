"""Fetch qualification and specialisation metadata from Massey."""
from __future__ import annotations
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


def discover_qualifications() -> tuple[list[dict], list[dict]]:
    """
    Page through the Massey Swiftype API and return (qualifications, specialisations).

    Qualifications are degree-level entries (sub_type='qual').
    Specialisations are major-level entries (sub_type='spec') that map to a
    parent qualification via qual_code.
    """
    page = 1
    quals = []
    specs = []

    while True:
        logger.debug("Fetching qualification page %d", page)

        payload = {
            "per_page": 100,
            "page": page,
            "filters": {
                "course-qual": {
                    "sub_type": {"values": ["qual", "spec"]}
                }
            },
            "fetch_fields": {
                "course-qual": [
                    "title",
                    "intro",
                    "url",
                    "sub_type",
                    "qual_code",
                    "qual_length",
                    "max_duration",
                    "nzqf_level",
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
            item = {
                "title":        _safe(r.get("title")),
                "url":          BASE + url if url else None,
                "qual_code":    _safe(r.get("qual_code")),
                "type":         _safe(r.get("sub_type")),
                "level":        _safe(r.get("nzqf_level")),
                "length":       _safe(r.get("qual_length")),
                "max_duration": _safe(r.get("max_duration")),
                "intro":        _safe(r.get("intro")),
            }
            if item["type"] == "qual":
                quals.append(item)
            elif item["type"] == "spec":
                specs.append(item)

        page += 1
        time.sleep(0.4)

    logger.info("Discovered %d qualifications, %d specialisations", len(quals), len(specs))
    return quals, specs


def discover_specialisations() -> list[dict]:
    """Return only the specialisations from discover_qualifications()."""
    _, specs = discover_qualifications()
    return specs


if __name__ == "__main__":
    discover_qualifications()
