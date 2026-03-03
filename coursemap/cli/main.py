import argparse
import json

from coursemap.domain.seed_data import (
    build_course_catalog,
    build_bsc_requirements,
)
from coursemap.services.planner_service import PlannerService
from coursemap.optimisation.scorer import PlanScorer
from coursemap.validation.engine import DegreeValidator
from coursemap.validation.rules import (
    TotalCreditRule,
    LevelCreditRule,
    CoreCourseRule,
    ElectivePoolRule,
    MajorCompletionRule,
)


def main():
    parser = argparse.ArgumentParser(description="CourseMap Degree Planner")
    parser.add_argument("--max-credits", type=int, default=60)
    parser.add_argument("--start-year", type=int, default=2026)
    args = parser.parse_args()

    courses = build_course_catalog() 
    # TODO: courses = load_courses_from_json("data/dataset.json")
    requirements = build_bsc_requirements()

    service = PlannerService(courses, requirements)
    plan = service.generate_best_plan(
        max_credits_per_semester=args.max_credits,
        start_year=args.start_year,
    )

    plan_data = []

    for semester in plan.semesters:
        plan_data.append({
            "year": semester.year,
            "semester": semester.semester,
            "courses": [c.code for c in semester.courses],
        })

    with open("generated_plan.json", "w") as f:
        json.dump(plan_data, f, indent=2)

    print("Plan exported to generated_plan.json")

    print("\n===== GENERATED DEGREE PLAN =====\n")

    total_credits = 0

    for semester in plan.semesters:
        semester_total = semester.total_credits()
        total_credits += semester_total

        print(f"{semester.year} {semester.semester} "
              f"({semester_total} credits)")
        for course in semester.courses:
            print(f"   {course.code} - {course.title}")
        print()

    print("===== SUMMARY =====")
    print(f"Total Credits: {total_credits}")
    print(f"Total Semesters: {len(plan.semesters)}")

    scorer = PlanScorer()
    print(f"Plan Score: {scorer.score(plan):.2f}")

    # Final validation confirmation
    rules = [
        TotalCreditRule(requirements),
        LevelCreditRule(requirements),
        CoreCourseRule(requirements.core_courses),
        MajorCompletionRule(requirements),
    ]

    for pool in requirements.elective_pools:
        rules.append(ElectivePoolRule(pool))

    validator = DegreeValidator(rules)
    validator.validate(plan)

    print("\n✔ Degree requirements satisfied.\n")


if __name__ == "__main__":
    main()