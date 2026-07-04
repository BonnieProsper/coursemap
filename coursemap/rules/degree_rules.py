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
#
# Caveat: max_level_100/min_level_300 here are shared across every 3/4/5-year
# bachelor's degree, but Massey's actual regulations set these per degree
# schedule, not per (level, length). Verified against live regulations for
# BSc, BA, BCom, and BInfoSci: all four use exactly 165/75, which is why a
# single shared profile is a reasonable default. Bachelor of Business is a
# known exception (cap is 180, not 165); it isn't special-cased here because
# doing so precisely would mean keying DegreeProfile by qualification name
# instead of (level, length), a bigger change than this dataclass currently
# supports. A BBus plan is very unlikely to hit exactly 166-180cr at L100
# and get incorrectly flagged, but it is possible, flag it if a student
# reports a false failure there.
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



def cap_overcaptured_required_codes(
    required_codes: set[str],
    pool_nodes: list,
    degree_total: int,
    course_credits: dict[str, int],
    course_levels: dict[str, int],
    schedulable_codes: frozenset,
    tree_required: set[str],
) -> tuple[set[str], bool]:
    """
    Decide which required-course codes to keep when a major's data lists
    more required courses than the degree's credit target allows for
    (typically because several alternative specialisation tracks were
    flattened into one list rather than the degree genuinely needing that
    many credits).

    Returns (kept_codes, was_capped); kept_codes equals required_codes
    unchanged when was_capped is False. Codes in `tree_required` are never
    dropped. Only the remaining, genuinely-droppable excess is capped, by
    the same priority order PlanSearch uses when generating a plan
    (in-tree, schedulable, lower level, then code).

    For callers without a specific generated plan (e.g. /api/plan/validate,
    which rebuilds the tree fresh), this is necessarily an approximation of
    what an actual generated plan would keep.
    """
    if degree_total <= 0:
        return required_codes, False

    req_total = sum(course_credits.get(c, 0) for c in required_codes)
    schedulable_pool_contribution = sum(
        min(
            n.credits,
            sum(
                course_credits.get(c, 0) for c in n.course_codes
                if c in schedulable_codes
            ),
        )
        for n in pool_nodes
    )

    req_budget = (
        max(0, degree_total - schedulable_pool_contribution)
        if req_total + schedulable_pool_contribution > degree_total
        else degree_total
    )
    if req_total <= req_budget:
        return required_codes, False

    def _req_sort(code: str) -> tuple:
        credits = course_credits.get(code)
        if credits is None:
            return (1, 2, 999, code)
        in_tree = 0 if code in tree_required else 1
        has_matching = 0 if code in schedulable_codes else 1
        level = course_levels.get(code, 999)
        return (in_tree, has_matching, level, code)

    kept: set[str] = set()
    running = 0
    for code in sorted(required_codes, key=_req_sort):
        if running >= req_budget:
            break
        credits = course_credits.get(code)
        if credits is None:
            continue
        kept.add(code)
        running += credits
    return kept, True


