import json
from coursemap.domain.course import Course, Offering


def load_courses(path):

    with open(path) as f:
        data = json.load(f)

    courses = {}

    for c in data:

        offerings = [
            Offering(semester=s, campus="default", mode="internal")
            for s in c["offerings"]
        ]

        course = Course(
            code=c["code"],
            title=c["title"],
            credits=c["credits"],
            level=c["level"],
            offerings=offerings
        )

        courses[c["code"]] = course

    return courses