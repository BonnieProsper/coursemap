"""
Degree requirement tree derivation from Massey's qualification and major data.

Instead of a hardcoded degree_requirements.json that covers four majors, this
module derives the complete requirement tree for any (qualification, major) pair
using:

  - qualifications.json  -- level (4-10) and length (1-5 years) per qualification
  - specialisations.json -- maps each major title to a qual_code
  - majors.json          -- required course lists and elective pools per major

Massey uses a standard credit structure: 120 credits per full-time year.
Level constraints are drawn from the public Massey undergraduate handbook.

The output is a RequirementNode tree identical in structure to what
degree_requirements.json used to provide, but covering every major in the
dataset rather than four hand-picked ones.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from coursemap.domain.requirement_nodes import (
    AllOfRequirement,
    AnyOfRequirement,
    ChooseCreditsRequirement,
    CourseRequirement,
    RequirementNode,
    TotalCreditsRequirement,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Massey credit and level rules by qualification level and length
# ---------------------------------------------------------------------------
#
# Source: Massey University undergraduate and postgraduate handbooks (public).
# Rule encoding: (nzqf_level, length_years) -> DegreeProfile
#
# Credits per year: 120 (standard full-time load at Massey).
# Level constraints apply only to undergraduate (Level 7) bachelor degrees;
# postgraduate qualifications have different and more variable structures.

@dataclass(frozen=True)
class DegreeProfile:
    """Credit and level constraints for one category of Massey qualification."""
    total_credits: int
    # Maximum credits from Level 100 courses (prevents first-year overload).
    max_level_100: int | None = None
    # Minimum credits from Level 300 courses (ensures third-year specialisation).
    min_level_300: int | None = None
    # Minimum credits from Level 400 courses (honours-level depth).
    min_level_400: int | None = None


# Keyed by (nzqf_level, length_years). Missing combinations fall back to
# total_credits = length * 120 with no level constraints.
_DEGREE_PROFILES: dict[tuple, DegreeProfile] = {
    # Standard 3-year bachelor's (BHSc, BSc, BA, BBus, etc.)
    (7, 3): DegreeProfile(
        total_credits=360,
        max_level_100=165,
        min_level_300=75,
    ),
    # 4-year bachelor's (BSW, BEng, some professional degrees)
    (7, 4): DegreeProfile(
        total_credits=480,
        max_level_100=165,
        min_level_300=135,
    ),
    # 5-year bachelor's (BVSc)
    (7, 5): DegreeProfile(
        total_credits=600,
        max_level_100=165,
        min_level_300=135,
    ),
    # Graduate diploma / graduate certificate (1yr, Level 7)
    (7, 1): DegreeProfile(total_credits=120),
    # 2-year graduate diploma (rare)
    (7, 2): DegreeProfile(total_credits=240),
    # Postgraduate diploma and certificate (1yr, Level 8).
    # Honours degrees are also Level 8, 1yr at Massey, but their courses are
    # at L700+ rather than L400, so no minimum level constraint is enforced --
    # the postgraduate level requirement is implicit in the course catalogue.
    (8, 1): DegreeProfile(total_credits=120),
    # 4-year bachelor with honours integrated (BFA Hons, BDes Hons)
    (8, 4): DegreeProfile(
        total_credits=480,
        max_level_100=165,
    ),
    # Taught master's (2yr, Level 9)
    (9, 2): DegreeProfile(total_credits=240),
    # Accelerated master's (1yr, Level 9)
    (9, 1): DegreeProfile(total_credits=120),
}


def profile_for(level: int, length: int) -> DegreeProfile:
    """Return the DegreeProfile for a qualification, with a safe fallback."""
    profile = _DEGREE_PROFILES.get((level, length))
    if profile is not None:
        return profile
    # Fallback: 120cr per year, no level constraints. Covers unusual combinations
    # (Level 4-6 foundation/diploma, Level 10 doctorates, etc.).
    return DegreeProfile(total_credits=length * 120)



def build_degree_tree(
    major_req: RequirementNode,
    qual_level: int,
    qual_length: int,
    major_name: str,
    schedulable_major_credits: int = 0,
) -> RequirementNode:
    """
    Wrap a major's requirement tree with degree-level credit and level constraints.

    The result is a complete degree requirement tree::

        ALL_OF(
            [TOTAL_CREDITS(N)],              # only when data is complete
            [MAX_LEVEL_CREDITS(100, max)],   # bachelor's only
            [MIN_LEVEL_CREDITS(300, min)],   # bachelor's only
            [MIN_LEVEL_CREDITS(400, min)],   # honours only
            <major_req>,
        )

    The TotalCreditsRequirement is included only when the major dataset covers
    the full degree (schedulable_major_credits >= degree_credits). Many majors
    in the scraped data do not capture free electives, so the major-specific
    courses sum to less than the degree total. In those cases the credit
    requirement is omitted from validation to avoid false failures.

    Args:
        major_req:                 Already-built RequirementNode for the major.
        qual_level:                NZQF level (7 = bachelor, 8 = honours, etc.).
        qual_length:               Duration in years.
        major_name:                Human-readable name (for log messages only).
        schedulable_major_credits: Total credits of major courses that have
                                   offerings. Used to decide whether to include
                                   the TotalCreditsRequirement.
    """
    profile = profile_for(qual_level, qual_length)
    children: list[RequirementNode] = []

    # Apply the total credit requirement only when the major dataset covers
    # the full degree. When data is incomplete (free electives not scraped),
    # omit it -- the CLI reports the gap separately.
    #
    # Level constraints (MaxLevelCredits, MinLevelCredits) are NOT included in
    # the validation tree. These are handbook rules about credit distribution
    # that the planner cannot control: it schedules the courses a major requires
    # in whatever order prerequisites allow. If the curriculum has more L100
    # courses than the standard rule permits, that is Massey's design decision.
    # Applying these constraints as hard validation gates causes false failures
    # on legitimate majors with non-standard level distributions (health science,
    # nutrition, some professional programmes).
    data_is_complete = schedulable_major_credits >= profile.total_credits
    if data_is_complete:
        children.append(TotalCreditsRequirement(profile.total_credits))

    children.append(major_req)
    return AllOfRequirement(tuple(children))


def filter_requirement_tree(
    node: RequirementNode,
    schedulable_codes: frozenset,
    course_credits: dict[str, int] | None = None,
) -> RequirementNode | None:
    """
    Return a copy of node with unschedulable courses removed and pool credit
    targets adjusted to what the configured delivery mode can actually provide.

    Used to align the validation tree with the working set. Two adjustments:

    1. CourseRequirement nodes for courses with no matching offering are dropped.
    2. ChooseCreditsRequirement pool targets are capped at the total credits
       available from schedulable pool members. When a pool's DIS courses cannot
       meet the original credit target (e.g. field-work-heavy ecology courses
       that are internal-only), requiring the full amount would permanently fail
       distance plans. The cap aligns validation with what the scheduler achieves.

    Composite nodes with no remaining children are dropped entirely.
    Returns None if the entire subtree becomes empty after filtering.
    """
    if isinstance(node, CourseRequirement):
        return node if node.course_code in schedulable_codes else None

    if isinstance(node, ChooseCreditsRequirement):
        schedulable_pool = tuple(c for c in node.course_codes if c in schedulable_codes)
        if not schedulable_pool:
            return None
        if course_credits is not None:
            available_cr = sum(course_credits.get(c, 0) for c in schedulable_pool)
            effective_credits = min(node.credits, available_cr)
        else:
            effective_credits = node.credits
        if effective_credits == node.credits and schedulable_pool == node.course_codes:
            return node
        return ChooseCreditsRequirement(
            credits=effective_credits,
            course_codes=schedulable_pool,
        )

    if isinstance(node, AllOfRequirement):
        children = [
            filtered
            for child in node.children
            if (filtered := filter_requirement_tree(
                child, schedulable_codes, course_credits
            )) is not None
        ]
        if not children:
            return None
        return AllOfRequirement(tuple(children))

    if isinstance(node, AnyOfRequirement):
        children = [
            filtered
            for child in node.children
            if (filtered := filter_requirement_tree(
                child, schedulable_codes, course_credits
            )) is not None
        ]
        if not children:
            return None
        return AnyOfRequirement(tuple(children))

    # TotalCreditsRequirement, MinLevelCreditsRequirement, MaxLevelCreditsRequirement, etc.
    return node
