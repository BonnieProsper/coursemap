import pytest

from coursemap.domain.seed_data import build_seed_courses
from coursemap.planner.generator import PlanGenerator
from coursemap.domain.degree_requirements import (
    DegreeRequirements,
    LevelCreditRequirement,
)
from coursemap.validation.rules import (
    TotalCreditRule,
    LevelCreditRule,
    ValidationError,
)
from coursemap.validation.engine import DegreeValidator


def test_degree_validation_passes():
    courses = build_seed_courses()

    generator = PlanGenerator(courses)
    plan = generator.generate()

    requirements = DegreeRequirements(
        total_credits=105,
        level_requirements={
            100: LevelCreditRequirement(100, 60),
            200: LevelCreditRequirement(200, 30),
            300: LevelCreditRequirement(300, 15),
        },
    )

    validator = DegreeValidator(
        [
            TotalCreditRule(requirements),
            LevelCreditRule(requirements),
        ]
    )

    validator.validate(plan)


def test_degree_validation_fails_on_wrong_total():
    courses = build_seed_courses()

    generator = PlanGenerator(courses)
    plan = generator.generate()

    requirements = DegreeRequirements(
        total_credits=999,
        level_requirements={},
    )

    validator = DegreeValidator(
        [TotalCreditRule(requirements)]
    )

    with pytest.raises(ValidationError):
        validator.validate(plan)