def build_degree_tree(
    major_req: RequirementNode,
    qual_level: int,
    qual_length: int,
    major_name: str,
    schedulable_major_credits: int = 0,
    force_total_credits: bool = False,
    override_total_credits: int | None = None,
) -> RequirementNode:
    """
    Wrap a major's requirement tree with degree-level credit and level constraints.

    The result is a complete degree requirement tree::

        ALL_OF(
            [TOTAL_CREDITS(N)],              # when data complete OR force_total_credits=True
            <major_req>,
        )

    The TotalCreditsRequirement is included when the major dataset covers the
    full degree (schedulable_major_credits >= degree_credits) OR when
    force_total_credits=True (used by generate_filled_plan after augmenting the
    requirement tree with filler courses to reach the degree total).

    NOTE: this does not yet emit MaxLevelCreditsRequirement/MinLevelCreditsRequirement
    from the profile's max_level_100/min_level_300/min_level_400, even though those
    are computed correctly by profile_for and ElectiveFiller is already
    distribution-aware (see PlannerService._level_distribution_state). See the
    NOTE in the function body for the second, separate issue blocking this.

    Args:
        major_req:                 Already-built RequirementNode for the major.
        qual_level:                NZQF level (7 = bachelor, 8 = honours, etc.).
        qual_length:                Duration in years.
        major_name:                Human-readable name (for log messages only).
        schedulable_major_credits: Total credits of major courses that have
                                   offerings. Used to decide whether to include
                                   the TotalCreditsRequirement automatically.
        force_total_credits:       If True, always include TotalCreditsRequirement
                                   regardless of schedulable_major_credits. Used
                                   by the filled-plan path after injecting filler
                                   courses that bring the working set to degree total.
    """
    profile = profile_for(qual_level, qual_length)
    children: list[RequirementNode] = []

    # Include TotalCreditsRequirement when:
    #   a) The scraped major data fully covers the degree (data_is_complete), or
    #   b) The caller explicitly requests it (force_total_credits=True), which the
    #      filled-plan path uses after augmenting the tree with filler courses.
    #
    # When neither condition holds the credit target is reported separately as a
    # "free elective gap" so the student knows they must self-select extra courses.
    #
    # History: profile.max_level_100 / min_level_300 / min_level_400 were
    # wired in twice and reverted twice. Attempt 1: naive wiring, reverted
    # immediately, ElectiveFiller/PlanSearch had no concept of level
    # distribution at all (CS-BInfoSci: 195cr/165cr-max at L100, 60cr/75cr-min
    # at L300). Attempt 2: made ElectiveFiller distribution-aware
    # (PlannerService._level_distribution_state, ElectiveFiller's dedicated
    # Tier 1 for the distribution floor, level_credit_limits for the cap).
    # That fixed the majors attempt 1 broke, but surfaced a SEPARATE,
    # pre-existing issue: _select_electives always fully satisfies every
    # pool's nominal credit target regardless of the elective_budget passed
    # in (only the zero-credit-pool top-up pass and the "over-capture" case
    # actually look at elective_budget), so when generate_filled_plan injects
    # a filler pool alongside a major's own already-nominal-sized pool, the
    # two pools' targets simply add up rather than sharing a combined budget.
    # This was already happening before either wiring attempt, just invisible,
    # since TotalCreditsRequirement uses >=, so a few extra credits overall
    # never failed validation. A hard per-level cap is the first constraint
    # sensitive enough to notice it (Computer Science – Bachelor of Science
    # with prior/transfer credits: 210cr/165cr-max at L100; Creative Writing,
    # Bachelor of Arts: 195cr/165cr-max at L100). Fixing that needs changes to
    # _select_electives's pool-budget accounting in search.py, a separate,
    # larger piece of work than this method's own wiring. The ElectiveFiller
    # distribution-awareness from attempt 2 is kept (it's correct and tested
    # on its own, and improves filler quality even without hard enforcement
    # here), but these two node types stay unemitted until that second issue
    # is fixed. See DATA_QUALITY.md's "Level Distribution" section.
    data_is_complete = schedulable_major_credits >= profile.total_credits
    if data_is_complete or force_total_credits:
        _total = override_total_credits if override_total_credits is not None else profile.total_credits
        children.append(TotalCreditsRequirement(_total))

    children.append(major_req)
    return AllOfRequirement(tuple(children))


def filter_requirement_tree(
    node: RequirementNode,
    schedulable_codes: frozenset,
    course_credits: dict[str, int] | None = None,
    keep_open_pools: bool = False,
) -> RequirementNode | None:
    """
    Return a copy of node with unschedulable courses removed and pool credit
    targets capped at what the configured delivery mode can actually provide.

    Two adjustments:
    1. CourseRequirement nodes with no matching offering are dropped.
    2. ChooseCreditsRequirement pool targets are capped at the credits
       available from schedulable pool members, so a pool that can't be
       fully met by distance offerings (e.g. field-work-heavy courses)
       doesn't permanently fail distance plans.

    Composite nodes with no remaining children are dropped; returns None if
    the whole subtree becomes empty.

    `keep_open_pools`: pass True only when validating a complete plan, where
    the open free-elective pool can genuinely be checked against what was
    taken. Generation-time callers (validating an unfilled base plan) should
    leave this False.
    """
    if isinstance(node, CourseRequirement):
        return node if node.course_code in schedulable_codes else None

    if isinstance(node, ChooseCreditsRequirement):
        if node.open_pool and not node.course_codes:
            return node if keep_open_pools else None
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
                child, schedulable_codes, course_credits, keep_open_pools
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
                child, schedulable_codes, course_credits, keep_open_pools
            )) is not None
        ]
        if not children:
            return None
        return AnyOfRequirement(tuple(children))

    # TotalCreditsRequirement, MinLevelCreditsRequirement, MaxLevelCreditsRequirement, etc.
    return node
