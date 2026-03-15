import pytest

from coursemap.domain.seed_data import build_seed_courses
from coursemap.planner.generator import PlanGenerator
from coursemap.domain.degree_requirements import (
    DegreeRequirements,
    LevelCreditRequirement,
)
from coursemap.validation.engine import DegreeValidator
from coursemap.validation.tree_builder import build_requirement_tree


def test_degree_validation_passes():
    courses = build_seed_courses()

    generator = PlanGenerator(courses)
    plan = generator.generate()

    requirements = DegreeRequirements(
        total_credits=165,  # must match seed dataset
        max_100_level=None,
        min_300_level=None,
        level_requirements={
            100: LevelCreditRequirement(100, 60),
            200: LevelCreditRequirement(200, 60),
            300: LevelCreditRequirement(300, 45),
        },
        core_courses=set(courses.keys()),
        min_schedule_credits=None,
        required_majors=0,
        available_majors=[],
        elective_pools=[],
    )

    degree_requirement = build_requirement_tree(requirements)
    validator = DegreeValidator(degree_requirement)
    result = validator.validate(plan)
    assert result.passed


def test_degree_validation_fails_on_wrong_total():
    courses = build_seed_courses()

    generator = PlanGenerator(courses)
    plan = generator.generate()

    requirements = DegreeRequirements(
        total_credits=999,
        max_100_level=None,
        min_300_level=None,
        level_requirements={},
        core_courses=set(),
        min_schedule_credits=None,
        required_majors=0,
        available_majors=[],
        elective_pools=[],
    )

    degree_requirement = build_requirement_tree(requirements)
    validator = DegreeValidator(degree_requirement)
    result = validator.validate(plan)
    assert not result.passed
    assert "Degree requirements not satisfied" in result.errors
