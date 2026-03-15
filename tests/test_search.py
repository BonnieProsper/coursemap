from coursemap.domain.seed_data import build_seed_courses
from coursemap.domain.degree_requirements import (
    DegreeRequirements,
    LevelCreditRequirement,
)
from coursemap.domain.electives import ElectivePool
from coursemap.planner.generator import PlanGenerator
from coursemap.optimisation.search import ExhaustivePlanSearch
from .course_requirements import build_realistic_requirements

def test_exhaustive_search_returns_valid_plan():
    courses = build_seed_courses()

    requirements = DegreeRequirements(
        total_credits=105,
        max_100_level=None,
        min_300_level=None,
        level_requirements={
            100: LevelCreditRequirement(100, 60),
            200: LevelCreditRequirement(200, 30),
            300: LevelCreditRequirement(300, 15),
        },
        core_courses=set(courses.keys()),
        min_schedule_credits=None,
        required_majors=0,
        available_majors=[],
        elective_pools=[],
    )

    generator = PlanGenerator(courses)

    search = ExhaustivePlanSearch(
        courses,
        requirements,
        generator,
    )

    plan = search.search()

    assert plan is not None
    assert len(plan.semesters) > 0


def test_realistic_search():
    courses = build_seed_courses()
    requirements = build_realistic_requirements()

    generator = PlanGenerator(courses)

    search = ExhaustivePlanSearch(
        courses,
        requirements,
        generator,
    )

    plan = search.search()

    assert plan is not None
    assert sum(
        c.credits
        for s in plan.semesters
        for c in s.courses
    ) == 120