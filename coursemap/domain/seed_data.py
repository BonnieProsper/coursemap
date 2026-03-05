"""
Seed data for deterministic testing and development.
NOT scraped real university data.
"""
from typing import Dict, List

from coursemap.domain.course import Course, Offering
from coursemap.domain.prerequisite import CourseRequirement
from coursemap.domain.degree_requirements import (
    DegreeRequirements,
    LevelCreditRequirement,
)
from coursemap.domain.electives import ElectivePool
from coursemap.domain.major import Major


# --------------------------------------------------
# COURSE CATALOG
# --------------------------------------------------

def _offering(semesters: List[str]) -> List[Offering]:
    return [
        Offering(semester=s, campus="PN", mode="internal")
        for s in semesters
    ]

def build_course_catalog() -> Dict[str, Course]:
    return {

        # 100-level (4 courses = 60 credits)
        "STAT101": Course("STAT101", "Statistics I", 15, 100, _offering(["S1", "S2"])),
        "MATH101": Course("MATH101", "Calculus I", 15, 100, _offering(["S1", "S2"])),
        "COMP101": Course("COMP101", "Programming I", 15, 100, _offering(["S1", "S2"])),
        "PHYS101": Course("PHYS101", "Physics I", 15, 100, _offering(["S1", "S2"])),

        # 200-level (5 courses = 75 credits)
        "STAT201": Course("STAT201", "Statistical Modelling", 15, 200,
                          _offering(["S1"]), CourseRequirement("STAT101")),
        "STAT202": Course("STAT202", "Probability Theory", 15, 200,
                          _offering(["S1"]), CourseRequirement("STAT101")),
        "COMP201": Course("COMP201", "Data Structures", 15, 200,
                          _offering(["S1"]), CourseRequirement("COMP101")),
        "PHYS201": Course("PHYS201", "Mechanics II", 15, 200,
                          _offering(["S1"]), CourseRequirement("PHYS101")),
        "MATH201": Course("MATH201", "Linear Algebra", 15, 200,
                          _offering(["S1"]), CourseRequirement("MATH101")),

        # 300-level (5 courses = 75 credits)
        "STAT301": Course("STAT301", "Advanced Regression", 15, 300,
                          _offering(["S2"]), CourseRequirement("STAT201")),
        "STAT302": Course("STAT302", "Bayesian Statistics", 15, 300,
                          _offering(["S2"]), CourseRequirement("STAT202")),
        "COMP301": Course("COMP301", "Algorithms", 15, 300,
                          _offering(["S2"]), CourseRequirement("COMP201")),
        "PHYS301": Course("PHYS301", "Quantum Intro", 15, 300,
                          _offering(["S2"]), CourseRequirement("PHYS201")),
        "MATH301": Course("MATH301", "Abstract Algebra", 15, 300,
                          _offering(["S2"]), CourseRequirement("MATH201")),
    }


def build_seed_courses() -> Dict[str, Course]:
    """
    Backward-compatible alias used by older tests/modules.
    """
    return build_course_catalog()


# --------------------------------------------------
# DEGREE REQUIREMENTS
# --------------------------------------------------
def build_bsc_requirements() -> DegreeRequirements:

    level_requirements = {
        200: LevelCreditRequirement(level=200, min_credits=60),
        300: LevelCreditRequirement(level=300, min_credits=60),
    }

    statistics_major = Major(
        name="Statistics",
        required_courses={
            "STAT201",
            "STAT202",
            "STAT301",
            "STAT302",
        },
        total_credits=60,
        min_200_level=30,
        min_300_level=30,
    )

    elective_pool = ElectivePool(
        name="General Science Electives",
        course_codes={
            "MATH101", "COMP101", "PHYS101",
            "COMP201", "PHYS201", "MATH201",
            "COMP301", "PHYS301", "MATH301",
        },
        min_credits=105,  # 7 courses × 15 = 105
    )

    return DegreeRequirements(
        total_credits=180,
        max_100_level=90,
        min_300_level=60,
        level_requirements=level_requirements,
        core_courses={"STAT101"},
        min_schedule_credits=None,
        required_majors=1,
        available_majors=[statistics_major],
        elective_pools=[elective_pool],
    )
