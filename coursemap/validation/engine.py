from dataclasses import dataclass
from typing import Iterable, List

from coursemap.domain.plan import DegreePlan
from coursemap.validation.rules import ValidationRule, ValidationError


@dataclass
class ValidationResult:
    passed: bool
    errors: List[str]


class DegreeValidator:
    def __init__(self, rules: Iterable[ValidationRule]):
        self.rules: List[ValidationRule] = list(rules)

    def validate(self, plan: DegreePlan) -> ValidationResult:
        errors: List[str] = []

        for rule in self.rules:
            try:
                rule.validate(plan)
            except ValidationError as e:
                errors.append(str(e))

        return ValidationResult(
            passed=len(errors) == 0,
            errors=errors,
        )