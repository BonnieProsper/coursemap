"""
ElectiveFiller: subject-area elective recommendation engine.

Extracted from PlannerService.generate_filled_plan() to:
  1. Remove the ~400-line monolith from planner_service.py
  2. Allow the same logic to be called identically for single and double majors
  3. Make the fill strategy independently testable

Single filler implementation used by every plan-filling path (single major,
double major). Used to be two separate implementations: this class, plus a
~250-line inline duplicate in generate_filled_plan that ranked candidates
differently (it had a prereq-chain tier and subject_hint support, this
class didn't), so single and double major auto-fill could recommend
different courses for the same kind of gap. Unified here; see CHANGELOG.md.

Usage::

    filler = ElectiveFiller(courses, campus="D", mode="DIS", no_summer=True)
    candidates = filler.rank_candidates(
        seed_codes=["159101", "159201"],   # courses already in plan
        exclude=frozenset(["159999"]),
        prefer=frozenset(["159234"]),
        budget_credits=60,
        completed=frozenset(),
        chain_seed_codes=["159101", "159201", "159352"],  # major pool codes too
        hint_prefixes=["161"],  # e.g. "Math for CS" from the major's own data
    )
"""
from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass

from coursemap.domain.course import Course

logger = logging.getLogger(__name__)


@dataclass
class FillerCandidate:
    code: str
    credits: int
    level: int
    prefix: str          # subject-area prefix (first 3 digits of code)
    tier: int            # lower = better; see ElectiveFiller class docstring
    restrictions: frozenset[str] = frozenset()  # this course's own restriction codes
    is_preferred: bool = False


