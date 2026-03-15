"""
Tree traversal utilities for requirement nodes.
Work on arbitrarily nested requirement trees. Used for enumeration (e.g. solver), not validation.
"""
from __future__ import annotations

from typing import List, Set

from .requirement_nodes import (
    AllOfRequirement,
    AnyOfRequirement,
    ChooseCreditsRequirement,
    ChooseNRequirement,
    CourseRequirement,
    MajorRequirement,
    MinLevelCreditsFromRequirement,
    RequirementNode,
    TotalCreditsRequirement,
)


def collect_course_codes(node: RequirementNode) -> Set[str]:
    """Recursively collect all course codes mentioned anywhere in the tree."""
    out: Set[str] = set()
    if isinstance(node, CourseRequirement):
        out.add(node.course_code)
    elif isinstance(node, (AllOfRequirement, AnyOfRequirement)):
        for c in node.children:
            out |= collect_course_codes(c)
    elif isinstance(
        node,
        (ChooseCreditsRequirement, ChooseNRequirement, MinLevelCreditsFromRequirement),
    ):
        out.update(node.course_codes)
    elif isinstance(node, MajorRequirement):
        out |= collect_course_codes(node.requirement)
    return out


def collect_elective_nodes(
    node: RequirementNode,
) -> List[ChooseCreditsRequirement | ChooseNRequirement]:
    """Recursively collect all CHOOSE_CREDITS and CHOOSE_N nodes at any depth."""
    out: List[ChooseCreditsRequirement | ChooseNRequirement] = []
    if isinstance(node, (ChooseCreditsRequirement, ChooseNRequirement)):
        out.append(node)
    if isinstance(node, (AllOfRequirement, AnyOfRequirement)):
        for c in node.children:
            out.extend(collect_elective_nodes(c))
    elif isinstance(node, MajorRequirement):
        out.extend(collect_elective_nodes(node.requirement))
    return out


def collect_major_nodes(node: RequirementNode) -> List[MajorRequirement]:
    """Recursively collect all MAJOR nodes at any depth."""
    out: List[MajorRequirement] = []
    if isinstance(node, MajorRequirement):
        out.append(node)
        out.extend(collect_major_nodes(node.requirement))
    elif isinstance(node, (AllOfRequirement, AnyOfRequirement)):
        for c in node.children:
            out.extend(collect_major_nodes(c))
    return out


def find_total_credits(node: RequirementNode) -> int:
    """Return required_credits from the first TOTAL_CREDITS node found (pre-order). 0 if none."""
    if isinstance(node, TotalCreditsRequirement):
        return node.required_credits
    if isinstance(node, (AllOfRequirement, AnyOfRequirement)):
        for c in node.children:
            n = find_total_credits(c)
            if n != 0:
                return n
    elif isinstance(node, MajorRequirement):
        return find_total_credits(node.requirement)
    return 0


def collect_core_course_codes(node: RequirementNode, *, under_major: bool = False) -> Set[str]:
    """
    Collect course codes from COURSE nodes that are not inside a major.
    Used for degree-level required (core) courses; does not include codes from CHOOSE_* nodes.
    """
    out: Set[str] = set()
    if isinstance(node, CourseRequirement):
        if not under_major:
            out.add(node.course_code)
    elif isinstance(node, (AllOfRequirement, AnyOfRequirement)):
        for c in node.children:
            out |= collect_core_course_codes(c, under_major=under_major)
    elif isinstance(node, MajorRequirement):
        out |= collect_core_course_codes(node.requirement, under_major=True)
    return out
