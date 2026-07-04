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


def _collect_claimed_codes(
    node: RequirementNode,
    plan_codes: list[str] | None = None,
    credits_by_code: dict[str, int] | None = None,
) -> set[str]:
    """
    Collect course codes already claimed by a specific requirement, so an
    open elective pool doesn't double-count credits a course is already
    satisfying elsewhere.

    CourseRequirement codes are always claimed. For pool requirements
    (ChooseCreditsRequirement, ChooseNRequirement, MinLevelCreditsFromRequirement),
    only as many plan members as the pool's own credit target needs are
    claimed. Extra eligible courses beyond that target are left free to
    count toward an open pool instead.

    `plan_codes` and `credits_by_code` let claiming be computed against an
    actual plan; when either is None, every named pool member is claimed
    (the conservative fallback, for callers with only the tree).
    """
    claimed: set[str] = set()
    stack = [node]
    while stack:
        n = stack.pop()
        if isinstance(n, CourseRequirement):
            claimed.add(n.course_code)
        elif isinstance(n, ChooseCreditsRequirement):
            if n.open_pool and not n.course_codes:
                continue
            if plan_codes is None or credits_by_code is None:
                claimed.update(n.course_codes)
            else:
                pool_members_in_plan = [c for c in plan_codes if c in n.course_codes]
                running = 0
                for code in pool_members_in_plan:
                    if running >= n.credits:
                        break
                    if code in claimed:
                        continue
                    claimed.add(code)
                    running += credits_by_code.get(code, 0)
        elif isinstance(n, (ChooseNRequirement, MinLevelCreditsFromRequirement)):
            claimed.update(n.course_codes)
        elif isinstance(n, (AllOfRequirement, AnyOfRequirement)):
            stack.extend(n.children)
        elif isinstance(n, MajorRequirement):
            stack.append(n.requirement)
    return claimed


class DegreeValidator:
    """Validates a degree plan against a requirement node tree."""

    def __init__(self, requirement: RequirementNode):
        self.requirement = requirement

    def validate(self, plan: DegreePlan) -> ValidationResult:
        errors: list[str] = []
        all_plan_courses = [c for s in plan.semesters for c in s.courses] + list(plan.prior_completed)
        plan_codes = [c.code for c in all_plan_courses]
        credits_by_code = {c.code: c.credits for c in all_plan_courses}
        claimed = _collect_claimed_codes(self.requirement, plan_codes, credits_by_code)
        _check(self.requirement, plan, errors, claimed)
        return ValidationResult(passed=not errors, errors=errors)


def _check(
    node: RequirementNode,
    plan: DegreePlan,
    errors: list[str],
    claimed: set[str] | None = None,
) -> bool:
    """
    Recursively walk the requirement tree and collect every unsatisfied leaf.

    Returns True when this subtree is satisfied. Accumulates human-readable
    error messages into errors for every failing node so the caller gets a
    complete picture rather than stopping at the first failure.

    `claimed` is the set of course codes already named by some specific
    requirement elsewhere in the full tree (see `_collect_claimed_codes`).
    It's used only by open ChooseCreditsRequirement pools, to avoid counting
    a course toward both its own specific requirement and an unrelated open
    elective pool.
    """
    if claimed is None:
        claimed = set()

    if isinstance(node, CourseRequirement):
        if node.course_code not in plan.all_course_codes:
            errors.append(f"Missing required course {node.course_code}.")
            return False
        return True

    if isinstance(node, TotalCreditsRequirement):
        total = plan.total_credits() + plan.prior_credits() + getattr(plan, "transfer_credits", 0)
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

        if node.open_pool and not node.course_codes:
            # Open pool: count any plan credits not already claimed by a
            # more specific requirement elsewhere in the tree.
            total = sum(
                c.credits
                for s in plan.semesters
                for c in s.courses
                if c.code not in claimed
            )
            total += sum(
                c.credits for c in plan.prior_completed if c.code not in claimed
            )
            if total < node.credits:
                errors.append(
                    f"Free electives: have {total}cr, need {node.credits}cr "
                    f"from any course not already counted elsewhere."
                )
                return False
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
            if not _check(child, plan, child_errors, claimed):
                ok = False
        errors.extend(child_errors)
        return ok

    if isinstance(node, AnyOfRequirement):
        if node.is_satisfied(plan):
            return True
        # None of the branches satisfied. Collect errors from all of them.
        branch_errors: list[str] = []
        for child in node.children:
            _check(child, plan, branch_errors, claimed)
        errors.append(
            f"None of {len(node.children)} alternatives satisfied: "
            + "; OR ".join(branch_errors[:3])
            + ("..." if len(branch_errors) > 3 else "")
        )
        return False

    if isinstance(node, MajorRequirement):
        return _check(node.requirement, plan, errors, claimed)

    # Unknown node type: fall back to is_satisfied.
    if not node.is_satisfied(plan):
        errors.append(f"Unsatisfied requirement: {type(node).__name__}.")
        return False
    return True

