import json
from pathlib import Path
from typing import List

from coursemap.domain.prerequisite import (
    CourseRequirement,
    AndExpression,
    PrerequisiteExpression,
)
from coursemap.domain.course import Course, Offering


DATASET_PATH = Path("datasets/courses.json")


def _parse_offerings(raw):

    offerings = []

    if not raw:
        return offerings

    for o in raw:

        semester = o.get("semester") or o.get("teachingPeriod")
        campus = o.get("campus") or o.get("location") or "PN"
        mode = o.get("mode") or o.get("deliveryMode") or "internal"

        if not semester:
            continue

        offerings.append(
            Offering(
                semester=semester,
                campus=campus,
                mode=mode,
            )
        )

    return offerings


def _parse_prereqs(prereqs):

    if not prereqs:
        return None

    exprs: List[PrerequisiteExpression] = [
        CourseRequirement(code) for code in prereqs
    ]

    if len(exprs) == 1:
        return exprs[0]

    return AndExpression(exprs)


def load_courses():

    if not DATASET_PATH.exists():
        raise FileNotFoundError(
            "courses.json not found. Run ingestion/build_dataset.py first."
        )

    with open(DATASET_PATH, encoding="utf8") as f:
        raw_courses = json.load(f)

    courses = {}

    for item in raw_courses:

        code = item.get("course_code")

        if not code:
            continue

        offerings = _parse_offerings(item.get("offerings"))

        prereq_expr = _parse_prereqs(item.get("prerequisites"))

        try:

            course = Course(
                code=code,
                title=item.get("title", ""),
                credits=int(item.get("credits") or 15),
                level=int(item.get("level") or 100),
                offerings=offerings,
                prerequisites=prereq_expr,
            )

        except Exception:
            continue

        courses[code] = course

    print(f"Loaded {len(courses)} courses from dataset")

    return courses