from typing import Dict, List, Set

from coursemap.domain.course import Course
from coursemap.domain.plan import DegreePlan, SemesterPlan
from coursemap.planner.graph import PrerequisiteGraph


class PlanGenerator:
    """
    Deterministic, prerequisite-aware, offering-aware scheduler.

    Properties:
    - Allows empty semesters
    - Advances time indefinitely until completion
    - Detects true impossibility (no future offering exists)
    - Deterministic ordering
    """

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

        # validates DAG on construction
        self.graph = PrerequisiteGraph(courses)

    def generate(self) -> DegreePlan:
        remaining: Set[str] = set(self.courses.keys())
        completed: Set[str] = set()
        semesters: List[SemesterPlan] = []

        base_year = self.start_year
        semester_cycle = ["S1", "S2"]
        semester_index = 0

        # safety guard against infinite loops
        max_semesters = 50

        while remaining:
            if semester_index > max_semesters:
                raise ValueError("Exceeded maximum scheduling horizon.")

            semester_name = semester_cycle[semester_index % 2]
            current_year = base_year + (semester_index // 2)
            semester_index += 1

            eligible = self._eligible_courses(
                remaining, completed, current_year, semester_name
            )

            semester_courses = []
            credits = 0

            for code in sorted(eligible):
                course = self.courses[code]

                if credits + course.credits > self.max_credits:
                    continue

                semester_courses.append(course)
                credits += course.credits

            if semester_courses:
                for course in semester_courses:
                    remaining.remove(course.code)
                    completed.add(course.code)

            semesters.append(
                SemesterPlan(
                    year=current_year,
                    semester=semester_name,
                    courses=semester_courses,
                )
            )

            # Detect true impossibility:
            # If no remaining course can EVER be offered again
            if not semester_courses and not self._future_possible(remaining):
                raise ValueError("No remaining courses can be scheduled in future.")

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

    def _future_possible(self, remaining: Set[str]) -> bool:
        """
        Checks whether any remaining course has any offering
        in any semester in future years.
        """
        for code in remaining:
            course = self.courses[code]
            if course.offerings:
                return True
        return False
