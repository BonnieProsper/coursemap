import json
from pathlib import Path
from typing import Any, Dict, List

from coursemap.domain.prerequisite import (
    CourseRequirement,
    AndExpression,
    PrerequisiteExpression,
)
from coursemap.domain.course import Course, Offering
from coursemap.domain.requirement_serialization import requirement_from_dict


DATASET_PATH = Path("datasets/courses.json")
MAJORS_DATASET_PATH = Path("datasets/majors.json")
REQUIREMENTS_DATASET_PATH = Path("datasets/requirements.json")
DEGREE_REQUIREMENTS_DATASET_PATH = Path("datasets/degree_requirements.json")


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


def load_majors() -> List[Dict[str, Any]]:
    """
    Load majors.json (requirement node tree format).
    Returns list of {"name": str, "url": str, "requirement": dict}.
    Use requirement_from_dict(item["requirement"]) to get a RequirementNode.
    """
    if not MAJORS_DATASET_PATH.exists():
        raise FileNotFoundError(
            "datasets/majors.json not found. Run ingestion/build_majors_dataset.py first."
        )
    with open(MAJORS_DATASET_PATH, encoding="utf-8") as f:
        return json.load(f)


def load_requirement_tree(data: Dict[str, Any]):
    """Parse a requirement tree dict (e.g. from JSON) into a RequirementNode."""
    return requirement_from_dict(data)


def load_requirement_tree_from_file(path: Path = REQUIREMENTS_DATASET_PATH):
    """Load a requirement tree from a JSON file (e.g. requirements.json)."""
    if not path.exists():
        raise FileNotFoundError(f"Requirement tree file not found: {path}")
    with open(path, encoding="utf-8") as f:
        return requirement_from_dict(json.load(f))


def load_degree_requirement_tree():
    """
    Load the degree requirement tree from datasets/degree_requirements.json.
    Returns a RequirementNode (root of the tree). Used as source of truth for validation.
    """
    if not DEGREE_REQUIREMENTS_DATASET_PATH.exists():
        raise FileNotFoundError(
            "datasets/degree_requirements.json not found. "
            "Create it with a requirement node tree (e.g. ALL_OF with TOTAL_CREDITS)."
        )
    with open(DEGREE_REQUIREMENTS_DATASET_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return requirement_from_dict(data)