from typing import List

from coursemap.domain.plan import DegreePlan
from coursemap.validation.rules import ValidationRule


class DegreeValidator:
    def __init__(self, rules: List[ValidationRule]):
        self.rules = rules

    def validate(self, plan: DegreePlan) -> None:
        for rule in self.rules:
            rule.validate(plan)
