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
    being scheduled) is treated as already satisfied.  This handles admission
    gatekeepers such as University Entrance codes that the scraper captures as
    prerequisites but that never appear as schedulable courses.

    Args:
        prereq:    The prerequisite expression to evaluate, or None.
        completed: Course codes that have already been scheduled.
        known:     Course codes that are in scope for this planning run.
                   Any prerequisite code absent from known is treated as
                   satisfied (i.e. assumed to be met outside this plan).
    """
    if prereq is None:
        return True
    if isinstance(prereq, CoursePrerequisite):
        return prereq.code not in known or prereq.code in completed
    if isinstance(prereq, (AndExpression, OrExpression)):
        fn = all if isinstance(prereq, AndExpression) else any
        return fn(prereqs_met(child, completed, known) for child in prereq.children)
    # Fallback for any future PrerequisiteExpression subclass: synthesise a
    # completed set that includes all out-of-scope codes as if they were done.
    return prereq.is_satisfied(completed | (prereq.required_courses() - known))
