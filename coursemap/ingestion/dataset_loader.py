import json
from pathlib import Path

from coursemap.domain.course import Course, Offering


DATA_FILE = Path("datasets/courses.json")


def load_courses():

    data = json.loads(DATA_FILE.read_text())

    courses = {}

    for c in data:

        offerings = [
            Offering(
                semester=s,
                campus="default",
                mode="internal"
            )
            for s in c.get("offerings", [])
        ]

        course = Course(
            code=c["code"],
            title=c.get("title"),
            credits=c.get("credits"),
            level=c.get("level"),
            offerings=offerings
        )

        courses[c["code"]] = course

    return courses