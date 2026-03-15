"""
Serialize and deserialize requirement trees to/from JSON-friendly dicts.
Dataset format: each node is a dict with "type" and type-specific fields.
"""
from __future__ import annotations

from typing import Any, Dict, Set

from .requirement_nodes import (
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


def requirement_to_dict(node: RequirementNode) -> Dict[str, Any]:
    """Convert a RequirementNode to a JSON-serializable dict."""
    if isinstance(node, CourseRequirement):
        return {"type": "COURSE", "course_code": node.course_code}
    if isinstance(node, AllOfRequirement):
        return {
            "type": "ALL_OF",
            "children": [requirement_to_dict(c) for c in node.children],
        }
    if isinstance(node, AnyOfRequirement):
        return {
            "type": "ANY_OF",
            "children": [requirement_to_dict(c) for c in node.children],
        }
    if isinstance(node, ChooseCreditsRequirement):
        return {
            "type": "CHOOSE_CREDITS",
            "credits": node.credits,
            "course_codes": list(node.course_codes),
        }
    if isinstance(node, ChooseNRequirement):
        return {
            "type": "CHOOSE_N",
            "n": node.n,
            "course_codes": list(node.course_codes),
        }
    if isinstance(node, MinLevelCreditsRequirement):
        return {
            "type": "MIN_LEVEL_CREDITS",
            "level": node.level,
            "min_credits": node.min_credits,
        }
    if isinstance(node, MinLevelCreditsFromRequirement):
        return {
            "type": "MIN_LEVEL_CREDITS_FROM",
            "level": node.level,
            "min_credits": node.min_credits,
            "course_codes": list(node.course_codes),
        }
    if isinstance(node, MaxLevelCreditsRequirement):
        return {
            "type": "MAX_LEVEL_CREDITS",
            "level": node.level,
            "max_credits": node.max_credits,
        }
    if isinstance(node, TotalCreditsRequirement):
        return {"type": "TOTAL_CREDITS", "required_credits": node.required_credits}
    if isinstance(node, MajorRequirement):
        return {
            "type": "MAJOR",
            "name": node.name,
            "requirement": requirement_to_dict(node.requirement),
        }
    raise ValueError(f"Unknown requirement node type: {type(node)}")


def requirement_from_dict(data: Dict[str, Any]) -> RequirementNode:
    """Parse a dict (e.g. from JSON) into a RequirementNode."""
    if not isinstance(data, dict) or "type" not in data:
        raise ValueError("Requirement dict must have 'type' key")
    typ = data["type"]
    if typ == "COURSE":
        return CourseRequirement(course_code=data["course_code"])
    if typ == "ALL_OF":
        children = [requirement_from_dict(c) for c in data["children"]]
        return AllOfRequirement(children=tuple(children))
    if typ == "ANY_OF":
        children = [requirement_from_dict(c) for c in data["children"]]
        return AnyOfRequirement(children=tuple(children))
    if typ == "CHOOSE_CREDITS":
        return ChooseCreditsRequirement(
            credits=int(data["credits"]),
            course_codes=tuple(data["course_codes"]),
        )
    if typ == "CHOOSE_N":
        return ChooseNRequirement(
            n=int(data["n"]),
            course_codes=tuple(data["course_codes"]),
        )
    if typ == "MIN_LEVEL_CREDITS":
        return MinLevelCreditsRequirement(
            level=int(data["level"]),
            min_credits=int(data["min_credits"]),
        )
    if typ == "MIN_LEVEL_CREDITS_FROM":
        return MinLevelCreditsFromRequirement(
            level=int(data["level"]),
            min_credits=int(data["min_credits"]),
            course_codes=tuple(data["course_codes"]),
        )
    if typ == "MAX_LEVEL_CREDITS":
        return MaxLevelCreditsRequirement(
            level=int(data["level"]),
            max_credits=int(data["max_credits"]),
        )
    if typ == "TOTAL_CREDITS":
        return TotalCreditsRequirement(required_credits=int(data["required_credits"]))
    if typ == "MAJOR":
        return MajorRequirement(
            name=data["name"],
            requirement=requirement_from_dict(data["requirement"]),
        )
    raise ValueError(f"Unknown requirement type: {typ!r}")


def requirement_collect_course_codes(node: RequirementNode) -> Set[str]:
    """Recursively collect all course codes mentioned in a requirement tree."""
    from .requirement_utils import collect_course_codes
    return collect_course_codes(node)
