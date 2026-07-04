"""
Plan search: selects electives and evaluates degree plans.

The central challenge is elective selection: a student must choose N credits
from a pool of M courses, and we want to find the combination that produces
the most compact, balanced plan.

Previous approach: exhaustive enumeration of all valid combinations via
itertools.product. This is exact but exponential -- C(M, N/15) combinations
per pool, multiplied across pools. With real credit values (e.g. choose 45cr
from 10 courses) the search space is C(10,3) = 120 per pool; with three pools
that is 1.7M combinations before even running the scheduler.

Current approach: greedy minimum-credit selection per pool, with student
preference signals. For each pool we select the fewest courses that meet the
credit requirement, preferring:
  1. Courses the student has indicated a preference for (--prefer flag).
  2. Courses offered in the earliest possible semester (minimises waiting time).
  3. Lower-level courses before higher-level (foundation before specialisation).
  4. Alphabetical by code as a final tiebreaker (determinism).

This is O(M log M) per pool and produces a single candidate plan rather than
enumerating the full search space. It is correct for the vast majority of
cases; the rare scenario where the greedy selection creates an unsatisfiable
prerequisite chain is handled by falling back to an alternative ordering.

The search still iterates over all matching majors when the user provides a
partial name, picking the major whose plan has the best score.
"""

from __future__ import annotations

import dataclasses
import logging
import math
import re
from collections.abc import Iterable

from coursemap.domain.course import Course
from coursemap.domain.plan import DegreePlan
from coursemap.domain.requirement_nodes import (
    ChooseCreditsRequirement,
    RequirementNode,
)
from coursemap.domain.requirement_utils import (
    collect_course_codes,
    collect_course_node_codes as _shared_collect_course_node_codes,
    collect_elective_nodes,
    find_total_credits,
)
from coursemap.domain.prerequisite import (
    CoursePrerequisite as _CoursePrerequisite,
    AndExpression as _AndExpression,
    OrExpression as _OrExpression,
)
from coursemap.domain.prerequisite_utils import prereqs_met
from coursemap.planner.generator import PlanGenerator, _LEVEL_PROGRESSION_GATE
from coursemap.optimisation.scorer import PlanScorer
from coursemap.validation.engine import DegreeValidator
from coursemap.rules.degree_rules import filter_requirement_tree as _frt

logger = logging.getLogger(__name__)

_scorer = PlanScorer()


def _estimate_chain_cost(
    code: str,
    courses: dict,
    already_counted: set[str],
    visited: set[str] | None = None,
) -> int:
    """
    Estimate the additional credits required to satisfy `code`'s prerequisite
    chain, beyond codes already in `already_counted`.

    For OR-prerequisites, picks a branch already in `already_counted` if one
    exists, otherwise the lowest-level branch. May overestimate slightly in
    rare cases; that's the safe direction here, since this feeds a budget
    reservation for required courses rather than a hard limit.
    """
    if visited is None:
        visited = set()
    if code in visited or code not in courses:
        return 0
    visited.add(code)

    course = courses[code]
    prereq = course.prerequisites
    if prereq is None:
        return 0

    def _expr_cost(node) -> int:
        if isinstance(node, _CoursePrerequisite):
            child = node.code
            if child in already_counted or child in visited:
                return 0
            if child not in courses:
                return 0
            return courses[child].credits + _estimate_chain_cost(
                child, courses, already_counted, visited
            )
        if isinstance(node, _AndExpression):
            return sum(_expr_cost(c) for c in node.children)
        if isinstance(node, _OrExpression):
            # Free if any branch is already counted; otherwise cheapest.
            for child in node.children:
                if isinstance(child, _CoursePrerequisite) and child.code in already_counted:
                    return 0
            costs = [_expr_cost(c) for c in node.children]
            return min(costs) if costs else 0
        return 0

    return _expr_cost(prereq)


def _collect_course_node_codes(node: RequirementNode) -> set[str]:
    """
    Collect codes from COURSE requirement nodes only, ignoring pool members.

    Thin wrapper around the shared collect_course_node_codes in
    requirement_utils, kept here so existing call sites in this module don't
    need updating. See requirement_utils.collect_course_node_codes for the
    actual implementation and docstring.
    """
    return _shared_collect_course_node_codes(node)


def _resolve_or_prerequisite(prereq, working_codes: set[str]):
    """
    Collapse an OR-prerequisite to its single resolved branch when exactly
    one branch is present in `working_codes`.

    The working-set builder deliberately includes only one branch of an OR
    prerequisite (to avoid scheduling an unneeded sibling course). Left
    unresolved, the unchosen branch's absence is indistinguishable from a
    genuine external prerequisite (e.g. an admission requirement), which
    would let the OR be satisfied vacuously regardless of whether the chosen
    branch was actually completed. Resolving it here removes that ambiguity.

    Only direct CoursePrerequisite children are resolved; nested expressions
    are left as-is. AndExpression, None, and already-unambiguous
    OrExpressions pass through unchanged.
    """
    if prereq is None:
        return prereq
    if isinstance(prereq, _OrExpression):
        course_children = [c for c in prereq.children if isinstance(c, _CoursePrerequisite)]
        other_children = [c for c in prereq.children if not isinstance(c, _CoursePrerequisite)]
        in_working = [c for c in course_children if c.code in working_codes]
        if len(in_working) == 1 and len(course_children) > 1 and not other_children:
            return in_working[0]
        return prereq
    if isinstance(prereq, _AndExpression):
        new_children = tuple(
            _resolve_or_prerequisite(child, working_codes) for child in prereq.children
        )
        if new_children == prereq.children:
            return prereq
        return _AndExpression(new_children)
    return prereq


def _unreachable_reason(
    course: "Course | None",
    campus: str,
    mode: str,
    no_summer: bool,
) -> str | None:
    """
    Classify why a required course has no offering in the working set, so a
    validation failure can tell the student something actionable instead of
    a bare "missing required course X".

    Returns None if the course has a valid offering for this campus/mode/
    no_summer combination (it isn't this function's job to explain,
    something else dropped it). Otherwise returns a short, human-readable
    reason string.

    Checked in order of specificity: a course can fail more than one of
    these at once (e.g. SS-only AND a different campus), but the message
    should lead with whichever fact is most actionable for the student.
    """
    if course is None:
        return "the course code was not found in the dataset (a data gap, not a scheduling choice)"

    if not course.offerings:
        return "it has no recorded offering at any campus or mode (a data gap, check the course's Massey page)"

    matching_campus_mode = [o for o in course.offerings if o.campus == campus and o.mode == mode]
    if not matching_campus_mode:
        available = sorted({f"{o.campus}/{o.mode}" for o in course.offerings})
        return (
            f"it is not offered as {campus}/{mode}, only {', '.join(available)} "
            f"({'try a different --campus/--mode' if available else 'no offerings recorded'})"
        )

    if no_summer and all(o.semester == "SS" for o in matching_campus_mode):
        return (
            f"it is only offered in Summer School (SS) at {campus}/{mode}, and Summer School "
            f"is disabled (--no-summer). Pass --allow-summer, or take this course over summer"
        )

    return None


def explain_missing_required_codes(
    missing_codes: Iterable[str],
    all_courses: dict[str, "Course"],
    campus: str,
    mode: str,
    no_summer: bool,
) -> list[str]:
    """
    Build one human-readable explanation per missing required course code,
    using _unreachable_reason where it applies and a generic fallback
    otherwise (e.g. the course was schedulable but a prerequisite chain or
    credit cap pushed it out, a real planning conflict, not an offering gap).
    """
    explanations: list[str] = []
    for code in sorted(missing_codes):
        course = all_courses.get(code)
        reason = _unreachable_reason(course, campus, mode, no_summer)
        if reason is None:
            reason = (
                "it was schedulable but didn't fit. Likely a prerequisite chain, "
                "credit cap, or elective-pool conflict elsewhere in the plan"
            )
        explanations.append(f"{code} is missing because {reason}.")
    return explanations


