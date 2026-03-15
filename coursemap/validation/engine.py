from dataclasses import dataclass
from typing import List

from coursemap.domain.plan import DegreePlan
from coursemap.domain.requirement_nodes import RequirementNode


@dataclass
class ValidationResult:
    passed: bool
    errors: List[str]


class DegreeValidator:
    """Validates a degree plan against a requirement tree."""

    def __init__(self, degree_requirement: RequirementNode):
        self.degree_requirement = degree_requirement

    def validate(self, plan: DegreePlan) -> ValidationResult:
        passed = self.degree_requirement.is_satisfied(plan)
        errors = [] if passed else ["Degree requirements not satisfied"]
        return ValidationResult(passed=passed, errors=errors)
