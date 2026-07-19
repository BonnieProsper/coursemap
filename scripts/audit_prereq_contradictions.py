"""
Finds courses whose own stored prerequisite is self-contradictory: an AND
clause requiring two codes that mutually restrict each other. A student
can never satisfy a prerequisite like this regardless of scheduling, since
it requires enrolling in two courses that are mutually exclusive by
definition - it's always a scraper error (almost always a "one of A, B, C"
list that got parsed as a flat AND), never a real Massey requirement.

This is the same check that found and confirmed 160212 (Discrete
Mathematics) and 123201 (Chemical Energetics) as broken, generalized to
run across the whole dataset instead of one course at a time. Run it
after every re-scrape - it's a fast, whole-dataset way to catch this bug
class instead of waiting for a specific major to break and someone to
trace it back.

A hit here is a strong signal, not automatic proof: confirm each one
against the course's live Massey page before adding it to
_VERIFIED_PREREQ_FIXES in repair_dataset.py. This script only detects the
symptom (two restricted codes in the same AND); it doesn't know what the
correct requirement actually is.

Run from the repo root:
    python scripts/audit_prereq_contradictions.py
    python scripts/audit_prereq_contradictions.py --json   # machine-readable

Expected output: one line per hit (course code, title, the conflicting
pair), or "No self-contradictory prerequisites found." if the dataset is
clean.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from coursemap.domain.prerequisite import AndExpression, CoursePrerequisite
from coursemap.ingestion.dataset_loader import load_courses


def _and_clause_codes(node) -> list[str] | None:
    """
    Flattens a top-level AND expression (including nested ANDs) into its
    directly-required course codes. Returns None for anything else (a bare
    course, an OR, or no prerequisite) - those can't be self-contradictory
    in this sense, since OR only ever requires ONE branch.
    """
    if not isinstance(node, AndExpression):
        return None
    codes: list[str] = []
    for child in node.children:
        if isinstance(child, CoursePrerequisite):
            codes.append(child.code)
        elif isinstance(child, AndExpression):
            nested = _and_clause_codes(child)
            if nested:
                codes.extend(nested)
    return codes


def find_contradictions(courses: dict) -> list[tuple[str, str, str]]:
    """Returns (course_code, code_a, code_b) for every course whose AND
    clause requires two mutually-restricting codes."""
    hits: list[tuple[str, str, str]] = []
    for code, course in courses.items():
        and_codes = _and_clause_codes(course.prerequisites)
        if not and_codes or len(and_codes) < 2:
            continue
        for i, a in enumerate(and_codes):
            for b in and_codes[i + 1:]:
                course_a = courses.get(a)
                course_b = courses.get(b)
                a_restricts_b = course_a and b in course_a.restrictions
                b_restricts_a = course_b and a in course_b.restrictions
                if a_restricts_b or b_restricts_a:
                    hits.append((code, a, b))
    return hits


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args()

    courses = load_courses()
    hits = find_contradictions(courses)

    if args.json:
        print(json.dumps(
            [{"course": c, "conflicting_pair": [a, b],
              "title": courses[c].title if c in courses else None}
             for c, a, b in hits],
            indent=2,
        ))
        return 1 if hits else 0

    if not hits:
        print("No self-contradictory prerequisites found.")
        return 0

    print(f"{len(hits)} self-contradictory prerequisite(s) found:\n")
    for code, a, b in hits:
        title = courses[code].title if code in courses else "?"
        print(f"  {code} ({title}): AND clause requires both {a} and {b}, "
              f"which mutually restrict each other")
    print(f"\n{len(hits)} course(s) need live verification before adding "
          f"to _VERIFIED_PREREQ_FIXES (see repair_dataset.py).")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
