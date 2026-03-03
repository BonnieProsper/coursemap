import json
from pathlib import Path
from typing import Dict

from coursemap.domain.course import Course, Offering


def load_courses_from_json(path: str) -> Dict[str, Course]:
    raw = json.loads(Path(path).read_text())

    courses = {}

    for item in raw:
        offerings = [
            Offering(
                semester=o["semester"],
                campus=o["campus"],
                mode=o["mode"],
            )
            for o in item["offerings"]
        ]

        courses[item["code"]] = Course(
            code=item["code"],
            title=item["title"],
            credits=item["credits"],
            level=item["level"],
            offerings=offerings,
        )

    return courses