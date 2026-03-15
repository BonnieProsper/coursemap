"""
Build a RequirementNode tree from flat DegreeRequirements.
Used so validation can call degree_requirement.is_satisfied(plan).
"""
from coursemap.domain.degree_requirements import DegreeRequirements
from coursemap.domain.requirement_nodes import (
    AllOfRequirement,
    AnyOfRequirement,
    ChooseCreditsRequirement,
    CourseRequirement,
    MajorRequirement,
    MaxLevelCreditsRequirement,
    MinLevelCreditsFromRequirement,
    MinLevelCreditsRequirement,
    TotalCreditsRequirement,
)


def build_requirement_tree(requirements: DegreeRequirements) -> AllOfRequirement:
    """Convert flat DegreeRequirements into a requirement tree (root AllOf)."""
    children = []

    # Total credits
    children.append(TotalCreditsRequirement(required_credits=requirements.total_credits))

    # Global level caps/minimums
    if requirements.max_100_level is not None:
        children.append(
            MaxLevelCreditsRequirement(level=100, max_credits=requirements.max_100_level)
        )
    if requirements.min_300_level is not None:
        children.append(
            MinLevelCreditsRequirement(
                level=300, min_credits=requirements.min_300_level
            )
        )

    # Per-level requirements
    for level, lr in requirements.level_requirements.items():
        if lr.min_credits is not None:
            children.append(
                MinLevelCreditsRequirement(level=level, min_credits=lr.min_credits)
            )
        if lr.max_credits is not None:
            children.append(
                MaxLevelCreditsRequirement(level=level, max_credits=lr.max_credits)
            )

    # Core courses (all required)
    for code in sorted(requirements.core_courses):
        children.append(CourseRequirement(course_code=code))

    # Elective pools (choose credits from each pool)
    for pool in requirements.elective_pools:
        children.append(
            ChooseCreditsRequirement(
                credits=pool.min_credits,
                course_codes=tuple(sorted(pool.course_codes)),
            )
        )

    # Majors: at least one must be satisfied
    if requirements.available_majors and requirements.required_majors >= 1:
        major_nodes = [
            _major_requirement_node(major) for major in requirements.available_majors
        ]
        children.append(AnyOfRequirement(children=tuple(major_nodes)))

    return AllOfRequirement(children=tuple(children))


def _major_requirement_node(major) -> MajorRequirement:
    """Build the requirement subtree for one major."""
    sub_children = [
        ChooseCreditsRequirement(
            credits=major.total_credits,
            course_codes=tuple(major.required_courses),
        ),
        MinLevelCreditsFromRequirement(
            level=200,
            min_credits=major.min_200_level,
            course_codes=tuple(major.required_courses),
        ),
        MinLevelCreditsFromRequirement(
            level=300,
            min_credits=major.min_300_level,
            course_codes=tuple(major.required_courses),
        ),
    ]
    return MajorRequirement(
        name=major.name,
        requirement=AllOfRequirement(children=tuple(sub_children)),
    )
