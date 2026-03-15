"""
Degree requirement tree nodes as described in docs/03_requirement_language.md.
Each node implements is_satisfied(plan) to evaluate against a degree plan.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from .plan import DegreePlan


class RequirementNode(ABC):
    """Base type for all degree requirement tree nodes."""

    @abstractmethod
    def is_satisfied(self, plan: DegreePlan) -> bool:
        """Return True if this requirement is satisfied by the given plan."""
        ...


@dataclass(frozen=True)
class CourseRequirement(RequirementNode):
    """Represents a required course."""

    course_code: str

    def is_satisfied(self, plan: DegreePlan) -> bool:
        return self.course_code in plan.all_course_codes()


@dataclass(frozen=True)
class AllOfRequirement(RequirementNode):
    """All child requirements must be satisfied."""

    children: tuple[RequirementNode, ...]

    def is_satisfied(self, plan: DegreePlan) -> bool:
        return all(child.is_satisfied(plan) for child in self.children)


@dataclass(frozen=True)
class AnyOfRequirement(RequirementNode):
    """At least one child requirement must be satisfied."""

    children: tuple[RequirementNode, ...]

    def is_satisfied(self, plan: DegreePlan) -> bool:
        return any(child.is_satisfied(plan) for child in self.children)


@dataclass(frozen=True)
class ChooseCreditsRequirement(RequirementNode):
    """Choose courses totaling a specified credit amount from a list."""

    credits: int
    course_codes: tuple[str, ...]

    def is_satisfied(self, plan: DegreePlan) -> bool:
        allowed = set(self.course_codes)
        total = sum(
            course.credits
            for semester in plan.semesters
            for course in semester.courses
            if course.code in allowed
        )
        return total >= self.credits


@dataclass(frozen=True)
class ChooseNRequirement(RequirementNode):
    """Choose N courses from a list."""

    n: int
    course_codes: tuple[str, ...]

    def is_satisfied(self, plan: DegreePlan) -> bool:
        plan_codes = plan.all_course_codes()
        chosen = sum(1 for code in self.course_codes if code in plan_codes)
        return chosen >= self.n


@dataclass(frozen=True)
class MinLevelCreditsRequirement(RequirementNode):
    """Minimum credits from courses at a specific level."""

    level: int
    min_credits: int

    def is_satisfied(self, plan: DegreePlan) -> bool:
        total = 0
        for semester in plan.semesters:
            for course in semester.courses:
                if course.level == self.level:
                    total += course.credits
        return total >= self.min_credits


@dataclass(frozen=True)
class TotalCreditsRequirement(RequirementNode):
    """Total credits required for the degree."""

    required_credits: int

    def is_satisfied(self, plan: DegreePlan) -> bool:
        return plan.total_credits() >= self.required_credits


@dataclass(frozen=True)
class MajorRequirement(RequirementNode):
    """Requirement representing a major program (subtree)."""

    name: str
    requirement: RequirementNode

    def is_satisfied(self, plan: DegreePlan) -> bool:
        return self.requirement.is_satisfied(plan)
