from typing import Dict, List, Set

from coursemap.domain.course import Course
from coursemap.domain.plan import DegreePlan, SemesterPlan


class PlanGenerator:
    """
    Deterministic prerequisite-aware scheduler.
    Offerings are year-agnostic (repeat annually).
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

    def generate(self) -> DegreePlan:
        remaining: Set[str] = set(self.courses.keys())
        completed: Set[str] = set()
        semesters: List[SemesterPlan] = []

        base_year = self.start_year
        semester_cycle = ["S1", "S2", "SS"]
        semester_index = 0

        max_semesters = 20  # hard safety bound

        while remaining:
            if semester_index > max_semesters:
                raise ValueError(
                    "Scheduling exceeded safe horizon. "
                    "Possible unsatisfiable prerequisites or offerings."
                )

            semester_name = semester_cycle[semester_index % 2]
            current_year = base_year + (semester_index // 2)
            semester_index += 1

            eligible = self._eligible_courses(
                remaining, completed, semester_name
            )

            if not eligible:
                # If nothing eligible this semester, try next semester
                # But detect global deadlock
                if not self._any_future_possible(remaining, completed):
                    raise ValueError(
                        "No schedulable courses remain. "
                        "Prerequisite or offering deadlock detected."
                    )
                continue

            semester_courses = []
            credits = 0

            for code in sorted(eligible):
                course = self.courses[code]

                if credits + course.credits > self.max_credits:
                    continue

                semester_courses.append(course)
                credits += course.credits

            if not semester_courses:
                continue

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

        return DegreePlan(semesters)

    def _eligible_courses(
        self,
        remaining: Set[str],
        completed: Set[str],
        semester: str,
    ) -> List[str]:
        eligible = []

        for code in remaining:
            course = self.courses[code]

            if not course.is_offered(
                semester=semester,
                campus=self.campus,
                mode=self.mode,
            ):
                continue

            if (
                course.prerequisites
                and not course.prerequisites.is_satisfied(completed)
            ):
                continue

            eligible.append(code)

        return eligible

    def _any_future_possible(
        self,
        remaining: Set[str],
        completed: Set[str],
    ) -> bool:
        """
        Detect global deadlock:
        Is there ANY course whose prerequisites are satisfied?
        """
        for code in remaining:
            course = self.courses[code]

            if (
                not course.prerequisites
                or course.prerequisites.is_satisfied(completed)
            ):
                return True

        return False
