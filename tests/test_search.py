from coursemap.domain.seed_data import build_seed_courses
from coursemap.domain.degree_requirements import (
    DegreeRequirements,
    LevelCreditRequirement,
)
from coursemap.domain.electives import ElectivePool
from coursemap.planner.generator import PlanGenerator
from coursemap.optimisation.search import ExhaustivePlanSearch


def test_exhaustive_search_returns_valid_plan():
    courses = build_seed_courses()

    requirements = DegreeRequirements(
        total_credits=105,
        level_requirements={
            100: LevelCreditRequirement(100, 60),
            200: LevelCreditRequirement(200, 30),
            300: LevelCreditRequirement(300, 15),
        },
        core_courses=set(courses.keys()),
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