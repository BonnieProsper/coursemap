"""
Finds majors where an ALL_OF node has two or more sibling CHOOSE_CREDITS
pools whose course lists substantially overlap - the shape of a genuine
"Either this path OR that path" choice (e.g. a 120cr thesis vs a 60cr
research report) that got encoded as both being required simultaneously
instead of as a real choice between them.

This is the exact bug found and fixed for Animal Science - Master of
Science: its real "Part Two" requirement is "Either [90-120cr from the
thesis pool] Or [60cr research report]", but was stored as two separate
CHOOSE_CREDITS nodes ALL_OF'd together, forcing every student down the
thesis path and making the 60cr research-report alternative unreachable.
The schema already has a node type for this (ANY_OF, see
requirement_serialization.py) - the majors below just aren't using it
where they probably should be.

A hit here is a strong signal, not automatic proof: two pools can
legitimately share most of their course list without being a mis-encoded
Either/Or (e.g. a shared elective pool two different named requirements
both draw from). Confirm each one against the major's live "Courses you
can enrol in" page before changing majors.json - look for prose like
"Either... Or...", "choose ONE of the following options", or two
credit-target headings under a single overall total, as opposed to two
independently-required parts of the same total.

Run from the repo root:
    python scripts/audit_pool_overlap.py
    python scripts/audit_pool_overlap.py --json         # machine-readable
    python scripts/audit_pool_overlap.py --threshold 0.5  # loosen the overlap bar

Expected output: one line per hit (major name, the two pools' credit
targets and overlap), or "No overlapping sibling pools found." if none
match the current threshold.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_MAJORS_PATH = Path(__file__).resolve().parent.parent / "datasets" / "majors.json"

_DEFAULT_THRESHOLD = 0.7  # fraction of the smaller pool's codes that must overlap


def _find_overlapping_siblings(node, threshold: float) -> list[tuple[int, int, int, int]]:
    """
    Returns (credits_a, credits_b, overlap_count, smaller_pool_size) for
    every pair of sibling CHOOSE_CREDITS children of an ALL_OF node whose
    course lists overlap by at least `threshold` of the smaller pool.
    Recurses into all children regardless of node type.
    """
    hits: list[tuple[int, int, int, int]] = []
    if isinstance(node, dict) and node.get("type") == "ALL_OF":
        cc_children = [
            c for c in node.get("children", [])
            if isinstance(c, dict) and c.get("type") == "CHOOSE_CREDITS"
        ]
        for i in range(len(cc_children)):
            for j in range(i + 1, len(cc_children)):
                codes_a = set(cc_children[i].get("course_codes", []))
                codes_b = set(cc_children[j].get("course_codes", []))
                if not codes_a or not codes_b:
                    continue
                overlap = codes_a & codes_b
                smaller = min(len(codes_a), len(codes_b))
                if smaller > 0 and len(overlap) / smaller >= threshold:
                    hits.append((
                        cc_children[i].get("credits"),
                        cc_children[j].get("credits"),
                        len(overlap),
                        smaller,
                    ))
    if isinstance(node, dict):
        for child in node.get("children", []):
            hits.extend(_find_overlapping_siblings(child, threshold))
    return hits


def find_overlapping_pools(majors: list[dict], threshold: float = _DEFAULT_THRESHOLD) -> list[tuple[str, list]]:
    """Returns (major_name, hits) for every major with at least one hit."""
    results = []
    for m in majors:
        hits = _find_overlapping_siblings(m.get("requirement"), threshold)
        if hits:
            results.append((m["name"], hits))
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--threshold", type=float, default=_DEFAULT_THRESHOLD,
                         help=f"minimum overlap fraction to report (default {_DEFAULT_THRESHOLD})")
    args = parser.parse_args()

    with open(_MAJORS_PATH, encoding="utf-8") as f:
        majors = json.load(f)

    results = find_overlapping_pools(majors, args.threshold)

    if args.json:
        print(json.dumps(
            [{"major": name, "overlaps": [
                {"credits_a": a, "credits_b": b, "overlap": o, "smaller_pool_size": s}
                for a, b, o, s in hits
            ]} for name, hits in results],
            indent=2,
        ))
        return 1 if results else 0

    if not results:
        print("No overlapping sibling pools found.")
        return 0

    print(f"{len(results)} major(s) with likely mis-encoded Either/Or paths:\n")
    for name, hits in results:
        for a, b, overlap, smaller in hits:
            print(f"  {name}: {a}cr pool and {b}cr pool share {overlap}/{smaller} codes")
    print(f"\n{len(results)} major(s) need live verification against their "
          f"'Courses you can enrol in' page before changing majors.json.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
