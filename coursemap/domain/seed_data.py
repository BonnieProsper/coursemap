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
                semester=s,
                campus="PN",
                mode="internal",
            )
            for s in semesters
        ]

    return {
        # 100-level
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

        # 200-level
        "DATA201": Course(
            "DATA201",
            "Data 201",
            15,
            200,
            offering_all(200),
            CourseRequirement("STAT102"),
        ),
        "STAT201": Course(
            "STAT201",
            "Stats 201",
            15,
            200,
            offering_all(200),
            CourseRequirement("STAT102"),
        ),
        "STAT202": Course(
            "STAT202",
            "Stats 202",
            15,
            200,
            offering_all(200),
            CourseRequirement("STAT102"),
        ),
        "STAT203": Course(
            "STAT203",
            "Stats 203",
            15,
            200,
            offering_all(200),
            CourseRequirement("STAT102"),
        ),

        # 300-level
        "STAT301": Course(
            "STAT301",
            "Stats 301",
            15,
            300,
            offering_all(300),
            CourseRequirement("STAT201"),
        ),
        "DATA301": Course(
            "DATA301",
            "Data 301",
            15,
            300,
            offering_all(300),
            CourseRequirement("DATA201"),
        ),
        "COMP301": Course(
            "COMP301",
            "Comp 301",
            15,
            300,
            offering_all(300),
            CourseRequirement("COMP101"),
        ),
    }