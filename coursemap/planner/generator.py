from typing import Dict, List, Set

from coursemap.domain.course import Course
from coursemap.domain.plan import DegreePlan, SemesterPlan
from coursemap.planner.graph import PrerequisiteGraph


class PlanGenerator:
    def __init__(
        self,
        courses: Dict[str, Course],
        max_credits_per_semester: int = 60,
        campus: str = "PN",
        mode: str = "internal",
        start_year: int = 2026,
    ):
        self.courses = courses
        self.max_credits = max_credits_per_semester
        self.campus = campus
        self.mode = mode
        self.start_year = start_year

        self.graph = PrerequisiteGraph(courses)

    def generate(self) -> DegreePlan:
        remaining: Set[str] = set(self.courses.keys())
        completed: Set[str] = set()

        semesters: List[SemesterPlan] = []

        year = self.start_year
        semester_cycle = ["S1", "S2"]
        semester_index = 0

        while remaining:
            semester_name = semester_cycle[semester_index % 2]
            semester_index += 1

            eligible = self._eligible_courses(
                remaining, completed, year, semester_name
            )

            semester_courses = []
            credits = 0

            for code in sorted(eligible):
                course = self.courses[code]

                if credits + course.credits > self.max_credits:
                    continue

                semester_courses.append(course)
                credits += course.credits

            if not semester_courses:
                raise ValueError("No eligible courses available. Plan impossible.")

            for course in semester_courses:
                remaining.remove(course.code)
                completed.add(course.code)

            semesters.append(
                SemesterPlan(
                    year=year,
                    semester=semester_name,
                    courses=semester_courses,
                )
            )

            if semester_name == "S2":
                year += 1

        return DegreePlan(semesters)

    def _eligible_courses(
        self,
        remaining: Set[str],
        completed: Set[str],
        year: int,
        semester: str,
    ) -> List[str]:
        eligible = []

        for code in remaining:
            course = self.courses[code]

            if not course.is_offered(year, semester, self.campus, self.mode):
                continue

            if course.prerequisites and not course.prerequisites.is_satisfied(
                completed
            ):
                continue

            eligible.append(code)

        return eligible
