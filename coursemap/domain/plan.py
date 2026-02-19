from dataclasses import dataclass
from typing import List

from .course import Course


@dataclass
class SemesterPlan:
    year: int
    semester: str
    courses: List[Course]

    def total_credits(self) -> int:
        return sum(course.credits for course in self.courses)


@dataclass
class DegreePlan:
    semesters: List[SemesterPlan]

    def total_credits(self) -> int:
        return sum(semester.total_credits() for semester in self.semesters)

    def all_course_codes(self) -> set[str]:
        codes = set()
        for semester in self.semesters:
            for course in semester.courses:
                codes.add(course.code)
        return codes
