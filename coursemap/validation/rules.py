from abc import ABC, abstractmethod
from collections import defaultdict
from typing import Set

from coursemap.domain.plan import DegreePlan
from coursemap.domain.degree_requirements import DegreeRequirements
from coursemap.domain.electives import ElectivePool


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
            total = level_totals[level]

            if requirement.min_credits is not None:
                if total < requirement.min_credits:
                    raise ValidationError(
                        f"Level {level} credits {total} < required {requirement.min_credits}"
                    )

            if requirement.max_credits is not None:
                if total > requirement.max_credits:
                    raise ValidationError(
                        f"Level {level} credits {total} > allowed {requirement.max_credits}"
                    )

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
        # TODO: exclude courses already counted as core/major

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


class MajorCompletionRule(ValidationRule):
    def __init__(self, requirements):
        self.requirements = requirements

    def validate(self, plan: DegreePlan) -> None:
        majors_completed = 0

        plan_courses = {
            c.code
            for s in plan.semesters
            for c in s.courses
        }

        for major in self.requirements.available_majors:
            major_courses = plan_courses.intersection(major.required_courses)

            total = sum(
                c.credits
                for s in plan.semesters
                for c in s.courses
                if c.code in major_courses
            )

            credits_200 = sum(
                c.credits
                for s in plan.semesters
                for c in s.courses
                if c.code in major_courses and c.level == 200
            )

            credits_300 = sum(
                c.credits
                for s in plan.semesters
                for c in s.courses
                if c.code in major_courses and c.level == 300
            )

            if (
                total >= major.total_credits
                and credits_200 >= major.min_200_level
                and credits_300 >= major.min_300_level
            ):
                majors_completed += 1

        if majors_completed < self.requirements.required_majors:
            raise ValidationError("Major requirements not satisfied")
        

class AllowedCourseRule(ValidationRule):
    def __init__(self, requirements: DegreeRequirements):
        self.allowed = (
            requirements.core_courses
            | set().union(*(m.required_courses for m in requirements.available_majors))
            | set().union(*(p.course_codes for p in requirements.elective_pools))
        )

    def validate(self, plan: DegreePlan) -> None:
        for s in plan.semesters:
            for c in s.courses:
                if c.code not in self.allowed:
                    raise ValidationError(f"Course {c.code} not allowed by degree")


# TODO: fix binary validation with internal errors e.g
"""ValidationResult:
    - passed: bool
    - errors: List[ValidationIssue]"""
# TODO: constraint integration 