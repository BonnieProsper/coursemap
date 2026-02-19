from typing import Dict

from coursemap.domain.course import Course, Offering
from coursemap.domain.prerequisite import CourseRequirement


def build_seed_courses() -> Dict[str, Course]:
    def offering_all(level):
        if level == 100:
            semesters = ["S1", "S2"]
        elif level == 200:
            semesters = ["S1"]
        else:
            semesters = ["S2"]

        return [
            Offering(
                year=2026,
                semester=s,
                campus="PN",
                mode="internal",
            )
            for s in semesters
        ]

    courses = {
        "MATH101": Course("MATH101", "Math 1", 15, 100, offering_all(100)),
        "STAT101": Course("STAT101", "Stats 1", 15, 100, offering_all(100)),
        "STAT102": Course(
            "STAT102",
            "Stats 2",
            15,
            100,
            offering_all(100),
            CourseRequirement("STAT101"),
        ),
        "COMP101": Course("COMP101", "Comp 1", 15, 100, offering_all(100)),
        "STAT201": Course(
            "STAT201",
            "Stats 201",
            15,
            200,
            offering_all(200),
            CourseRequirement("STAT102"),
        ),
        "DATA201": Course(
            "DATA201",
            "Data 201",
            15,
            200,
            offering_all(200),
            CourseRequirement("STAT102"),
        ),
        "STAT301": Course(
            "STAT301",
            "Stats 301",
            15,
            300,
            offering_all(300),
            CourseRequirement("STAT201"),
        ),
    }

    return courses