class PlanSearch:
    """
    Selects electives and finds the best valid degree plan for each major.

    Attributes:
        courses:             Full course catalogue.
        majors:              List of major dicts from PlannerService, each containing
                             'name', 'raw', 'requirement', 'degree_tree' fields.
        generator_template:  PlanGenerator instance used as a settings template.
        prior_completed:     Course codes completed before this plan.
        preferred_electives: Course codes the student wants to prioritise.
    """

    def __init__(
        self,
        courses: dict[str, Course],
        majors: list[dict],
        generator_template: PlanGenerator,
        prior_completed: frozenset[str] = frozenset(),
        preferred_electives: frozenset[str] = frozenset(),
        excluded_courses: frozenset[str] = frozenset(),
        allow_level_progression_shortfall: bool = False,
    ):
        self.courses = courses
        self.majors = majors
        self.generator_template = generator_template
        self.prior_completed = prior_completed
        self.preferred_electives = preferred_electives
        self.excluded_courses = excluded_courses
        # When True, a named elective pool that cannot satisfy the 45cr
        # level-progression rule from its own pool members alone is allowed
        # to fall short of its credit target in THIS plan, rather than
        # failing the whole search. Used only by generate_filled_plan's
        # internal discovery pass (see _repair_level_progression and
        # _plan_for_major), the credit shortfall this produces becomes
        # part of the gap that generate_filled_plan's open-pool filler step
        # fills in next, after which the plan is regenerated and validated
        # normally (with this flag off), so a final, returned plan is
        # never silently incomplete; only the discardable discovery pass is.
        self.allow_level_progression_shortfall = allow_level_progression_shortfall
        # Populated by _repair_level_progression when it has to give up on a
        # gate (whether or not allow_shortfall lets it drop the unschedulable
        # selection): {level: shortfall_credits} for the caller, typically
        # generate_filled_plan, to feed into ElectiveFiller's needed_levels
        # so the filler step actually closes the gap instead of papering
        # over it with whatever's cheapest. See PlannerService.last_needed_levels.
        self.last_needed_levels: dict[int, int] = {}
        self.best_generator_stats = None

        # Diagnostics
        self.attempts = 0
        self.failures: dict[str, int] = {}

    def search(self) -> DegreePlan:
        """
        Return the best valid plan found across all candidate majors.

        Raises ValueError if no valid plan can be constructed for any major.
        """
        best_plan: DegreePlan | None = None
        best_score: float | None = None
        best_generator: PlanGenerator | None = None

        for major in self.majors:
            try:
                plan, generator = self._plan_for_major(major)
            except Exception as exc:
                name = major.get("name", "?")
                logger.debug("Major '%s' failed: %s", name, exc)
                self.failures[name] = str(exc)
                continue

            self.attempts += 1
            score = _scorer.score(plan)
            if best_score is None or score < best_score:
                best_plan = plan
                best_score = score
                best_generator = generator

        if best_plan is None:
            detail = "; ".join(
                f"'{k}': {v}" for k, v in list(self.failures.items())[:3]
            )
            raise ValueError(f"No valid plan found. {detail}")

        self.best_generator_stats = best_generator.stats if best_generator else None
        return best_plan

    # ------------------------------------------------------------------
    # Per-major planning
    # ------------------------------------------------------------------

    def _cap_required_codes(
        self,
        required_codes: set[str],
        elective_nodes: list,
        degree_tree: RequirementNode,
        degree_total: int,
        campus: str,
        mode: str,
    ) -> tuple[set[str], bool]:
        """
        Cap `required_codes` at the degree's credit target when the major's
        data over-captures (lists more required courses than the degree
        actually needs. Common when several alternative specialisation
        tracks were scraped as one flat list).

        Codes the degree tree checks as COURSE nodes (`tree_required`) are
        never dropped, including the estimated cost of any prerequisite
        they pull in that isn't itself independently required. Otherwise
        that chain cost goes uncounted here and silently eats into the
        elective pool's budget later. Only genuinely droppable excess
        (non-tree-required codes) is trimmed, by priority: in the degree
        tree, schedulable, lower level, then code for determinism.

        Returns (codes_to_use, was_capped).
        """
        if degree_total <= 0:
            return required_codes, False

        req_total = sum(
            self.courses[c].credits for c in required_codes if c in self.courses
        )
        # Pool contribution this major's electives will actually deliver
        # (DIS-capped at each pool's stated target), so required courses
        # only get budget room the pools can't fill themselves.
        schedulable_pool_contribution = sum(
            min(
                n.credits,
                sum(
                    self.courses[c].credits for c in n.course_codes
                    if c in self.courses
                    and any(o.campus == campus and o.mode == mode
                            for o in self.courses[c].offerings)
                ),
            )
            for n in elective_nodes
        )
        req_budget = (
            max(0, degree_total - schedulable_pool_contribution)
            if req_total + schedulable_pool_contribution > degree_total
            else degree_total
        )
        if req_total <= req_budget:
            return required_codes, False

        tree_required = _collect_course_node_codes(degree_tree)

        def _req_sort(code: str) -> tuple:
            c = self.courses.get(code)
            if c is None:
                return (1, 2, 999, code)
            in_tree = 0 if code in tree_required else 1
            has_matching = any(o.campus == campus and o.mode == mode for o in c.offerings)
            return (in_tree, 0 if has_matching else 1, c.level, code)

        tree_required_in_codes = sorted(
            (c for c in required_codes if c in tree_required), key=_req_sort
        )
        non_tree_required = sorted(
            (c for c in required_codes if c not in tree_required), key=_req_sort
        )

        capped: set[str] = set()
        running = 0
        already_counted: set[str] = set(tree_required_in_codes)
        for code in tree_required_in_codes:
            c = self.courses.get(code)
            if c is None:
                continue
            capped.add(code)
            running += c.credits + _estimate_chain_cost(code, self.courses, already_counted)
        for code in non_tree_required:
            if running >= req_budget:
                break
            c = self.courses.get(code)
            if c is None:
                continue
            capped.add(code)
            running += c.credits

        return capped, True

    def _plan_for_major(self, major: dict) -> tuple[DegreePlan, PlanGenerator]:
        """
        Build and validate a plan for one major.

        Steps:
          1. Collect required course codes (COURSE nodes only, not pool members).
          1b. Cap required codes at the degree credit target, if over-captured.
          2. Select elective courses from each pool using the greedy strategy.
          3. Build the working set (required + selected electives, minus prior).
          4. Check prerequisite feasibility before running the scheduler.
          5. Run the scheduler.
          6. Attach prior-completed course objects to the plan.
          7. Validate against the degree tree.
        """
        degree_tree: RequirementNode = major["degree_tree"]
        major_req: RequirementNode = major["requirement"]
        name: str = major["name"]

        # The 45cr level-progression rule (General Regulations for
        # Undergraduate Degrees, Undergraduate Diplomas, Undergraduate
        # Certificates, Graduate Diplomas, and Graduate Certificates) applies
        # to undergraduate/graduate qualifications (NZQF level <= 7) only.
        # Postgraduate diplomas/certificates/masters (level 8+) are gated by
        # programme admission instead, and routinely include required L300
        # courses with no L200 prerequisite chain at all (e.g. Master of
        # Specialist Teaching). Applying the undergrad rule there produces
        # false unschedulable-major failures. qual_level is None when a
        # major has no qualification match in qualifications.json; default
        # to enforcing the rule in that case (the safer assumption, since
        # most unmatched majors in the dataset are undergraduate).
        qual_level = major.get("qual_level")
        enforce_level_progression = qual_level is None or qual_level <= 7

        # Step 1: separate required (COURSE nodes) from elective pool codes.
        # collect_course_codes returns ALL codes in the tree including pool members.
        # We only schedule pool members that the student actually selects.
        elective_nodes = [
            n for n in collect_elective_nodes(major_req)
            if isinstance(n, ChooseCreditsRequirement)
        ]
        pool_codes: set[str] = {code for n in elective_nodes for code in n.course_codes}
        all_major_codes = collect_course_codes(major_req)
        required_codes = all_major_codes - pool_codes

        # Step 1b: cap required_codes at the degree credit target.
        degree_total = find_total_credits(degree_tree)
        campus = self.generator_template.campus
        mode   = self.generator_template.mode
        required_codes, required_was_capped = self._cap_required_codes(
            required_codes, elective_nodes, degree_tree, degree_total, campus, mode,
        )

        # Step 2: select electives from each pool.
        # Pass the degree credit target so pools with credits=0 (not yet
        # backfilled) can be capped rather than including every pool course.
        #
        # Some pool members also appear as individual COURSE nodes in the
        # requirement tree (a scraping artefact where the same course is
        # listed as both required and elective). Those are always included;
        # only pure-elective pool members (codes that appear only in pools)
        # are subject to the budget cap.
        explicitly_required = _collect_course_node_codes(major_req)
        always_include_in_pool = explicitly_required & pool_codes - required_codes
        pure_elective_pool_codes = pool_codes - explicitly_required

        # Budget for pure-elective selections = degree target minus all
        # definitionally-required credits (required_codes + always_include_in_pool),
        # filtered to courses that will actually be scheduled.
        committed_schedulable = sum(
            self.courses[c].credits
            for c in (required_codes | always_include_in_pool)
            if c in self.courses
            and any(o.campus == campus and o.mode == mode
                    for o in self.courses[c].offerings)
        )
        elective_budget = (
            max(0, degree_total - committed_schedulable)
            if degree_total > 0
            else 0
        )

        # When the major includes an open free-elective pool ("choose any
        # Ncr"), that pool has no fixed course list for _select_electives to
        # draw from. It isn't even included in pure_elective_nodes below
        # (its course_codes is empty). If elective_budget includes the open
        # pool's share, _select_electives' top-up pass has no way to "spend"
        # that share on the open pool, so it spends it on the NAMED pools
        # instead, over-selecting them well past their own stated targets.
        # That produces a plan that reaches the right TOTAL credits but never
        # actually uses any genuine free electives, silently masking the open
        # pool requirement instead of satisfying it.
        #
        # Cap the budget passed to _select_electives at what the named pools
        # can actually need, so the open pool's share is left as a genuine
        # gap. generate_filled_plan picks that gap up afterwards and fills it
        # with real outside-the-major filler courses.
        open_pool_credits = sum(
            n.credits for n in elective_nodes
            if isinstance(n, ChooseCreditsRequirement) and n.open_pool and not n.course_codes
        )
        named_pool_target_sum = sum(
            n.credits for n in elective_nodes
            if not (isinstance(n, ChooseCreditsRequirement) and n.open_pool and not n.course_codes)
        )
        if open_pool_credits > 0:
            elective_budget = min(elective_budget, named_pool_target_sum)


        # Re-filter the degree tree whenever required courses were capped to
        # prevent validation from demanding courses we intentionally dropped.
        # Two cases:
        #   elective_budget == 0: required alone fill the degree; drop all pools.
        #   required_was_capped and elective_budget > 0: required were trimmed to
        #       make room for pools; drop only the trimmed required COURSE nodes.
        if degree_total > 0 and required_was_capped:
            _cc = {c: self.courses[c].credits for c in self.courses}
            if elective_budget == 0:
                # Required fill the whole degree; drop pool validation nodes too.
                _trim = frozenset(
                    c for c in required_codes
                    if c in self.courses
                    and any(o.campus == campus and o.mode == mode
                            for o in self.courses[c].offerings)
                )
            else:
                # Required were trimmed but pools still contribute; keep pool codes.
                _trim = frozenset(
                    c for c in required_codes | pool_codes
                    if c in self.courses
                    and any(o.campus == campus and o.mode == mode
                            for o in self.courses[c].offerings)
                )
            _rebased = _frt(degree_tree, _trim, _cc)
            if _rebased is not None:
                degree_tree = _rebased

        # Build elective node views that include ONLY pure-elective pool codes.
        # always_include_in_pool codes are handled separately and should not
        # consume the elective budget.
        #
        # When elective_budget == 0, the required courses already fill the degree
        # total. Pool selection is suppressed entirely. Adding pools on top would
        # overcredit the plan. The degree tree has already been re-filtered above
        # to remove pool validation nodes in this case.
        pool_credit_scale = 0 if (degree_total > 0 and elective_budget == 0) else 1

        pure_elective_nodes = [
            type(n)(
                credits=n.credits,
                course_codes=tuple(
                    c for c in n.course_codes if c in pure_elective_pool_codes
                ),
            )
            for n in elective_nodes
            if pool_credit_scale > 0 and any(c in pure_elective_pool_codes for c in n.course_codes)
        ]
        elective_codes = self._select_electives(
            pure_elective_nodes, elective_budget, set()
        )
        # Merge always_include_in_pool into elective_codes; they are required
        # but treated as electives by the working set builder.
        elective_codes = elective_codes | always_include_in_pool

        # Cross-pool level-progression repair (see _repair_level_progression):
        # each pool above was selected independently, so the combined set can
        # end up short on L100/L200 credit relative to the L200/L300 credit
        # it also contains, unschedulable in any valid order, not just an
        # ordering the greedy generator happened to pick. Only applies to
        # undergraduate/graduate majors (enforce_level_progression, computed
        # at the top of this method from qual_level).
        if enforce_level_progression:
            already_have = required_codes | elective_codes | frozenset(self.prior_completed)
            repaired = self._repair_level_progression(
                already_have, elective_nodes,
                always_keep=required_codes | always_include_in_pool | frozenset(self.prior_completed),
                degree_total=degree_total,
                allow_shortfall=self.allow_level_progression_shortfall,
            )
            # Only the pool-derived additions/removals are reflected back into
            # elective_codes. required_codes and prior_completed are passed
            # in purely so the repair sees the full picture, not as things it
            # should ever add to or remove from elective_codes itself.
            elective_codes = (repaired - required_codes - frozenset(self.prior_completed)) | always_include_in_pool

        # Step 3: build working set = required + selected electives, minus prior
        working_set = self._build_working_set(
            required_codes, elective_codes, self.prior_completed
        )

        if not working_set:
            campus = self.generator_template.campus
            mode   = self.generator_template.mode
            # Give a specific reason so the CLI can surface a useful message.
            all_codes_count = len(required_codes | elective_codes)
            if all_codes_count == 0:
                if self.allow_level_progression_shortfall:
                    # This is generate_filled_plan's discovery pass, and
                    # _repair_level_progression's allow_shortfall path
                    # dropped every pool selection it had (e.g. Finance –
                    # Bachelor of Business: ALL of its named-pool courses
                    # are L200/L300 with zero L100 members at all, so the
                    # L200 gate itself can never be satisfied from the
                    # named pools, and the cascade drops everything). A
                    # required_codes-only major (none here) would still
                    # have something to schedule; an all-pool, all-blocked
                    # major like this one genuinely has nothing yet, which
                    # is a valid, if extreme, discovery-pass outcome: it
                    # just means the WHOLE degree_total becomes the gap for
                    # generate_filled_plan's filler step to cover, starting
                    # from open-pool L100 courses. Return an empty-but-valid
                    # plan rather than raising; the caller computes the gap
                    # from base_plan.total_credits(), which correctly comes
                    # out as 0 here, and the real (non-discovery) re-run
                    # afterward validates at full strictness as normal.
                    empty_plan = DegreePlan(
                        semesters=(), prior_completed=tuple(
                            self.courses[c] for c in self.prior_completed if c in self.courses
                        ),
                    )
                    empty_generator = PlanGenerator(
                        {}, campus=campus, mode=mode,
                        no_summer=self.generator_template.no_summer,
                    )
                    return empty_plan, empty_generator
                raise ValueError(
                    "No courses left to schedule after excluding prior-completed."
                )
            # Build a helpful list of valid campus/mode combos for this major
            valid_combos: list[str] = []
            all_course_codes = required_codes | elective_codes
            combo_counts: dict[tuple[str,str], int] = {}
            for code in all_course_codes:
                c = self.generator_template.courses.get(code)
                if c and c.offerings:
                    for o in c.offerings:
                        key = (o.campus, o.mode)
                        combo_counts[key] = combo_counts.get(key, 0) + 1
            if combo_counts:
                # Sort by how many courses are available in that combo (desc)
                sorted_combos = sorted(combo_counts.items(), key=lambda x: -x[1])
                valid_combos = [f"{cp}/{mo}" for (cp, mo), _ in sorted_combos[:4]]

            hint = (
                f" Valid combinations for this major: {', '.join(valid_combos)}."
                if valid_combos
                else " Try --campus D --mode DIS for distance, or --campus M --mode INT for Manawatū."
            )
            raise ValueError(
                f"No courses left to schedule: all {all_codes_count} major course(s) lack "
                f"a {campus}/{mode} offering.{hint}"
            )

        # Step 4: check prerequisite feasibility before running the scheduler
        if not self._prereqs_feasible(working_set):
            raise ValueError(
                "Selected courses contain an unsatisfiable prerequisite chain."
            )

        # Step 5: run scheduler
        working_credits = sum(c.credits for c in working_set.values())
        # Effective per-semester credit capacity: the lesser of the credit cap
        # and what max_courses_per_semester can deliver. When max_courses=2 and
        # all courses are 15cr, each semester holds at most 30cr, not 60cr.
        _max_courses = self.generator_template.max_courses
        if _max_courses is not None:
            _min_cr = min((c.credits for c in working_set.values() if c.credits > 0), default=15)
            _effective_cap = min(self.generator_template.max_credits, _max_courses * _min_cr)
        else:
            _effective_cap = self.generator_template.max_credits
        min_sems = math.ceil(working_credits / max(1, _effective_cap))
        # Safety multiplier: allow 2.5x the theoretical minimum, but at least 16
        # semesters (8 years) and at most 32 (16 years, an absolute ceiling).
        # The old flat 24 was too small for some postgrad programmes (e.g. 480cr PhDs)
        # and too large a safety net for short diplomas (e.g. 120cr PGCert).
        dynamic_max_semesters = max(16, min(32, math.ceil(min_sems * 2.5)))

        required_zero_credit_codes = frozenset(
            code for code in required_codes
            if code in working_set and working_set[code].credits == 0
        )

        generator = PlanGenerator(
            working_set,
            max_credits_per_semester=self.generator_template.max_credits,
            max_courses_per_semester=self.generator_template.max_courses,
            campus=self.generator_template.campus,
            mode=self.generator_template.mode,
            start_year=self.generator_template.start_year,
            start_semester=self.generator_template.start_semester,
            prior_completed=self.prior_completed,
            max_semesters=dynamic_max_semesters,
            no_summer=self.generator_template.no_summer,
            required_zero_credit_codes=required_zero_credit_codes,
            enforce_level_progression=enforce_level_progression,
        )
        # Propagate filler_codes from the template so the generator's sort key
        # schedules required courses before filler electives. Without this the
        # filler_codes frozenset on the template is set but ignored by the new
        # generator instance that actually runs generate().
        generator.filler_codes = getattr(self.generator_template, "filler_codes", frozenset())
        plan = generator.generate()

        # Step 6: attach prior-completed course objects using the full catalogue
        if self.prior_completed:
            prior_objects = tuple(
                self.courses[code]
                for code in self.prior_completed
                if code in self.courses
            )
            # Reconstruct the plan so __post_init__ recomputes all_course_codes
            # with the prior_completed codes included. Mutating prior_completed
            # directly would leave all_course_codes stale (it is now computed
            # eagerly at construction time, not via cached_property).
            plan = type(plan)(
                semesters=plan.semesters,
                prior_completed=prior_objects,
                transfer_credits=plan.transfer_credits,
            )

        # Step 7: validate. Skip only the specific COURSE nodes for codes the
        # student deliberately excluded. The user was warned before generation;
        # we still show the plan but note the unsatisfied requirements.
        validator = DegreeValidator(degree_tree)
        result = validator.validate(plan)
        if not result.passed:
            # If every validation error is a "Missing required course X" where
            # X was explicitly excluded by the student, downgrade to a warning
            # instead of failing entirely. This lets the plan be shown.
            excluded_missing = [
                e for e in result.errors
                if e.startswith("Missing required course ")
                and e.split()[-1].rstrip(".") in self.excluded_courses
            ]
            # When this is generate_filled_plan's discovery pass
            # (allow_level_progression_shortfall=True), _repair_level_progression
            # may have deliberately left a named pool short of its own target
            # rather than deadlocking the generator (see that function's
            # allow_shortfall parameter). Tolerate exactly that error shape,
            # not ANY elective-pool shortfall, only ones this same pass
            # explicitly chose to allow, since the caller (generate_filled_plan)
            # is about to recompute and recover the resulting larger gap via
            # its own filler step, then regenerate and fully revalidate with
            # this flag off. A plan returned to any OTHER caller always goes
            # through this validation at full strictness.
            pool_shortfall = (
                [
                    e for e in result.errors
                    if e.startswith("Elective pool: have ") and "cr, need " in e
                ]
                if self.allow_level_progression_shortfall
                else []
            )
            non_excl_errors = [
                e for e in result.errors
                if e not in excluded_missing and e not in pool_shortfall
            ]
            if non_excl_errors:
                # "Missing required course X." errors are common but unhelpful on
                # their own. They don't say *why* X never made it into the plan.
                # Swap each one for an explanation (no campus/mode offering,
                # SS-only while --no-summer is set, or a genuine scheduling
                # conflict) so the student knows what to actually do about it.
                missing_codes = [
                    e.split()[-1].rstrip(".")
                    for e in non_excl_errors
                    if e.startswith("Missing required course ")
                ]
                other_errors = [
                    e for e in non_excl_errors
                    if not e.startswith("Missing required course ")
                ]
                explained = explain_missing_required_codes(
                    missing_codes,
                    self.courses,
                    self.generator_template.campus,
                    self.generator_template.mode,
                    self.generator_template.no_summer,
                ) if missing_codes else []
                raise ValueError(
                    f"Plan for '{name}' failed degree validation: "
                    f"{'; '.join(explained + other_errors)}"
                )
            # All errors are tolerated ones (student-excluded required courses,
            # and/or, only when allow_level_progression_shortfall, named pool
            # shortfalls deliberately left by _repair_level_progression's
            # allow_shortfall path). Log and continue.
            if excluded_missing:
                logger.debug(
                    "Plan for '%s' is missing %d excluded required course(s): %s",
                    name,
                    len(excluded_missing),
                    ", ".join(e.split()[-1].rstrip(".") for e in excluded_missing),
                )
            if pool_shortfall:
                logger.debug(
                    "Plan for '%s' has %d named elective pool(s) short of "
                    "their own target (tolerated: discovery pass for "
                    "generate_filled_plan, expected to be recovered by the "
                    "filler step): %s",
                    name, len(pool_shortfall), "; ".join(pool_shortfall),
                )

        # Trim plan to degree_total credits.
        # The working-set prereq expansion may add more courses than needed.
        # Remove lowest-priority courses to bring total to degree_total.
        if degree_total > 0:
            plan_total = plan.total_credits() + plan.prior_credits() + plan.transfer_credits
            if plan_total > degree_total:
                excess = plan_total - degree_total
                # Identify prereqs needed by other plan courses
                plan_codes = {c.code for s in plan.semesters for c in s.courses}
                prereqs_needed: set[str] = set()
                from coursemap.domain.prerequisite import (
                    CoursePrerequisite as _CP3,
                    AndExpression as _AND3,
                    OrExpression as _OR3,
                )
                for s in plan.semesters:
                    for c in s.courses:
                        if c.prerequisites is None:
                            continue
                        stack = [c.prerequisites]
                        while stack:
                            n = stack.pop()
                            if isinstance(n, _CP3) and n.code in plan_codes:
                                prereqs_needed.add(n.code)
                            elif isinstance(n, (_AND3, _OR3)):
                                stack.extend(n.children)
                # Remove non-required, non-preferred, non-tree courses first
                # Protect required, always-include, and direct prereqs of non-elective courses.
                # Pool courses (elective_codes) are optionally removable if they're
                # not in always_include_in_pool, since the pool offers alternatives.
                non_elective_needed: set[str] = set()
                from coursemap.domain.prerequisite import (
                    CoursePrerequisite as _CPt,
                    AndExpression as _ANDt,
                    OrExpression as _ORt,
                )
                for s in plan.semesters:
                    for c in s.courses:
                        if c.code in elective_codes and c.code not in always_include_in_pool:
                            continue  # pool courses don't protect their own prereqs in trim
                        if c.prerequisites is None:
                            continue
                        stk = [c.prerequisites]
                        while stk:
                            n = stk.pop()
                            if isinstance(n, _CPt) and n.code in plan_codes:
                                non_elective_needed.add(n.code)
                            elif isinstance(n, (_ANDt, _ORt)):
                                stk.extend(n.children)

                protected_trim = (required_codes | always_include_in_pool | non_elective_needed)
                # Pool courses are removable (from end of pool, higher-level first)
                removable_pool = sorted(
                    [c for s in plan.semesters for c in s.courses
                     if c.code in elective_codes
                     and c.code not in protected_trim
                     and c.code not in self.preferred_electives],
                    key=lambda c: (-c.level, c.code),
                )
                # Non-pool extras (prerequisite-chain courses pulled in only
                # because some other plan course needs them).
                removable_extras = sorted(
                    [c for s in plan.semesters for c in s.courses
                     if c.code not in protected_trim
                     and c.code not in elective_codes
                     and c.code not in self.preferred_electives],
                    key=lambda c: (-c.level, c.code),
                )
                removed: set[str] = set()
                remaining_excess = excess
                # Pass 1: remove pool courses first (they have alternates,
                # so they're the right place to look for excess before
                # touching prerequisite-chain extras).
                for candidate in removable_pool:
                    if remaining_excess <= 0:
                        break
                    if candidate.code not in removed:
                        removed.add(candidate.code)
                        remaining_excess -= candidate.credits
                # Pass 2: recompute what's still needed from the SURVIVING
                # plan (pool removals already applied) before deciding which
                # extras to cut. An extra needed only by a pool course that
                # was itself just removed is correctly still removable; an
                # extra needed by a surviving pool course is now protected,
                # non_elective_needed (computed before any removal) can't
                # tell this on its own, since it skips pool courses entirely.
                removable_extra_codes = {ex.code for ex in removable_extras}
                surviving_needed: set[str] = set()
                for s in plan.semesters:
                    for c in s.courses:
                        if c.code in removed or c.prerequisites is None:
                            continue
                        stk = [c.prerequisites]
                        while stk:
                            node = stk.pop()
                            if isinstance(node, _CPt) and node.code in removable_extra_codes:
                                surviving_needed.add(node.code)
                            elif isinstance(node, (_ANDt, _ORt)):
                                stk.extend(node.children)
                for candidate in removable_extras:
                    if remaining_excess <= 0:
                        break
                    if candidate.code in removed or candidate.code in surviving_needed:
                        continue
                    removed.add(candidate.code)
                    remaining_excess -= candidate.credits
                if removed:
                    from coursemap.domain.plan import SemesterPlan
                    new_sems = []
                    for sem in plan.semesters:
                        new_courses = [c for c in sem.courses if c.code not in removed]
                        if new_courses:
                            new_sems.append(SemesterPlan(
                                year=sem.year,
                                semester=sem.semester,
                                courses=tuple(new_courses),
                            ))
                    plan = type(plan)(
                        semesters=tuple(new_sems),
                        prior_completed=plan.prior_completed,
                        transfer_credits=plan.transfer_credits,
                    )

        logger.info(
            "Major '%s': %d semesters, %d credits",
            name, len(plan.semesters), plan.total_credits() + plan.prior_credits(),
        )
        return plan, generator

    # ------------------------------------------------------------------
    # Elective selection (greedy)
    # ------------------------------------------------------------------

    def _select_electives(
        self,
        elective_nodes: list[ChooseCreditsRequirement],
        elective_budget: int = 0,
        always_include: set[str] | None = None,
    ) -> set[str]:
        """
        Choose courses from elective pools using a greedy, delivery-mode-aware strategy.

        Selection prioritises courses that are schedulable in the configured campus/mode.
        Credit targets are satisfied using schedulable credits only. Non-schedulable
        courses will be dropped by _build_working_set, so counting them toward a credit
        target produces plans that fail validation. Non-schedulable courses are still
        included as a fallback when a pool cannot be satisfied by schedulable courses
        alone, but they are never counted toward the credit target.

        always_include: codes that appear as COURSE nodes AND pool members; always
        scheduled regardless of budget since the validation tree requires them directly.

        For pools with credits > 0: select the minimum schedulable courses meeting the
        credit target, preferring always_include codes then elective_sort_key order.
        Each pool's effective target is further capped by the remaining elective_budget
        so that when required courses already consume the full degree total, no pool
        courses are added (prevents overcrediting from scraped data that over-captures
        required courses for a given degree).

        For pools with credits == 0: use elective_budget to cap selection across pools.
        When elective_budget == 0, include all pool courses (no credit target known).

        Top-up: when all pools have credits > 0 but their targets sum to less than
        elective_budget, continue selecting from pools to meet the degree total.
        """
        if always_include is None:
            always_include = set()

        campus = self.generator_template.campus
        mode   = self.generator_template.mode

        def is_schedulable(code: str) -> bool:
            if code in self.excluded_courses:
                return False
            c = self.courses.get(code)
            return c is not None and any(
                o.campus == campus and o.mode == mode for o in c.offerings
            )

        selected: set[str] = set()
        zero_credit_nodes = [n for n in elective_nodes if n.credits <= 0]
        known_credit_nodes = [n for n in elective_nodes if n.credits > 0]

        # Pre-load always_include codes (required by COURSE nodes too).
        # They count toward the budget only if schedulable.
        always_credits = sum(
            self.courses[c].credits for c in always_include
            if c in self.courses and is_schedulable(c)
        )
        if elective_budget <= 0 or always_credits <= elective_budget:
            selected.update(always_include)
            force_include: set[str] = set()
        else:
            force_include = set(always_include)

        def _sort_key(code: str) -> tuple:
            """Force-include first, schedulable second, then elective_sort_key order."""
            return (
                0 if code in force_include else 1,
                0 if is_schedulable(code) else 1,
            ) + self._elective_sort_key(code)

        # ----------------------------------------------------------------
        # Pass 1: pools with known credit targets.
        # Count only schedulable credits toward the target; non-schedulable
        # courses are only added as a last resort when the schedulable subset
        # is insufficient.
        #
        # Each pool's effective credit target is capped by the remaining
        # elective_budget so that when required courses already consume the
        # full degree total, no additional pool courses are selected.
        # ----------------------------------------------------------------

        def _sched_credits(codes: Iterable[str]) -> int:
            return sum(
                self.courses[c].credits for c in codes
                if c in self.courses and is_schedulable(c)
            )

        # Schedulable credits already committed (always_include pre-loaded above).
        committed_sched = _sched_credits(selected)

        for node in known_credit_nodes:
            # Effective target = pool's own credit requirement.
            effective_target = node.credits

            # Credits already in `selected` from this pool (schedulable only).
            accumulated_sched = _sched_credits(
                c for c in node.course_codes if c in selected
            )
            if accumulated_sched >= effective_target:
                continue

            # Part I/II pair detection: before greedy sweep, check whether any
            # pair of courses that are explicitly "Part I" + "Part II" of the same
            # title meets the credit target. If so, prefer that pair, it avoids
            # mixing parts from different thesis tracks (e.g. taking the 90cr thesis
            # Part I alongside the 120cr thesis Part I, which is nonsensical).
            #
            # Approach: build (part1, part2) groups from title matching, compute
            # combined schedulable credits, pick the group with minimum overshoot
            # that meets the target. If no pair group qualifies, fall through to
            # the standard greedy loop.
            remaining_needed = effective_target - accumulated_sched
            best_group: list[str] | None = None
            best_overshoot = float("inf")

            _part1_re = re.compile(r"\bPart\s*I\b(?!I)", re.IGNORECASE)
            _part2_re = re.compile(r"\bPart\s*II\b", re.IGNORECASE)

            unselected_sched = [
                c for c in node.course_codes
                if c not in selected and c in self.courses and is_schedulable(c)
            ]
            part1_candidates = [c for c in unselected_sched
                                 if _part1_re.search(self.courses[c].title)]
            for p1 in part1_candidates:
                cr1 = self.courses[p1].credits
                # Find a Part II in the same pool with the same credit value.
                p2_match = next(
                    (c for c in unselected_sched
                     if c != p1
                     and self.courses[c].credits == cr1
                     and _part2_re.search(self.courses[c].title)),
                    None,
                )
                if p2_match is None:
                    continue
                pair_credits = cr1 * 2
                if pair_credits >= remaining_needed and remaining_needed > 0:
                    overshoot = pair_credits - remaining_needed
                    if overshoot < best_overshoot:
                        best_overshoot = overshoot
                        best_group = [p1, p2_match]

            if best_group is not None:
                for code in best_group:
                    selected.add(code)
                    if is_schedulable(code):
                        accumulated_sched += self.courses[code].credits
            else:
                sorted_codes = sorted(node.course_codes, key=_sort_key)
                for code in sorted_codes:
                    if accumulated_sched >= effective_target:
                        break
                    if code in selected:
                        continue
                    course = self.courses.get(code)
                    if course is None:
                        continue
                    selected.add(code)
                    if is_schedulable(code):
                        accumulated_sched += course.credits

            if accumulated_sched < effective_target and effective_target > 0:
                # Not enough schedulable courses. Include everything and let
                # filter_requirement_tree cap the validation target.
                logger.debug(
                    "Elective pool needs %dcr (effective %dcr) but only %dcr schedulable "
                    "in %s/%s; including all pool courses.",
                    node.credits, effective_target, accumulated_sched, campus, mode,
                )
                selected.update(
                    c for c in node.course_codes if c in self.courses
                )

            # Update committed_sched so the next pool sees the correct remaining budget.
            committed_sched = _sched_credits(selected)

        # ----------------------------------------------------------------
        # Top-up pass: when all pools have credits > 0 but their targets
        # sum to less than elective_budget (e.g. a 120cr GradDip with a
        # single 60cr pool), keep selecting to reach the degree total.
        #
        # When pool_target_sum > elective_budget the pool has been
        # over-captured (scraped more courses than the degree needs).
        # In that case cap at pool_target_sum to prevent runaway selection.
        # Otherwise use elective_budget as usual.
        # ----------------------------------------------------------------
        if not zero_credit_nodes and elective_budget > 0:
            pool_target_sum = sum(n.credits for n in known_credit_nodes)
            sched_selected = sum(
                self.courses[c].credits
                for c in selected
                if c in self.courses and is_schedulable(c)
            )
            # Only cap at pool_target_sum when the pools over-specify (more
            # pool courses exist than the degree target allows).
            if pool_target_sum > elective_budget:
                topup_cap = pool_target_sum
            else:
                topup_cap = elective_budget
            remaining = topup_cap - sched_selected
            if remaining > 0:
                for node in known_credit_nodes:
                    for code in sorted(node.course_codes, key=_sort_key):
                        if remaining <= 0:
                            break
                        if code in selected:
                            continue
                        course = self.courses.get(code)
                        if course is None or not is_schedulable(code):
                            continue
                        selected.add(code)
                        remaining -= course.credits
                    if remaining <= 0:
                        break

        if not zero_credit_nodes:
            return selected

        # ----------------------------------------------------------------
        # Pass 2: pools with credits == 0 (not yet backfilled).
        # Use elective_budget to cap; distribute across pools greedily.
        # ----------------------------------------------------------------
        committed_sched = sum(
            self.courses[c].credits
            for c in selected
            if c in self.courses and is_schedulable(c)
        )
        remaining_budget = max(0, elective_budget - committed_sched) if elective_budget > 0 else 0

        if remaining_budget > 0 and zero_credit_nodes:
            schedulable_per_pool: list[list[str]] = []
            for node in zero_credit_nodes:
                sched = sorted(
                    (
                        c for c in node.course_codes
                        if c in self.courses and is_schedulable(c)
                    ),
                    key=lambda c: (0 if c in force_include else 1,) + self._elective_sort_key(c),
                )
                schedulable_per_pool.append(sched)

            budget_used = 0
            pool_idx: list[int] = [0] * len(zero_credit_nodes)
            changed = True
            while changed and budget_used < remaining_budget:
                changed = False
                for pi, schedulable in enumerate(schedulable_per_pool):
                    while pool_idx[pi] < len(schedulable):
                        code = schedulable[pool_idx[pi]]
                        pool_idx[pi] += 1
                        if code in selected:
                            continue
                        cr = self.courses[code].credits
                        if budget_used + cr > remaining_budget:
                            continue
                        selected.add(code)
                        budget_used += cr
                        changed = True
                        break

            # Overshoot: close any remaining gap with the smallest schedulable course.
            if budget_used < remaining_budget:
                candidates = [
                    (self.courses[c].credits, c)
                    for pool in schedulable_per_pool
                    for c in pool
                    if c not in selected and c in self.courses
                ]
                if candidates:
                    candidates.sort()
                    selected.add(candidates[0][1])

        elif elective_budget == 0:
            for node in zero_credit_nodes:
                selected.update(c for c in node.course_codes if c in self.courses)

        return selected

    def _repair_level_progression(
        self,
        selected_codes: frozenset[str],
        elective_nodes: list[ChooseCreditsRequirement],
        always_keep: frozenset[str],
        degree_total: int,
        allow_shortfall: bool = False,
    ) -> frozenset[str]:
        """
        Cross-pool repair for the 45cr level-progression rule (see
        _LEVEL_PROGRESSION_GATE in coursemap.planner.generator).

        _select_electives processes each elective pool independently, so it
        has no way to know that pool A's L300 selections need pool B's L200
        selections to reach 45cr first. Each pool just picks its own
        cheapest valid subset. The result can be a selected set that is
        mathematically unschedulable in ANY order: not enough L100/L200
        credit anywhere in the set to legally unlock the L200/L300 credit
        that's also in the set (confirmed against real majors: Ecology and
        Conservation, Psychology, see DATA_QUALITY.md).

        IMPORTANT: a course's pool membership is specific. A course only
        counts toward the credit target of pools that actually list it, so
        a swap can only ever trade one course for ANOTHER COURSE IN THE SAME
        POOL. Pulling in an L200 course from an unrelated pool to "cover"
        another pool's L300 shortfall would silently break that other
        pool's own target instead of fixing anything (caught via
        test_filled_plan_reaches_degree_target[English...] during
        development. The first, pool-blind version of this function did
        exactly that). The cumulative level-credit shortfall is checked
        across the whole selected set (since that's what the gate actually
        enforces), but every repair swap is scoped to a single pool, and
        only proceeds if that pool can supply both sides of the trade.

        allow_shortfall: if no in-pool swap exists and this is True, the
        unschedulable higher-level selections for the affected pool(s) are
        DROPPED rather than left in place (which would deadlock the
        generator outright). This leaves the named pool short of its own
        credit target. The caller is expected to tolerate exactly that
        specific validation error and recover the shortfall elsewhere (see
        generate_filled_plan, the only caller that sets this). Default
        False preserves the original strict behaviour for ordinary,
        single-pass plan generation: an unfixable shortfall is left as-is
        and surfaces as a deadlock the normal way.

        If no in-pool swap exists anywhere that improves the shortfall:
          - allow_shortfall=False (default): the set is returned unchanged
            that genuinely means the major cannot be completed from its
            required + pool courses alone in a single pass (e.g. Chinese –
            Bachelor of Arts, where the required course list only reaches
            30cr at L200 with no pool path to the missing 15cr, full stop,
            no open pool exists there either, so there's nothing
            generate_filled_plan could supply afterward anyway). Surfaces
            as a clear scheduling error.
          - allow_shortfall=True: the unschedulable higher-level selections
            are dropped from the set instead, leaving the affected pool(s)
            short of their own credit target in this pass.

        always_keep: required (non-pool) codes and always-include codes,
        never removed by the swap (or the allow_shortfall drop), even if
        they're high-level.
        """
        selected = set(selected_codes)
        campus = self.generator_template.campus
        mode   = self.generator_template.mode

        def is_schedulable(code: str) -> bool:
            if code in self.excluded_courses:
                return False
            c = self.courses.get(code)
            return c is not None and any(
                o.campus == campus and o.mode == mode for o in c.offerings
            )

        def _total_shortfall(level_credits: dict[int, int]) -> int:
            """
            Sum of unsatisfied credit across every gate, given a level credit
            map. Used to ensure a swap makes real forward progress rather than
            trading one gate's shortfall for another's (the Psychology
            oscillation found during development: L100<->L200 swapped back
            and forth forever, each swap satisfying one gate while exactly
            re-breaking the other, since Psychology's pool requires L200
            credit to come from the same 45cr budget as its L100 credit and
            satisfying the L300-needs-L200 gate and the L200-needs-L100 gate
            simultaneously needs MORE total pool credit than the pool's own
            target allows, confirmed mathematically unsolvable earlier this
            audit). A swap is only accepted if it strictly reduces this total;
            otherwise it's not real progress and must be rejected, leaving
            the loop to fall through to the allow_shortfall drop path (or
            the hard-stop) instead of cycling forever.
            """
            total = 0
            for gated_level, (required, gate_level) in _LEVEL_PROGRESSION_GATE.items():
                if level_credits.get(gated_level, 0) <= 0:
                    continue
                have = level_credits.get(gate_level, 0)
                if have < required:
                    total += required - have
            return total

        for _ in range(12):  # bounded: a handful of swaps/drops across all pools+gate levels
            level_credits: dict[int, int] = {}
            for code in selected:
                c = self.courses.get(code)
                if c is not None and is_schedulable(code):
                    level_credits[c.level] = level_credits.get(c.level, 0) + c.credits
            shortfall_before = _total_shortfall(level_credits)

            # Find the lowest gated level that's short, so repairs happen
            # bottom-up (fixing L200 first can also help L300 next pass).
            shortfall_level: int | None = None
            shortfall_gate_level: int | None = None
            shortfall_amount = 0
            for gated_level in sorted(_LEVEL_PROGRESSION_GATE):
                required, gate_level = _LEVEL_PROGRESSION_GATE[gated_level]
                if level_credits.get(gated_level, 0) <= 0:
                    continue  # nothing selected at this level, no gate to satisfy
                have = level_credits.get(gate_level, 0)
                if have < required:
                    shortfall_level = gated_level
                    shortfall_gate_level = gate_level
                    shortfall_amount = required - have
                    break

            if shortfall_level is None:
                break  # all gates satisfied (or nothing to gate)

            # Try each pool that contains an unselected course at
            # shortfall_gate_level as the source of a same-pool swap. A pool
            # only qualifies if removing the chosen higher-level course and
            # adding the lower-level one leaves THAT POOL's own schedulable
            # credit total at or above its own target.
            swapped = False
            for node in elective_nodes:
                if node.credits <= 0:
                    continue  # only known-target pools can be safely rebalanced

                pool_codes = set(node.course_codes)
                add_candidates = sorted(
                    (
                        c for c in pool_codes
                        if c not in selected
                        and c in self.courses
                        and self.courses[c].level == shortfall_gate_level
                        and is_schedulable(c)
                    ),
                    key=lambda c: self.courses[c].credits,
                )
                if not add_candidates:
                    continue

                pool_selected_credit = sum(
                    self.courses[c].credits for c in pool_codes
                    if c in selected and c in self.courses and is_schedulable(c)
                )

                # A safe removal candidate is any already-selected, non-kept
                # course in this pool that is NOT at shortfall_gate_level
                # (removing more of the level we're trying to add more of
                # would be self-defeating). It doesn't have to be at
                # shortfall_level specifically, e.g. Psychology's 45cr pool
                # mixes L100 and L200 courses with no L300 member at all, so
                # the only valid swap is L100-out/L200-in within that one
                # pool, never touching the separate L300 pool. Prefer
                # removing the highest-level candidate first, since pools are
                # typically structured low-to-high and the top of the range
                # already selected is the most replaceable without affecting
                # a different gate.
                remove_candidates = sorted(
                    (
                        c for c in pool_codes
                        if c in selected
                        and c not in always_keep
                        and c in self.courses
                        and self.courses[c].level != shortfall_gate_level
                    ),
                    key=lambda c: (-self.courses[c].level, -self.courses[c].credits),
                )
                if not remove_candidates:
                    # Nothing in this pool can be safely dropped. Adding
                    # without a same-pool removal would grow this pool past
                    # its own credit target, which silently breaks downstream
                    # gap/budget accounting that assumes each pool stays at
                    # its target (see test_filled_plan_reaches_degree_target
                    # regression hit during development: an earlier version
                    # of this swap allowed pools to overshoot, which threw
                    # off generate_filled_plan's gap calculation by exactly
                    # the overshoot amount). Try the next pool instead.
                    continue

                for add_code in add_candidates:
                    add_credits = self.courses[add_code].credits
                    for drop_code in remove_candidates:
                        drop_credits = self.courses[drop_code].credits
                        new_pool_total = pool_selected_credit + add_credits - drop_credits
                        if new_pool_total < node.credits:
                            continue  # this pool's own target would break

                        # Tentatively apply the swap and check it actually
                        # makes net progress across ALL gates, not just the
                        # one we were targeting, otherwise this can oscillate
                        # forever (Psychology: L100<->L200 swap each fixing
                        # one gate while re-breaking the other, found during
                        # development). Reject and try the next candidate if
                        # the total shortfall doesn't strictly improve.
                        tentative_level_credits = dict(level_credits)
                        tentative_level_credits[self.courses[drop_code].level] = (
                            tentative_level_credits.get(self.courses[drop_code].level, 0)
                            - drop_credits
                        )
                        tentative_level_credits[shortfall_gate_level] = (
                            tentative_level_credits.get(shortfall_gate_level, 0)
                            + add_credits
                        )
                        if _total_shortfall(tentative_level_credits) >= shortfall_before:
                            continue  # no net progress, try the next candidate

                        selected.discard(drop_code)
                        selected.add(add_code)
                        logger.debug(
                            "Level-progression repair (pool target %dcr): "
                            "swapped out %s (L%d) for %s (L%d) to cover "
                            "%dcr shortfall at L%d.",
                            node.credits, drop_code, self.courses[drop_code].level,
                            add_code, shortfall_gate_level,
                            shortfall_amount, shortfall_gate_level,
                        )
                        swapped = True
                        break
                    if swapped:
                        break
                if swapped:
                    break

            if not swapped:
                # Record this gate's shortfall regardless of allow_shortfall.
                # generate_filled_plan reads self.last_needed_levels after its
                # discovery-pass call (the one that actually sets
                # allow_shortfall=True) to tell ElectiveFiller's filler step
                # which level to specifically prioritise, so the gap it fills
                # actually closes the gate instead of just hitting the right
                # credit TOTAL with the wrong levels (the bug this whole
                # mechanism exists to fix. See CHANGELOG.md, "ElectiveFiller
                # Level-Gate Awareness"). Accumulate rather than overwrite,
                # in case multiple gates are short across repair iterations.
                self.last_needed_levels[shortfall_gate_level] = (
                    self.last_needed_levels.get(shortfall_gate_level, 0) + shortfall_amount
                )
                if allow_shortfall:
                    # Drop every droppable (not in always_keep) selection at
                    # shortfall_level, across every pool, not just the pool
                    # this iteration happened to be examining, since the
                    # gate is checked against the cumulative credit total
                    # across the WHOLE selected set, not per-pool. Leaving
                    # any of them in place would still deadlock the
                    # generator (it gates on the same cumulative total).
                    dropped = {
                        c for c in selected
                        if c not in always_keep
                        and c in self.courses
                        and self.courses[c].level == shortfall_level
                    }
                    if dropped:
                        selected -= dropped
                        logger.debug(
                            "Level-progression repair (allow_shortfall): no "
                            "in-pool swap available to cover a %dcr shortfall "
                            "at L%d, dropped %d unschedulable L%d "
                            "selection(s) instead: %s. The pool(s) they came "
                            "from will report short of their own credit "
                            "target; generate_filled_plan is expected to "
                            "recover the resulting larger gap via its filler "
                            "step, then regenerate and fully revalidate.",
                            shortfall_amount, shortfall_gate_level,
                            len(dropped), shortfall_level, sorted(dropped),
                        )
                        continue  # re-check from the top, dropping L300 might also fix an L200-vs-L100 shortfall
                    # Nothing droppable either (everything's in always_keep).
                    # fall through to the same hard-stop as the non-shortfall
                    # case; allow_shortfall can't help if there's truly
                    # nothing to drop or swap.
                logger.debug(
                    "Level-progression repair: no in-pool swap available to "
                    "cover a %dcr shortfall at L%d; major may be genuinely "
                    "unsolvable from its named pools alone. (An open/free-"
                    "elective pool, if present, is deliberately NOT used as "
                    "a fallback source here, confirmed via Finance "
                    "Bachelor of Business during development that doing so "
                    "breaks generate_filled_plan's two-pass architecture: "
                    "open-pool additions made during the base-plan repair "
                    "aren't tracked in major_pool_codes, so the base-plan "
                    "and filled-plan passes can independently make different "
                    "repair choices and net out short of the degree total.)",
                    shortfall_amount, shortfall_gate_level,
                )
                break

        return frozenset(selected)

    def _elective_sort_key(self, code: str) -> tuple:
        """
        Sort key for greedy elective selection. Lower = more preferred.

        Priority (ascending, so lowest wins):
          0. Not preferred (1) vs preferred (0)  -- student preferences first
          1. Earliest semester offered (S1=0, S2=1, SS=2, none=3)
          2. Course level (100 before 200 before 300)
          3. Course code (alphabetical, for determinism)
        """
        preferred = 0 if code in self.preferred_electives else 1

        course = self.courses.get(code)
        if course is None:
            return (preferred, 3, 999, code)

        campus = self.generator_template.campus
        mode   = self.generator_template.mode
        sem_order = {"S1": 0, "S2": 1, "SS": 2}
        # Filter by campus/mode so we sort on the semester this student will use,
        # not on all offerings (e.g. internal S1 should not affect a DIS student)
        relevant_sems = [
            o.semester for o in course.offerings
            if o.campus == campus and o.mode == mode
        ]
        earliest_sem = min(
            (sem_order.get(s, 3) for s in relevant_sems),
            default=3,
        )
        return (preferred, earliest_sem, course.level, code)

    # ------------------------------------------------------------------
    # Course subset construction
    # ------------------------------------------------------------------

    def _build_working_set(
        self,
        major_codes: set[str],
        elective_codes: set[str],
        prior_completed: frozenset[str],
    ) -> dict[str, Course]:
        """
        Build the set of courses the scheduler should actually plan.

        Automatically expands the set to include any prerequisite-chain
        courses needed to satisfy prerequisites of major/elective courses
        that aren't already in the set.  For example, if a major requires
        159201 (which needs 159102, which needs 159101), all three are
        included so the scheduler respects the correct ordering.

        Excludes:
        - Courses the student has already completed.
        - Courses the student has explicitly excluded (--exclude flag).
        - Courses with no offering matching the configured campus and delivery
          mode. An internal-only course in a distance plan would deadlock the
          scheduler (it passes prerequisite checks but is never offered).
        - When no_summer=True, courses only available in Summer School (SS).
          These are permanently unschedulable in no-summer plans and would
          cause the generator to loop until the horizon is exceeded.
        """
        campus    = self.generator_template.campus
        mode      = self.generator_template.mode
        no_summer = self.generator_template.no_summer
        all_codes = set(major_codes) | set(elective_codes)

        def _has_valid_offering(course: Course) -> bool:
            matching = [o for o in course.offerings if o.campus == campus and o.mode == mode]
            if not matching:
                return False
            if no_summer:
                return any(o.semester in ("S1", "S2") for o in matching)
            return True

        # --- Expand prerequisite chains -----------------------------------
        # Walk the prereq graph of every course in all_codes and add any
        # prerequisite course that:
        #   a) exists in the full course catalogue
        #   b) has not already been completed by the student
        #   c) has a valid offering for this campus/mode
        # This ensures that e.g. 159201 (requires 159102 → 159101 → 159100)
        # causes all four courses to be included in the working set, so the
        # scheduler enforces the correct semester ordering.
        def _collect_prereq_codes(code: str, visited: set[str]) -> set[str]:
            if code in visited or code not in self.courses:
                return set()
            visited.add(code)
            course = self.courses[code]
            prereq = course.prerequisites
            if prereq is None:
                return set()
            from coursemap.domain.prerequisite import (
                CoursePrerequisite, AndExpression, OrExpression,
            )

            def _expand_node(node) -> set[str]:
                """
                OR-aware prereq expansion.

                AND: expand ALL children (all are required).
                OR:  expand ONLY the best available branch:
                     - already completed → free, pick it
                     - already in working set → reuse it
                     - otherwise pick the lowest-level schedulable branch
                This prevents OR(A, B) from adding both A and B when only
                one is needed, which was causing unnecessary course bloat.
                """
                if isinstance(node, CoursePrerequisite):
                    child = node.code
                    if (
                        child not in visited
                        and child in self.courses
                        and child not in prior_completed
                        and child not in self.excluded_courses
                    ):
                        result = {child}
                        result.update(_collect_prereq_codes(child, set(visited)))
                        return result
                    return set()
                if isinstance(node, AndExpression):
                    result: set[str] = set()
                    for child in node.children:
                        result.update(_expand_node(child))
                    return result
                if isinstance(node, OrExpression):
                    # Already satisfied by a prior_completed or in-plan course?
                    for child in node.children:
                        if isinstance(child, CoursePrerequisite):
                            if child.code in prior_completed or child.code in all_codes:
                                return set()  # satisfied, no expansion needed
                    # Pick the branch with the lowest level (simplest prereq)
                    def _branch_cost(child) -> int:
                        if isinstance(child, CoursePrerequisite):
                            c = self.courses.get(child.code)
                            return c.level if c else 999
                        return 500  # nested expression, deprioritise
                    best = min(node.children, key=_branch_cost)
                    return _expand_node(best)
                return set()

            return _expand_node(prereq)

        # Expand prereq chains. Pass only the expansion set as "visited"
        # (not all_codes) so we can collect prereqs for major courses.
        # Codes already in all_codes are the destination; we want to find
        # the courses needed *before* them.
        expansion: set[str] = set()
        for code in list(all_codes):
            expansion.update(_collect_prereq_codes(code, set(expansion)))
        # Remove codes that are already in the original set to avoid duplication
        expansion -= all_codes
        all_codes.update(expansion)
        # ------------------------------------------------------------------

        working = {
            code: self.courses[code]
            for code in all_codes
            if (
                code in self.courses
                and code not in prior_completed
                and code not in self.excluded_courses
                and _has_valid_offering(self.courses[code])
            )
        }

        # Resolve OR-prerequisites against the final working set. See
        # _resolve_or_prerequisite for why this is needed.
        resolved_working: dict[str, Course] = {}
        for code, course in working.items():
            new_prereq = _resolve_or_prerequisite(course.prerequisites, set(working))
            if new_prereq is not course.prerequisites:
                course = dataclasses.replace(course, prerequisites=new_prereq)
            resolved_working[code] = course

        return resolved_working

    # ------------------------------------------------------------------
    # Prerequisite feasibility check
    # ------------------------------------------------------------------

    def _prereqs_feasible(self, working_set: dict[str, Course]) -> bool:
        """
        Check that the working set can be ordered without a deadlock.

        Simulates the scheduler's topological pass: repeatedly marks courses
        as completable once their prerequisites are met. Returns False if
        progress stalls before all schedulable courses are processed.

        Courses with no offerings are skipped: they will never be eligible
        in the scheduler either, but they should not block the feasibility
        check for courses that do have offerings.

        Prerequisites outside the working set (and not in prior_completed)
        are treated as pre-satisfied -- they are admission gatekeepers or
        out-of-scope courses.
        """
        known = set(working_set.keys()) | self.prior_completed
        # Only consider courses that actually have offerings
        schedulable = {
            code for code, c in working_set.items() if c.offerings
        }
        remaining = set(schedulable)
        completed: set[str] = set(self.prior_completed)

        while remaining:
            unlocked = [
                code for code in remaining
                if prereqs_met(working_set[code].prerequisites, completed, known)
            ]
            if not unlocked:
                return False
            for code in unlocked:
                remaining.discard(code)
                completed.add(code)

        return True
