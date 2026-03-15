from coursemap.domain.seed_data import build_seed_courses
from coursemap.domain.requirement_serialization import requirement_from_dict
from coursemap.planner.generator import PlanGenerator
from coursemap.optimisation.search import ExhaustivePlanSearch


def test_exhaustive_search_returns_valid_plan():
    courses = build_seed_courses()
    total_credits = sum(c.credits for c in courses.values())

    degree_requirement = requirement_from_dict({
        "type": "ALL_OF",
        "children": [
            {"type": "TOTAL_CREDITS", "required_credits": total_credits},
        ],
    })
    majors = [
        {
            "name": "Default",
            "url": "",
            "requirement": {
                "type": "ALL_OF",
                "children": [
                    {"type": "COURSE", "course_code": code}
                    for code in sorted(courses.keys())
                ],
            },
        },
    ]

    generator = PlanGenerator(courses)
    search = ExhaustivePlanSearch(
        courses,
        degree_requirement,
        majors,
        generator,
    )

    plan = search.search()

    assert plan is not None
    assert len(plan.semesters) > 0


def test_realistic_search():
    courses = build_seed_courses()
    total_credits = 120
    degree_requirement = requirement_from_dict({
        "type": "ALL_OF",
        "children": [
            {"type": "TOTAL_CREDITS", "required_credits": total_credits},
            {"type": "COURSE", "course_code": "MATH101"},
            {"type": "COURSE", "course_code": "STAT101"},
            {"type": "COURSE", "course_code": "COMP101"},
            {
                "type": "CHOOSE_CREDITS",
                "credits": 30,
                "course_codes": ["STAT201", "STAT202", "STAT203"],
            },
            {
                "type": "CHOOSE_CREDITS",
                "credits": 15,
                "course_codes": ["STAT201", "MATH201"],
            },
        ],
    })
    majors = [
        {
            "name": "Default",
            "url": "",
            "requirement": {
                "type": "ALL_OF",
                "children": [
                    {"type": "COURSE", "course_code": "MATH101"},
                    {"type": "COURSE", "course_code": "STAT101"},
                    {"type": "COURSE", "course_code": "COMP101"},
                    {"type": "COURSE", "course_code": "STAT201"},
                    {"type": "COURSE", "course_code": "MATH201"},
                ],
            },
        },
    ]

    generator = PlanGenerator(courses)
    search = ExhaustivePlanSearch(
        courses,
        degree_requirement,
        majors,
        generator,
    )

    plan = search.search()

    assert plan is not None
    assert sum(
        c.credits for s in plan.semesters for c in s.courses
    ) == total_credits