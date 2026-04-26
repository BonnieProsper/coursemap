"""
Build majors.json from each major's Massey programme page.

Uses the URLs already stored in datasets/specialisations.json so no
Swiftype API key is required. Each programme page is fetched directly
and parsed by major_parser.parse_major_page.

Run from the repo root:

    python -m coursemap.ingestion.build_majors_dataset

Writes datasets/majors.json as a list of:
    {"name": str, "url": str, "requirement": <node dict>}
"""
from __future__ import annotations
import json
import logging
from pathlib import Path

import requests

from coursemap.ingestion.major_parser import parse_major_page

logger = logging.getLogger(__name__)

_DATASETS_DIR = Path(__file__).resolve().parents[2] / "datasets"


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


def build_majors_dataset() -> None:
    """
    Fetch each major's programme page and write datasets/majors.json.
    """
    specs = _load_specialisations()
    logger.info("Building majors dataset from %d specialisations", len(specs))

    majors = []
    for i, spec in enumerate(specs, 1):
        title = spec["title"]
        url   = spec.get("url", "")

        if not url:
            logger.warning("Skipping '%s': no URL in specialisations.json", title)
            continue

        logger.info("[%d/%d] %s", i, len(specs), title)

        try:
            html = requests.get(url, timeout=30).text
            requirement_tree = parse_major_page(html)
            majors.append({
                "name":        title,
                "url":         url,
                "requirement": requirement_tree,
            })
        except Exception as exc:
            logger.warning("Failed to scrape '%s': %s", title, exc)

    out_path = _DATASETS_DIR / "majors.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(majors, f, indent=2, ensure_ascii=False)

    logger.info("Wrote %s (%d majors)", out_path, len(majors))


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s: %(message)s",
    )
    build_majors_dataset()
