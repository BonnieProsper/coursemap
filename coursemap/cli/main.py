import pprint

from coursemap.domain.seed_data import (
    build_course_catalog,
    build_bsc_requirements,
)
from coursemap.services.planner_service import PlannerService


def main():
    courses = build_course_catalog()
    requirements = build_bsc_requirements()

    service = PlannerService(courses, requirements)
    plan = service.generate_best_plan()

    for semester in plan.semesters:
        print(f"{semester.year} {semester.semester}")
        for course in semester.courses:
            print(f"   {course.code}")
        print()


if __name__ == "__main__":
    main()