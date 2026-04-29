"""Degree plan validation against a requirement node tree."""
from __future__ import annotations

from dataclasses import dataclass

from coursemap.domain.plan import DegreePlan
from coursemap.domain.requirement_nodes import (
    AllOfRequirement,
    AnyOfRequirement,
    ChooseCreditsRequirement,
    ChooseNRequirement,
    CourseRequirement,
    MajorRequirement,
    MaxLevelCreditsRequirement,
    MinLevelCreditsFromRequirement,
    MinLevelCreditsRequirement,
    RequirementNode,
    TotalCreditsRequirement,
)


@dataclass
class ValidationResult:
    passed: bool
    errors: list[str]


class DegreeValidator:
    """Validates a degree plan against a requirement node tree."""

    def __init__(self, requirement: RequirementNode):
        self.requirement = requirement

    def validate(self, plan: DegreePlan) -> ValidationResult:
        errors: list[str] = []
        _check(self.requirement, plan, errors)
        return ValidationResult(passed=not errors, errors=errors)


def _check(node: RequirementNode, plan: DegreePlan, errors: list[str]) -> bool:
    """
    Recursively walk the requirement tree and collect every unsatisfied leaf.

    Returns True when this subtree is satisfied. Accumulates human-readable
    error messages into errors for every failing node so the caller gets a
    complete picture rather than stopping at the first failure.
    """
    if isinstance(node, CourseRequirement):
        if node.course_code not in plan.all_course_codes:
            errors.append(f"Missing required course {node.course_code}.")
            return False
        return True

    if isinstance(node, TotalCreditsRequirement):
        total = plan.total_credits() + plan.prior_credits()
        if total < node.required_credits:
            errors.append(
                f"Total credits {total} is below required {node.required_credits}."
            )
            return False
        return True

    if isinstance(node, MinLevelCreditsRequirement):
        total = sum(
            c.credits
            for s in plan.semesters
            for c in s.courses
            if c.level == node.level
        )
        if total < node.min_credits:
            errors.append(
                f"Only {total}cr at level {node.level} "
                f"(need at least {node.min_credits}cr)."
            )
            return False
        return True

    if isinstance(node, MaxLevelCreditsRequirement):
        total = sum(
            c.credits
            for s in plan.semesters
            for c in s.courses
            if c.level == node.level
        )
        if total > node.max_credits:
            errors.append(
                f"{total}cr at level {node.level} exceeds cap of {node.max_credits}cr."
            )
            return False
        return True

    if isinstance(node, MinLevelCreditsFromRequirement):
        allowed = set(node.course_codes)
        total = sum(
            c.credits
            for s in plan.semesters
            for c in s.courses
            if c.code in allowed and c.level == node.level
        )
        if total < node.min_credits:
            errors.append(
                f"Only {total}cr at level {node.level} from the required pool "
                f"(need at least {node.min_credits}cr)."
            )
            return False
        return True

    if isinstance(node, ChooseCreditsRequirement):
        if node.credits <= 0:
            # Pool with unknown credit target: treat as satisfied.
            return True
        allowed = set(node.course_codes)
        total = sum(
            c.credits
            for s in plan.semesters
            for c in s.courses
            if c.code in allowed
        )
        total += sum(
            c.credits for c in plan.prior_completed if c.code in allowed
        )
        if total < node.credits:
            errors.append(
                f"Elective pool: have {total}cr, need {node.credits}cr "
                f"from {len(node.course_codes)} available courses."
            )
            return False
        return True

    if isinstance(node, ChooseNRequirement):
        plan_codes = plan.all_course_codes
        chosen = sum(1 for code in node.course_codes if code in plan_codes)
        if chosen < node.n:
            errors.append(
                f"Choose-N requirement: have {chosen} of required {node.n} courses."
            )
            return False
        return True

    if isinstance(node, AllOfRequirement):
        child_errors: list[str] = []
        ok = True
        for child in node.children:
            if not _check(child, plan, child_errors):
                ok = False
        errors.extend(child_errors)
        return ok

    if isinstance(node, AnyOfRequirement):
        if node.is_satisfied(plan):
            return True
        # None of the branches satisfied - collect errors from all of them.
        branch_errors: list[str] = []
        for child in node.children:
            _check(child, plan, branch_errors)
        errors.append(
            f"None of {len(node.children)} alternatives satisfied: "
            + "; OR ".join(branch_errors[:3])
            + ("..." if len(branch_errors) > 3 else "")
        )
        return False

    if isinstance(node, MajorRequirement):
        return _check(node.requirement, plan, errors)

    # Unknown node type: fall back to is_satisfied.
    if not node.is_satisfied(plan):
        errors.append(f"Unsatisfied requirement: {type(node).__name__}.")
        return False
    return True
