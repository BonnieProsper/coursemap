from coursemap.domain.seed_data import build_seed_courses
from coursemap.planner.generator import PlanGenerator


def test_plan_generation():
    courses = build_seed_courses()

    generator = PlanGenerator(
        courses,
        max_credits_per_semester=60,
        start_year=2026,
    )

    plan = generator.generate()

    total_courses = sum(len(s.courses) for s in plan.semesters)

    assert total_courses == len(courses)

    # STAT101 must come before STAT102
    semester_lookup = {}
    for i, sem in enumerate(plan.semesters):
        for c in sem.courses:
            semester_lookup[c.code] = i

    assert semester_lookup["STAT101"] < semester_lookup["STAT102"]
    assert semester_lookup["STAT201"] < semester_lookup["STAT301"]
