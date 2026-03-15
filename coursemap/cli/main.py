import argparse
import json

from coursemap.domain.seed_data import (
    build_course_catalog,
    build_bsc_requirements,
) # TODO: remove when nolonger needed
from coursemap.optimisation.scorer import PlanScorer
from coursemap.services.planner_service import PlannerService
from coursemap.validation.engine import DegreeValidator
from coursemap.validation.tree_builder import build_requirement_tree
from coursemap.ingestion.dataset_loader import load_courses



def main():
    parser = argparse.ArgumentParser(description="CourseMap Degree Planner")
    parser.add_argument("--max-credits", type=int, default=60)
    parser.add_argument("--start-year", type=int, default=2026)
    parser.add_argument("--major", type=str, default=None)

    args = parser.parse_args()

    courses = load_courses()
    requirements = build_bsc_requirements()

    service = PlannerService(courses, requirements)
    plan = service.generate_best_plan(
        max_credits_per_semester=args.max_credits,
        start_year=args.start_year,
        major_name=args.major,
    )
    active_requirements = service.requirements

    plan_data = []

    for semester in plan.semesters:
        plan_data.append(
            {
                "year": semester.year,
                "semester": semester.semester,
                "courses": [c.code for c in semester.courses],
            }
        )

    with open("generated_plan.json", "w") as f:
        json.dump(plan_data, f, indent=2)

    print("Plan exported to generated_plan.json")
    print("\n===== GENERATED DEGREE PLAN =====\n")

    total_credits = 0
    for semester in plan.semesters:
        semester_total = semester.total_credits()
        total_credits += semester_total

        print(f"{semester.year} {semester.semester} ({semester_total} credits)")
        for course in semester.courses:
            print(f"   {course.code} - {course.title}")
        print()

    print("===== SUMMARY =====")
    print(f"Total Credits: {total_credits}")
    print(f"Total Semesters: {len(plan.semesters)}")

    scorer = PlanScorer()
    print(f"Plan Score: {scorer.score(plan):.2f}")

    degree_requirement = build_requirement_tree(active_requirements)
    validator = DegreeValidator(degree_requirement)
    result = validator.validate(plan)
    if not result.passed:
        raise ValueError("Generated plan failed validation: " + "; ".join(result.errors))

    print("\nDegree requirements satisfied.\n")


if __name__ == "__main__":
    main()



# replace seed data:

from coursemap.ingestion.major_loader import load_majors
from coursemap.domain.degree_requirements import DegreeRequirements

majors = load_majors()

requirements = DegreeRequirements(
    total_credits=360,
    core_courses=[],
    elective_pools=[],
    majors=majors,
    level_credit_requirements=[]
)