"""
Utility helpers for evaluating prerequisite expressions in a scheduling context.
"""

from __future__ import annotations
from coursemap.domain.prerequisite import (
    AndExpression,
    CoursePrerequisite,
    OrExpression,
    PrerequisiteExpression,
)


def prereqs_met(
    prereq: PrerequisiteExpression | None,
    completed: set[str],
    known: set[str],
) -> bool:
    """
    Return True if prereq is satisfied given the completed and known sets.

    A prerequisite code that is not in known (i.e. not one of the courses
    being scheduled) is treated as already satisfied. This handles admission
    gatekeepers such as University Entrance codes that the scraper captures as
    prerequisites but that never appear as schedulable courses.

    Args:
        prereq:    The prerequisite expression to evaluate, or None.
        completed: Course codes that have already been scheduled.
        known:     Course codes that are in scope for this planning run.
                   Any prerequisite code absent from known is treated as
                   satisfied (i.e. assumed to be met outside this plan).

    Note: this can't distinguish a genuine external gatekeeper from an
    OR-sibling branch the working-set builder chose not to include. Both
    are simply absent from `known`. Callers building `known` from an OR
    expansion should resolve the chosen branch explicitly (see
    PlanSearch._build_working_set) rather than relying on this function to
    infer which case applies.
    """
    if prereq is None:
        return True
    if isinstance(prereq, CoursePrerequisite):
        return prereq.code not in known or prereq.code in completed
    if isinstance(prereq, (AndExpression, OrExpression)):
        fn = all if isinstance(prereq, AndExpression) else any
        return fn(prereqs_met(child, completed, known) for child in prereq.children)
    # Fallback for any future PrerequisiteExpression subclass.
    # KNOWN LIMITATION: required_courses() returns the union of all OR branches,
    # so this check is too permissive for OR expressions. It may return True
    # when only some OR branches are satisfied via out-of-scope codes.
    # This fallback only fires for unknown subclasses; in practice it is dead code.
    return prereq.is_satisfied(completed | (prereq.required_courses() - known))


def forced_prereq_closure(
    code: str,
    context: set[str],
    courses: dict,
) -> frozenset[str]:
    """
    Course codes that would end up in the working set purely because
    `code` has no way around needing them: a plain prerequisite, or an AND
    branch, with no OR alternative already satisfied by `context`.

    `context` is the set of codes to treat as already available (selected
    so far, prior completions, anything else already locked in) - an OR
    branch already in context needs no further expansion, since it's free.

    Used to catch conflicts one level removed from a candidate's own
    restrictions field: a course can have no restriction of its own and
    still force a restricted course in later via its prerequisite chain.
    """
    result: set[str] = set()
    visited: set[str] = {code}

    def _walk(node) -> None:
        if node is None:
            return
        if isinstance(node, CoursePrerequisite):
            child = node.code
            if child in context or child in result or child in visited or child not in courses:
                return
            result.add(child)
            visited.add(child)
            _walk(courses[child].prerequisites)
        elif isinstance(node, AndExpression):
            for c in node.children:
                _walk(c)
        elif isinstance(node, OrExpression):
            for c in node.children:
                if isinstance(c, CoursePrerequisite) and c.code in context:
                    return  # already satisfied, nothing forced
            best = min(
                node.children,
                key=lambda c: courses[c.code].level if isinstance(c, CoursePrerequisite) and c.code in courses else 999,
            )
            _walk(best)

    if code in courses:
        _walk(courses[code].prerequisites)
    return frozenset(result)


def would_restriction_conflict(
    code: str,
    locked_codes: set[str],
    courses: dict,
    context: set[str] | None = None,
) -> bool:
    """
    True if adding `code` would conflict, directly or transitively, with
    anything in `locked_codes` (already-selected or otherwise-committed
    course codes it must not restriction-conflict with) - or with anything
    THOSE codes will themselves eventually force in via their own
    unresolved prerequisites.

    That second part matters for a case direct-only closure checking
    misses: a course already in locked_codes (e.g. one entered via
    always_include, not picked from a pool) can itself carry an
    unresolved OR prerequisite. Nothing has walked ITS closure yet, since
    forced_prereq_closure is normally only computed for a fresh candidate.
    If the candidate's own closure conflicts with what that locked
    course's closure will eventually add, the conflict is real but
    invisible unless both sides are expanded. Concrete case: 159102 (OR-
    requires 159100 or 159101) already locked in via always_include,
    candidate 159261 (bare-requires 159101, which restricts 159100) -
    159100 isn't in locked_codes yet, only 159102 is, so a candidate-only
    closure check never sees the eventual conflict.

    Checked both ways since scraped restriction data isn't guaranteed to
    list a pair from both sides.

    `context` defaults to locked_codes; pass a wider set (e.g. including
    prior-completed courses) if the caller has one available.
    """
    course = courses.get(code)
    if course is None:
        return False

    closure_context = context if context is not None else locked_codes
    candidate_group = {code} | forced_prereq_closure(code, closure_context, courses)

    locked_group = set(locked_codes)
    for other in locked_codes:
        locked_group |= forced_prereq_closure(other, closure_context, courses)

    for a in candidate_group:
        a_course = courses.get(a)
        if a_course is None:
            continue
        if a_course.restrictions & locked_group:
            return True
        for b in locked_group:
            b_course = courses.get(b)
            if b_course and a in b_course.restrictions:
                return True
    return False
