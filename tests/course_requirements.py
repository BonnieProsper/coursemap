from coursemap.domain.degree_requirements import (
    DegreeRequirements,
    LevelCreditRequirement,
)
from coursemap.domain.electives import ElectivePool


def build_realistic_requirements():
    return DegreeRequirements(
        total_credits=120,
        level_requirements={
            100: LevelCreditRequirement(100, 60),
            200: LevelCreditRequirement(200, 30),
            300: LevelCreditRequirement(300, 30),
        },
        core_courses={
            "MATH101",
            "STAT101",
            "STAT102",
            "COMP101",
            "DATA201",
        },
        elective_pools=[
            ElectivePool(
                name="Stats Electives",
                course_codes={"STAT201", "STAT202", "STAT203"},
                min_credits=30,
            ),
            ElectivePool(
                name="Advanced Electives",
                course_codes={"STAT201", "MATH201", "DATA301", "AI301"},
                min_select=2,
                max_select=2,
                min_credits=15,
            )
        ],
    )


def build_massey_bsc_requirements() -> DegreeRequirements:
    return DegreeRequirements(
        total_credits=360,
        max_100_level=165,
        min_300_level=75,
        level_requirements={},
        core_courses=set(),  # schedule A handled separately
        elective_pools=[],
        required_majors=1,
    )