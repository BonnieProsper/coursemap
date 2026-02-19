from abc import ABC, abstractmethod
from collections import defaultdict
from typing import List

from coursemap.domain.plan import DegreePlan
from coursemap.domain.degree_requirements import DegreeRequirements


class ValidationError(Exception):
    pass


class ValidationRule(ABC):
    @abstractmethod
    def validate(self, plan: DegreePlan) -> None:
        ...


class TotalCreditRule(ValidationRule):
    def __init__(self, requirements: DegreeRequirements):
        self.requirements = requirements

    def validate(self, plan: DegreePlan) -> None:
        total = sum(
            course.credits
            for semester in plan.semesters
            for course in semester.courses
        )

        if total != self.requirements.total_credits:
            raise ValidationError(
                f"Total credits {total} != required {self.requirements.total_credits}"
            )


class LevelCreditRule(ValidationRule):
    def __init__(self, requirements: DegreeRequirements):
        self.requirements = requirements

    def validate(self, plan: DegreePlan) -> None:
        level_totals = defaultdict(int)

        for semester in plan.semesters:
            for course in semester.courses:
                level_totals[course.level] += course.credits

        for level, requirement in self.requirements.level_requirements.items():
            if level_totals[level] < requirement.min_credits:
                raise ValidationError(
                    f"Level {level} credits {level_totals[level]} "
                    f"< required {requirement.min_credits}"
                )

from typing import Set
from coursemap.domain.electives import ElectivePool


class CoreCourseRule(ValidationRule):
    def __init__(self, core_courses: Set[str]):
        self.core_courses = core_courses

    def validate(self, plan: DegreePlan) -> None:
        completed = {
            c.code
            for semester in plan.semesters
            for c in semester.courses
        }

        missing = self.core_courses - completed
        if missing:
            raise ValidationError(f"Missing core courses: {missing}")


class ElectivePoolRule(ValidationRule):
    def __init__(self, pool: ElectivePool):
        self.pool = pool

    def validate(self, plan: DegreePlan) -> None:
        credits = 0

        for semester in plan.semesters:
            for course in semester.courses:
                if course.code in self.pool.course_codes:
                    credits += course.credits

        if credits < self.pool.min_credits:
            raise ValidationError(
                f"Elective pool '{self.pool.name}' requires "
                f"{self.pool.min_credits} credits, got {credits}"
            )