class ElectiveFiller:
    """
    Ranks elective candidates to fill a free-elective credit gap.

    Strategy (in priority order):
      Tier 0: explicitly preferred courses (student-supplied ``prefer`` list)
      Tier 1: level-distribution-floor courses. Courses at a level the caller
                has flagged as short relative to a degree-wide credit floor
                (see level_floor_priority below), e.g. Massey's "at least
                75 credits at 300-level" rule (DegreeProfile.min_level_300
                in degree_rules.py). This is a DIFFERENT mechanism from
                Tier 2 below despite looking similar, and it has its own
                tier for a specific reason: Tier 2's needed_levels routinely
                flags several levels at once (e.g. {100: 15, 200: 45} from
                the level-progression rule), and Tier 2 sorts level-ASC
                within itself (see Tier 2's note), so if a distribution
                floor for a HIGHER level (e.g. 300) were merged into that
                same dict/tier, the lower levels already in there would
                consume the entire fill budget first, and the ranked list
                would never even reach the higher level's candidates before
                the caller's budget ran out. Confirmed via a real-dataset
                case (Creative Writing, Bachelor of Arts): merging a
                min_level_300 shortfall into needed_levels selected 135cr
                of L100 and 195cr of L200 filler and 0cr of L300, even
                though L300 was marked "needed" the whole time; the L300
                candidates were simply never reached by the greedy loop.
                A dedicated, higher tier for the distribution floor fixes
                this because it's tried, and can exhaust its own budget
                share, before Tier 2 ever gets a turn.
      Tier 2: level-gate-critical courses. Courses at a level the caller has
                flagged as still short relative to the 45cr level-progression
                rule (see needed_levels below). Without this tier, a surplus
                of cheap L100 filler can crowd out the handful of L200/L300
                courses that would actually satisfy a major's own named
                pools: the credit total comes out right while the pools
                stay unsatisfied (found via a real-dataset sweep, 10 of 25
                sampled undergrad majors hit exactly this, including ones
                with no other unusual structure at all, e.g. English. See
                CHANGELOG.md, "ElectiveFiller Level-Gate Awareness").
      Tier 3: prerequisite-chain courses. Needed (directly or transitively)
                by something already in the plan, but not themselves part of
                the major's requirement tree. Scheduling these as filler is
                pedagogically necessary, not just convenient, so they outrank
                ordinary same-subject electives.
      Tier 4: courses whose 3-digit prefix matches the most common prefix
                in the plan (same subject area) or an explicit subject hint
                from the major's own data (e.g. "Math for CS"), at the
                lowest available level first
      Tier 5: courses from subject areas with at least one course already in
                the plan but not in Tier 4 (adjacent subject areas)

    Within Tier 2 specifically (and only Tier 2), courses are sorted by
    (level ASC, code ASC) so earlier, lower-level courses are always
    preferred. This mimics what a real academic advisor would suggest: take
    lower-level electives first so you can build on them. For Tier 2 it's
    not just a style preference. A lower level must actually be filled
    before a higher one is schedulable at all under the level-progression
    rule, so sorting Tier 2 by shortfall amount instead of level was tried
    and found to be a real bug (see needed_levels and CHANGELOG.md): it
    could let a L200 candidate get selected before enough L100 credit
    existed to make it schedulable, which the real scheduling pass then
    correctly rejected. Tier 1 has no such dependency (a L300 distribution
    floor doesn't require L100/L200 to be filled first, only the course's
    own prerequisites, already checked separately), so this level-ASC
    reasoning doesn't apply there and isn't needed to fix the starvation
    bug described above, the separate tier alone is sufficient.

    The filler never recommends:
      - Zero-credit courses (practicums, language enrolments)
      - Courses with no offering at the student's campus/mode (in S1/S2 only
        if no_summer is set; an SS-only offering doesn't count then)
      - Courses already in the plan or in the exclude set
      - Courses whose prerequisites are not fully met by the current plan
    """

    def __init__(
        self,
        all_courses: dict[str, Course],
        campus: str = "D",
        mode: str = "DIS",
        no_summer: bool = True,
    ) -> None:
        self.courses = all_courses
        self.campus = campus
        self.mode = mode
        self.no_summer = no_summer

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def rank_candidates(
        self,
        seed_codes: list[str],
        completed: frozenset[str],
        budget_credits: int,
        exclude: frozenset[str] = frozenset(),
        prefer: frozenset[str] = frozenset(),
        level_cap: int | None = None,
        chain_seed_codes: list[str] | None = None,
        hint_prefixes: list[str] | None = None,
        needed_levels: dict[int, int] | None = None,
        level_floor_priority: dict[int, int] | None = None,
    ) -> list[FillerCandidate]:
        """
        Return a ranked list of elective candidates.

        Args:
            seed_codes:     Course codes already in the plan (used to derive
                            the subject-area prefix ranking).
            completed:      Codes the student has already completed (satisfy prereqs).
            budget_credits: Maximum total credits needed from fillers.
            exclude:        Codes to never recommend (excluded by student or major).
            prefer:         Codes the student explicitly wants prioritised.
            level_cap:      If set, exclude courses at this level or above
                            (e.g. 400 to avoid honours-only courses).
            chain_seed_codes: Codes whose prerequisite chains should be walked
                            to find Tier 3 candidates. Typically seed_codes
                            plus the major's own elective-pool codes (pool
                            members may have prereqs even if not yet
                            scheduled). Defaults to seed_codes if omitted.
            hint_prefixes:  Subject-area prefixes the major itself recommends
                            (e.g. Mathematics for a Computer Science major),
                            independent of what's already in the plan. These
                            rank as Tier 4 alongside the plan's own top prefix.
            needed_levels:  {level: shortfall_credits} for levels the caller
                            knows are still short relative to the 45cr
                            level-progression rule (e.g. {200: 30} means
                            still need 30cr at L200 to satisfy a gate. See
                            _LEVEL_PROGRESSION_GATE in
                            coursemap.planner.generator and
                            PlanSearch.last_needed_levels, which derives
                            this from the major's own named pools after the
                            discovery pass dropped courses it couldn't
                            justify). A course at one of these levels is
                            promoted to Tier 2 regardless of subject area:
                            closing the gate is what makes the major's named
                            pools satisfiable at all, so it outranks
                            ordinary subject-relevance ranking. Do NOT use
                            this for a degree-wide credit floor like
                            min_level_300, see level_floor_priority instead;
                            merging the two causes a real starvation bug,
                            see the class docstring's Tier 1 note.
            level_floor_priority: {level: shortfall_credits} for levels the
                            caller knows are short relative to a degree-wide
                            level-distribution floor (e.g.
                            DegreeProfile.min_level_300 in degree_rules.py).
                            A course at one of these levels is promoted to
                            Tier 1, ahead of needed_levels' Tier 2, for the
                            reason explained in the class docstring: Tier 2
                            routinely spans several lower levels at once and
                            sorts level-ASC within itself, which would
                            otherwise consume the whole budget before ever
                            reaching a higher level this parameter is trying
                            to prioritise.

        Returns:
            List of FillerCandidate, best-first. The caller is responsible for
            selecting enough candidates to fill the budget.
        """
        needed_levels = needed_levels or {}
        level_floor_priority = level_floor_priority or {}

        # Derive subject prefix distribution from seed codes
        prefix_counts = Counter(
            self._prefix(c) for c in seed_codes
            if c in self.courses and self._prefix(c)
        )
        for hp in (hint_prefixes or []):
            if hp not in prefix_counts:
                prefix_counts[hp] = 0  # ranks after real plan prefixes, but still Tier 4

        top_prefixes = {p for p, _ in prefix_counts.most_common(1)}
        # Hints always count as "top" (Tier 4), even though most_common(1)
        # would only pick one. A major can recommend several subjects at once.
        top_prefixes |= set(hint_prefixes or [])
        secondary_prefixes = {
            p for p, _ in prefix_counts.most_common(6) if p not in top_prefixes
        }

        already_in_plan = set(seed_codes) | set(completed) | exclude
        chain_codes = self._collect_prereq_chain(
            chain_seed_codes if chain_seed_codes is not None else seed_codes,
            exclude=already_in_plan,
        )

        # Restrictions cut both ways and the scraped data isn't guaranteed to
        # list a pair from both sides (Massey's own pages don't always list
        # the reverse direction either), so precompute what's restricted BY
        # anything already in the plan, not just what each already-planned
        # course's own restrictions field says. Without this, a candidate
        # like 159100 (restricted against 159101) gets recommended as filler
        # even when 159101 is already a required course elsewhere in the
        # same plan, and the generator correctly rejects the whole plan
        # afterward instead of the filler just picking something else.
        restricted_by_existing: set[str] = set()
        for code in already_in_plan:
            existing = self.courses.get(code)
            if existing:
                restricted_by_existing |= existing.restrictions

        candidates: list[FillerCandidate] = []

        for code, course in self.courses.items():
            if code in already_in_plan:
                continue
            if course.credits <= 0:
                continue
            if not self._is_offered(course):
                continue
            if level_cap and course.level >= level_cap:
                continue
            if not self._prereqs_satisfiable(course, completed | set(seed_codes)):
                continue
            if course.restrictions & already_in_plan:
                continue
            if code in restricted_by_existing:
                continue

            prefix = self._prefix(code)
            is_preferred = code in prefer

            if is_preferred:
                tier = 0
            elif level_floor_priority.get(course.level, 0) > 0:
                tier = 1
            elif needed_levels.get(course.level, 0) > 0:
                tier = 2
            elif code in chain_codes:
                tier = 3
            elif prefix in top_prefixes:
                tier = 4
            elif prefix in secondary_prefixes:
                tier = 5
            elif not top_prefixes:
                # No seed codes or hints provided. Broad-search mode: include everything
                tier = 6
            else:
                continue  # out of scope, don't recommend

            candidates.append(FillerCandidate(
                code=code,
                credits=course.credits,
                level=course.level,
                prefix=prefix,
                tier=tier,
                restrictions=course.restrictions,
                is_preferred=is_preferred,
            ))

        # Sort: tier ASC, then level ASC (lowest first, always, even within
        # Tier 2: a lower level must be filled before a higher one is usable
        # at all under the level-progression rule itself, so sorting Tier 2
        # by shortfall amount instead of level was a real bug, found via a
        # full-dataset sample. It let the filler pick L200 candidates before
        # enough L100 existed to make them schedulable, so the same gate
        # that was supposed to be satisfied ended up blocking the filler's
        # own selections in the real scheduling pass. See CHANGELOG.md.
        # Then code ASC as the final tiebreak.
        candidates.sort(key=lambda c: (c.tier, c.level, c.code))

        logger.debug(
            "ElectiveFiller: %d candidates for budget=%dcr (top prefixes=%s, "
            "%d prereq-chain candidates, needed_levels=%s, level_floor_priority=%s)",
            len(candidates), budget_credits, sorted(top_prefixes),
            len(chain_codes), needed_levels, level_floor_priority,
        )
        return candidates

    def select_to_fill(
        self,
        seed_codes: list[str],
        completed: frozenset[str],
        budget_credits: int,
        exclude: frozenset[str] = frozenset(),
        prefer: frozenset[str] = frozenset(),
        level_cap: int | None = None,
        chain_seed_codes: list[str] | None = None,
        hint_prefixes: list[str] | None = None,
        overshoot_tolerance: int = 0,
        needed_levels: dict[int, int] | None = None,
        level_credit_limits: dict[int, int] | None = None,
        level_floor_priority: dict[int, int] | None = None,
    ) -> list[str]:
        """
        Select elective codes that fit within budget_credits.

        Greedy selection: takes candidates in rank order until budget is filled.
        Returns just the course codes (not FillerCandidate objects).

        overshoot_tolerance: allow a candidate whose credits would push the
        running total up to this many credits past budget_credits, rather
        than skipping it outright. 0 (default) means never overshoot, the
        original ElectiveFiller behaviour. generate_filled_plan's inline
        implementation used a 14cr tolerance (skip only if the overshoot
        would exceed almost a full extra course) so a single slightly-larger
        course wasn't needlessly passed over; pass overshoot_tolerance=14 to
        match that.

        needed_levels, level_floor_priority: see rank_candidates. Passed
        through unchanged; DO NOT merge these two into one dict, see
        rank_candidates' docstring and the class docstring's Tier 1 note for
        the starvation bug that causes.

        level_credit_limits: {level: max_credits_from_filler_at_this_level}.
        Unlike needed_levels/level_floor_priority (a ranking preference, more
        of that level is still fine), this is a hard cap enforced during
        selection: a candidate is skipped, not just deprioritised, once
        selecting it would push the running total at its level past the
        limit. Intended for a degree-wide ceiling like Massey's "not more
        than 165 credits at 100-level" (see DegreeProfile.max_level_100 in
        degree_rules.py): the ranking tiers already sort by level ASC within
        Tier 2 specifically (lower levels first, so earlier prerequisites get
        satisfied sooner, see the class docstring), which is exactly
        backwards for a level that's already at its ceiling, so ranking
        alone can't fix this, only a hard stop during selection can. The
        caller is responsible for computing the limit as "cap minus credits
        already committed elsewhere in the plan" (major-required courses,
        named elective pools), not the raw DegreeProfile number itself:
        this method only ever sees what it's adding, not the whole plan.
        """
        ranked = self.rank_candidates(
            seed_codes=seed_codes,
            completed=completed,
            budget_credits=budget_credits,
            exclude=exclude,
            prefer=prefer,
            level_cap=level_cap,
            chain_seed_codes=chain_seed_codes,
            hint_prefixes=hint_prefixes,
            needed_levels=needed_levels,
            level_floor_priority=level_floor_priority,
        )

        level_credit_limits = level_credit_limits or {}
        level_floor_priority = level_floor_priority or {}
        level_running: dict[int, int] = {}
        floor_running: dict[int, int] = {}
        # rank_candidates already excludes anything restricted against what
        # was already in the plan BEFORE this call started. This tracks
        # restrictions introduced by selections made DURING this call, since
        # the ranked list is built once upfront: two candidates that
        # restrict each other could otherwise both pass the initial ranking
        # and both get selected in the same batch.
        restricted_by_selected: set[str] = set()

        selected: list[str] = []
        running = 0
        for cand in ranked:
            if running >= budget_credits:
                break
            if running + cand.credits > budget_credits + overshoot_tolerance:
                continue
            if cand.code in restricted_by_selected or cand.restrictions & set(selected):
                continue
            limit = level_credit_limits.get(cand.level)
            if limit is not None and level_running.get(cand.level, 0) + cand.credits > limit:
                continue
            # Once a distribution-floor level (Tier 1) has reached its target,
            # stop treating further candidates at that level as forced-priority.
            # Without this, a large budget (e.g. a thin major with a big free-
            # elective gap) lets Tier 1 alone consume the entire budget once
            # its shortfall is satisfied several times over, crowding out
            # ordinary subject-relevant Tier 4/5 picks that would otherwise
            # fill the rest. The candidate is simply skipped rather than
            # re-tiered, a small missed-opportunity cost (it might have also
            # been a fine Tier 4 same-subject pick) traded for not needing a
            # second ranking pass mid-loop.
            if cand.tier == 1 and floor_running.get(cand.level, 0) >= level_floor_priority.get(cand.level, 0):
                continue
            selected.append(cand.code)
            restricted_by_selected |= cand.restrictions
            running += cand.credits
            if limit is not None:
                level_running[cand.level] = level_running.get(cand.level, 0) + cand.credits
            if cand.tier == 1:
                floor_running[cand.level] = floor_running.get(cand.level, 0) + cand.credits

        logger.debug(
            "ElectiveFiller.select_to_fill: selected %d courses for %dcr budget "
            "(running=%dcr, level_credit_limits=%s, level_floor_priority=%s)",
            len(selected), budget_credits, running, level_credit_limits, level_floor_priority,
        )
        return selected

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _prefix(code: str) -> str:
        """Return the 3-digit numeric prefix of a course code."""
        digits = "".join(c for c in code if c.isdigit())
        return digits[:3] if len(digits) >= 3 else ""

    def _is_offered(self, course: Course) -> bool:
        """
        True if the course has an offering at the student's campus/mode in a
        semester that's actually usable: any semester normally, S1/S2 only
        if no_summer is set (an SS-only course can never be scheduled then,
        matches the same check the generator itself applies during scheduling).
        """
        for o in course.offerings:
            if o.campus != self.campus or o.mode != self.mode:
                continue
            if self.no_summer and o.semester == "SS":
                continue
            return True
        return False

    def _collect_prereq_chain(
        self, seed_codes: list[str], exclude: set[str],
    ) -> set[str]:
        """
        Walk the prerequisite trees of `seed_codes` (transitively) and
        return every course code found that isn't in `exclude`.

        Uses an OR-aware walk in the sense that it doesn't try to determine
        which OR branch is actually needed. It collects every branch's
        codes. That's deliberately permissive here: this set only feeds
        into candidate *ranking* (Tier 1 vs Tier 2+), never into a hard
        eligibility decision, so including a few not-strictly-needed OR
        alternatives just means they get offered as slightly-higher-priority
        filler suggestions, not that an invalid plan gets produced.
        """
        from coursemap.domain.prerequisite import (
            AndExpression, OrExpression, CoursePrerequisite,
        )

        chain: set[str] = set()
        visited: set[str] = set()

        def _walk(code: str) -> None:
            if code in visited or code not in self.courses:
                return
            visited.add(code)
            prereq = self.courses[code].prerequisites
            if prereq is None:
                return
            stack = [prereq]
            while stack:
                node = stack.pop()
                if isinstance(node, CoursePrerequisite):
                    child = node.code
                    if child in self.courses and child not in exclude:
                        chain.add(child)
                        _walk(child)
                elif isinstance(node, (AndExpression, OrExpression)):
                    stack.extend(node.children)

        for code in seed_codes:
            _walk(code)
        return chain

    @staticmethod
    def _prereqs_satisfiable(course: Course, available: set[str]) -> bool:
        """
        Return True if the course's prerequisites can be met from ``available``.

        Uses an OR-aware check: an OR expression is satisfiable if ANY one branch
        is met. An AND expression requires ALL branches. This prevents the old
        ``required_courses()`` approach from demanding all OR-branch codes are
        present simultaneously (which is too strict: it rejects courses that
        only need one of several alternatives).
        """
        prereq = course.prerequisites
        if prereq is None:
            return True

        from coursemap.domain.prerequisite import (
            AndExpression,
            OrExpression,
            CoursePrerequisite,
        )

        def _sat(node) -> bool:
            if isinstance(node, CoursePrerequisite):
                return node.code in available
            if isinstance(node, AndExpression):
                return all(_sat(c) for c in node.children)
            if isinstance(node, OrExpression):
                return any(_sat(c) for c in node.children)
            # Unknown node type: assume satisfiable (don't over-reject)
            return True

        return _sat(prereq)

