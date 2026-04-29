"""
Orchestration layer between the CLI and the planning/search engine.

PlannerService is the single entry point for plan generation. It:

  1. Resolves the user's major name to the matching dataset entry.
  2. Derives the degree requirement tree from qualification metadata
     (replacing the old hardcoded degree_requirements.json approach).
  3. Constructs the PlanGenerator template and PlanSearch instance.
  4. Returns the best valid DegreePlan along with diagnostics.

The service intentionally knows nothing about scheduling logic; that lives
in planner.generator. It knows nothing about the CLI; that lives in cli.main.
"""

from __future__ import annotations

import difflib
import json
import logging
from pathlib import Path

from coursemap.domain.course import Course
from coursemap.domain.plan import DegreePlan
from coursemap.domain.requirement_nodes import (
    AllOfRequirement,
    ChooseCreditsRequirement,
    RequirementNode,
    TotalCreditsRequirement,
)
from coursemap.domain.requirement_serialization import requirement_from_dict
from coursemap.domain.requirement_utils import (
    collect_course_codes,
    collect_elective_nodes,
    find_total_credits,
)
from coursemap.optimisation.search import PlanSearch
from coursemap.planner.generator import PlanGenerator
from coursemap.rules.degree_rules import build_degree_tree, filter_requirement_tree, profile_for

logger = logging.getLogger(__name__)

_DATASETS_DIR = Path(__file__).resolve().parents[2] / "datasets"


def _load_qualification_map() -> dict[str, dict]:
    """
    Return a dict mapping major title -> qualification metadata.

    Built by joining specialisations.json (major title -> qual_code) with
    qualifications.json (qual_code -> level, length, title).
    """
    specs_path = _DATASETS_DIR / "specialisations.json"
    quals_path = _DATASETS_DIR / "qualifications.json"

    if not specs_path.exists() or not quals_path.exists():
        logger.warning(
            "specialisations.json or qualifications.json not found; "
            "degree rules will fall back to 360cr/no-level-constraints for all majors."
        )
        return {}

    specs = json.loads(specs_path.read_text(encoding="utf-8"))
    quals = json.loads(quals_path.read_text(encoding="utf-8"))

    qual_by_code = {q["qual_code"]: q for q in quals}
    return {
        s["title"]: qual_by_code[s["qual_code"]]
        for s in specs
        if s["qual_code"] in qual_by_code
    }


class PlannerService:
    """
    Orchestrates degree plan generation for a given major and student state.

    Attributes:
        courses:            Full course catalogue, code -> Course.
        majors:             Raw major list from majors.json (after load_majors()).
        _qual_map:          Maps major title to qualification metadata.
    """

    def __init__(
        self,
        courses: dict[str, Course],
        majors: list[dict],
    ):
        self.courses = courses
        self.majors = majors
        self._qual_map = _load_qualification_map()
        self.last_plan_stats = None

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def generate_best_plan(
        self,
        major_name: str | None = None,
        max_credits_per_semester: int = 60,
        max_courses_per_semester: int | None = None,
        campus: str = "D",
        mode: str = "DIS",
        start_year: int = 2026,
        start_semester: str = "S1",
        prior_completed: frozenset = frozenset(),
        preferred_electives: frozenset = frozenset(),
        excluded_courses: frozenset = frozenset(),
        no_summer: bool = False,
        transfer_credits: int = 0,
    ) -> DegreePlan:
        """
        Generate the best valid degree plan for the given major.

        Args:
            major_name:               Partial or full major name. None plans all majors.
            max_credits_per_semester: Credit cap per semester (default 60, full-time).
            max_courses_per_semester: Course count cap per semester (None = no limit).
            campus:                   Campus code filter (e.g. 'D' for distance).
            mode:                     Delivery mode filter (e.g. 'DIS', 'INT').
            start_year:               First calendar year of study.
            prior_completed:          Course codes already completed before this plan.
            preferred_electives:      Course codes to prefer when selecting electives.
            excluded_courses:         Course codes to never schedule (student opt-out).

        Returns:
            The highest-scoring valid DegreePlan found.

        Raises:
            ValueError: No matching major, ambiguous name, or no valid plan exists.
        """
        resolved = self._resolve_major(major_name)

        parsed_majors = []
        for m in resolved:
            req_tree = self._build_major_req_tree(m)
            degree_tree = self._build_degree_tree(m, req_tree, campus=campus, mode=mode)
            parsed_majors.append({
                "name": m["name"],
                "url": m.get("url", ""),
                "raw": m,
                "requirement": req_tree,
                "degree_tree": degree_tree,
            })

        generator_template = PlanGenerator(
            self.courses,
            max_credits_per_semester=max_credits_per_semester,
            max_courses_per_semester=max_courses_per_semester,
            campus=campus,
            mode=mode,
            start_year=start_year,
            start_semester=start_semester,
            no_summer=no_summer,
        )

        search = PlanSearch(
            courses=self.courses,
            majors=parsed_majors,
            generator_template=generator_template,
            prior_completed=prior_completed,
            preferred_electives=preferred_electives,
            excluded_courses=excluded_courses,
        )

        plan = search.search()
        self.last_plan_stats = search.best_generator_stats
        if transfer_credits > 0:
            plan.transfer_credits = transfer_credits
        return plan

    def resolve_major(self, major_name: str | None) -> list[dict]:
        """
        Public name resolution. Returns the list of matching raw major dicts.

        Accepts exact or case-insensitive substring names. Raises ValueError
        on ambiguous or missing matches so callers can provide a useful error.
        """
        return self._resolve_major(major_name)

    def degree_tree_for_major(
        self,
        major_name: str,
        campus: str = "D",
        mode: str = "DIS",
    ) -> RequirementNode | None:
        """
        Return the full degree requirement tree for a named major.

        Returns None when the name matches zero or more than one major so the
        caller can skip validation gracefully without raising.
        """
        try:
            resolved = self._resolve_major(major_name)
        except ValueError:
            return None
        if len(resolved) != 1:
            return None
        m = resolved[0]
        return self._build_degree_tree(
            m,
            self._build_major_req_tree(m),
            campus=campus,
            mode=mode,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_major(self, major_name: str | None) -> list[dict]:
        if not major_name:
            return self.majors

        query = major_name.strip().lower()

        # Exact match (case-insensitive)
        exact = [m for m in self.majors if m["name"].lower() == query]
        if exact:
            return exact

        # Whole-string substring (handles "Computer Science – Bachelor of Science")
        partial = [m for m in self.majors if query in m["name"].lower()]
        if len(partial) == 1:
            return partial
        if len(partial) > 1:
            # Apply smart disambiguation before raising: prefer undergrad over postgrad,
            # then prefer BSc/BA over named professional degrees.
            smart = self._smart_disambiguate(partial, query)
            if smart is not None:
                return smart
            names = "\n  ".join(m["name"] for m in partial)
            raise ValueError(
                f"'{major_name}' matches {len(partial)} majors -- be more specific:\n  {names}"
            )

        # Word-overlap: every query word must appear as a substring of some
        # token in the major name. Handles abbreviations like 'comp sci',
        # 'maths', 'psych' that don't substring-match the full name.
        words = query.split()
        def word_match(name: str) -> bool:
            tokens = name.lower().replace("–", " ").split()
            return all(any(w in tok for tok in tokens) for w in words)

        word_matches = [m for m in self.majors if word_match(m["name"])]
        if len(word_matches) == 1:
            return word_matches
        if len(word_matches) > 1:
            smart = self._smart_disambiguate(word_matches, query)
            if smart is not None:
                return smart
            names = "\n  ".join(m["name"] for m in word_matches)
            raise ValueError(
                f"'{major_name}' matches {len(word_matches)} majors -- be more specific:\n  {names}"
            )

        # Last resort: difflib sequence similarity for typos / transpositions.
        all_names = [m["name"] for m in self.majors]
        suggestions = difflib.get_close_matches(major_name, all_names, n=5, cutoff=0.35)
        # If difflib finds nothing, try word-overlap scoring for partial suggestions.
        if not suggestions:
            query_words = set(query.split())
            scored = [
                (sum(1 for w in query_words if w in m["name"].lower()), m["name"])
                for m in self.majors
            ]
            suggestions = [name for sc, name in sorted(scored, reverse=True) if sc > 0][:5]
        hint = (
            "\n  " + "\n  ".join(suggestions) if suggestions
            else "\n  Run 'coursemap majors --search <keyword>' to browse."
        )
        raise ValueError(f"No major matching '{major_name}'. Did you mean:{hint}")

    def _smart_disambiguate(self, candidates: list[dict], query: str) -> list[dict] | None:
        """
        Given a list of ambiguous major matches, attempt to return a single best match.

        Strategy:
        1. If the query has no degree-type qualifier, strip postgrad options first.
        2. If one undergrad remains, return it.
        3. If multiple undergrads remain, prefer by standard degree order
           (BSc > BA > BBus > BHSc > BIS > other bachelor's).
        4. Return None if still ambiguous (caller will raise with full list).
        """
        _POSTGRAD_MARKERS = ("master", "honours", "postgrad", "graduate", "doctor", "phd",
                             "diploma", "certificate")
        _UNDERGRAD_MARKERS = ("bachelor",)
        query_has_qual = any(m in query for m in _POSTGRAD_MARKERS + _UNDERGRAD_MARKERS)

        if query_has_qual:
            return None  # User specified a qualifier - don't second-guess them

        undergrad = [
            m for m in candidates
            if any(mk in m["name"].lower() for mk in _UNDERGRAD_MARKERS)
            and not any(mk in m["name"].lower() for mk in _POSTGRAD_MARKERS)
        ]

        if len(undergrad) == 1:
            return undergrad

        if len(undergrad) > 1:
            # Prefer by standard Massey degree type order.
            _PREFERRED_ORDER = [
                "bachelor of science",
                "bachelor of arts",
                "bachelor of business",
                "bachelor of health science",
                "bachelor of engineering",
                "bachelor of information sciences",
                "bachelor of social work",
            ]
            for pref in _PREFERRED_ORDER:
                pref_match = [m for m in undergrad if pref in m["name"].lower()]
                if len(pref_match) == 1:
                    return pref_match

        return None  # Still ambiguous

    def _build_major_req_tree(self, major: dict) -> RequirementNode:
        """
        Parse the RequirementNode tree for this major's courses.

        The loaded dataset always provides a 'requirement' key containing a
        serialised node tree. The isinstance check on RequirementNode handles
        the case where the tree was already deserialised (e.g. in tests).
        """
        req = major.get("requirement")
        if isinstance(req, dict):
            return requirement_from_dict(req)
        if isinstance(req, RequirementNode):
            return req
        raise ValueError(
            f"Major '{major.get('name')}' has no 'requirement' field. "
            "Re-run ingestion to rebuild majors.json."
        )

    def _build_degree_tree(
        self,
        major: dict,
        major_req: RequirementNode,
        campus: str = "D",
        mode: str = "DIS",
    ) -> RequirementNode:
        """
        Derive the full degree requirement tree for this major, filtered to the
        configured delivery mode.

        Two adjustments are made relative to the raw requirement tree:

        1. CourseRequirement nodes for courses with no offering in the given
           campus/mode are removed. This aligns the validation tree with the
           working set so a plan is not penalised for requirements it genuinely
           cannot satisfy (e.g. internal-only fieldwork in a distance plan).

        2. Credit and level constraints (TotalCredits, MaxLevel, MinLevel) are
           included only when the schedulable major credits cover the full degree
           target. When the scraped data is incomplete (free electives missing),
           these constraints are omitted to avoid false failures.
        """

        name = major["name"]
        qual = self._qual_map.get(name)
        if qual is None:
            logger.warning("No qualification found for '%s'; using 360cr fallback.", name)
            return AllOfRequirement((TotalCreditsRequirement(360), major_req))

        all_codes = collect_course_codes(major_req)

        schedulable_codes = frozenset(
            code for code in all_codes
            if code in self.courses
            and any(o.campus == campus and o.mode == mode for o in self.courses[code].offerings)
        )

        course_credits = {code: self.courses[code].credits for code in self.courses}
        filtered_req = (
            filter_requirement_tree(major_req, schedulable_codes, course_credits)
            or major_req
        )

        schedulable_credits = sum(
            self.courses[c].credits for c in schedulable_codes
        )

        return build_degree_tree(
            major_req=filtered_req,
            qual_level=qual["level"],
            qual_length=qual["length"],
            major_name=name,
            schedulable_major_credits=schedulable_credits,
        )

    def generate_double_major_plan(
        self,
        major_name: str,
        second_major_name: str,
        max_credits_per_semester: int = 60,
        max_courses_per_semester: int | None = None,
        campus: str = "D",
        mode: str = "DIS",
        start_year: int = 2026,
        start_semester: str = "S1",
        prior_completed: frozenset = frozenset(),
        preferred_electives: frozenset = frozenset(),
        excluded_courses: frozenset = frozenset(),
        no_summer: bool = False,
        transfer_credits: int = 0,
    ) -> tuple["DegreePlan", dict]:
        """
        Generate a combined degree plan for two concurrent majors.

        Courses shared between majors are counted once (deduplication). The
        scheduler sees a single merged working set. Validation is run
        independently for each major so both requirement trees are satisfied.

        Returns (plan, info) where info contains:
            'shared_codes'    : frozenset of course codes counted in both majors
            'first_label'     : resolved name of the first major
            'second_label'    : resolved name of the second major
            'first_gap'       : free-elective gap for first major (credits)
            'second_gap'      : free-elective gap for second major (credits)
            'combined_credits': total credits in the merged requirement trees
                                (before deduplication)
            'saved_credits'   : credits saved by deduplication (shared × credit)

        Raises ValueError if either major cannot be resolved or no valid plan
        can be produced for the merged working set.
        """
        # Resolve both majors.
        first_resolved  = self._resolve_major(major_name)
        second_resolved = self._resolve_major(second_major_name)

        if len(first_resolved) != 1:
            raise ValueError(
                f"'{major_name}' must resolve to exactly one major for a double major plan."
            )
        if len(second_resolved) != 1:
            raise ValueError(
                f"'{second_major_name}' must resolve to exactly one major for a double major plan."
            )

        first_major  = first_resolved[0]
        second_major = second_resolved[0]

        first_req  = self._build_major_req_tree(first_major)
        second_req = self._build_major_req_tree(second_major)

        # Build merged requirement tree: ALL_OF(first_req, second_req).
        # Shared courses satisfy both subtrees - the validator checks each
        # independently against plan.all_course_codes.
        from coursemap.domain.requirement_nodes import AllOfRequirement as _AllOf
        merged_req = _AllOf((first_req, second_req))

        # Build per-major degree trees, then compose the merged tree using only
        # the course-requirement subtrees (not TotalCreditsRequirement nodes).
        # Using AllOf(first_tree, second_tree) directly would require 720cr total
        # for two 360cr degrees, which is incorrect: the two majors share a single
        # enrolment and the credit target is the higher of the two.
        first_tree  = self._build_degree_tree(first_major,  first_req,  campus=campus, mode=mode)
        second_tree = self._build_degree_tree(second_major, second_req, campus=campus, mode=mode)

        # Extract just the major-requirement subtrees (strip TotalCreditsRequirement
        # wrappers) so validation checks course coverage without demanding 720cr.
        def _major_subtree(tree: "RequirementNode") -> "RequirementNode":
            """Return the inner major requirement node, unwrapping AllOf(TotalCredits, req)."""
            from coursemap.domain.requirement_nodes import AllOfRequirement as _A, TotalCreditsRequirement as _T
            if isinstance(tree, _A) and len(tree.children) == 2:
                non_total = [c for c in tree.children if not isinstance(c, _T)]
                if len(non_total) == 1:
                    return non_total[0]
            return tree

        merged_tree = _AllOf((_major_subtree(first_tree), _major_subtree(second_tree)))

        parsed_combined = [{
            "name": f"{first_major['name']} + {second_major['name']}",
            "url":  "",
            "raw":  {},
            "requirement":  merged_req,
            "degree_tree":  merged_tree,
        }]

        generator_template = PlanGenerator(
            self.courses,
            max_credits_per_semester=max_credits_per_semester,
            max_courses_per_semester=max_courses_per_semester,
            campus=campus,
            mode=mode,
            start_year=start_year,
            start_semester=start_semester,
            no_summer=no_summer,
        )

        from coursemap.optimisation.search import PlanSearch as _PlanSearch
        search = _PlanSearch(
            courses=self.courses,
            majors=parsed_combined,
            generator_template=generator_template,
            prior_completed=prior_completed,
            preferred_electives=preferred_electives,
            excluded_courses=excluded_courses,
        )
        plan = search.search()
        self.last_plan_stats = search.best_generator_stats

        # Reattach prior-completed course objects.
        if prior_completed:
            prior_objects = tuple(
                self.courses[c] for c in prior_completed if c in self.courses
            )
            plan = type(plan)(semesters=plan.semesters, prior_completed=prior_objects)

        # Build info dict.
        from coursemap.domain.requirement_utils import collect_course_codes as _ccc
        first_codes  = _ccc(first_req)
        second_codes = _ccc(second_req)
        shared_codes = first_codes & second_codes

        saved_credits = sum(
            self.courses[c].credits for c in shared_codes if c in self.courses
        )
        combined_credits = sum(
            self.courses[c].credits
            for c in first_codes | second_codes
            if c in self.courses
        )

        info = {
            "shared_codes":     frozenset(shared_codes),
            "first_label":      first_major["name"],
            "second_label":     second_major["name"],
            "first_gap":        self.free_elective_gap(major_name,        campus=campus, mode=mode),
            "second_gap":       self.free_elective_gap(second_major_name, campus=campus, mode=mode),
            "combined_credits": combined_credits,
            "saved_credits":    saved_credits,
        }
        if transfer_credits > 0:
            plan.transfer_credits = transfer_credits
        return plan, info

    def generate_filled_plan(
        self,
        major_name: str | None = None,
        max_credits_per_semester: int = 60,
        max_courses_per_semester: int | None = None,
        campus: str = "D",
        mode: str = "DIS",
        start_year: int = 2026,
        start_semester: str = "S1",
        prior_completed: frozenset = frozenset(),
        preferred_electives: frozenset = frozenset(),
        excluded_courses: frozenset = frozenset(),
        no_summer: bool = False,
        transfer_credits: int = 0,
    ) -> tuple["DegreePlan", list[str]]:
        """
        Generate a plan and auto-fill the free-elective gap with subject-area courses.

        Returns (filled_plan, filler_codes) where filler_codes are the course
        codes added to fill the gap.  If the gap is zero the plan is returned
        unchanged with an empty filler list.

        The fill strategy selects same-subject-prefix courses ordered by
        (prefix_rank, level, code), then injects them into the major's requirement
        tree as an additional CHOOSE_CREDITS pool before re-running the full
        PlanSearch pipeline. This ensures the filled plan benefits from the same
        elective selection, prerequisite resolution, rebalancing and equalisation
        passes as a normal plan - fixing the sparse-final-semester issue that
        occurred when the filler bypassed PlanSearch.
        """
        from collections import Counter as _Counter
        from coursemap.domain.requirement_nodes import (
            AllOfRequirement as _AllOf,
            ChooseCreditsRequirement as _CCR,
        )

        # First pass: generate the unfilled plan to discover working codes
        # and compute the free-elective gap.
        base_plan = self.generate_best_plan(
            major_name=major_name,
            max_credits_per_semester=max_credits_per_semester,
            max_courses_per_semester=max_courses_per_semester,
            campus=campus,
            mode=mode,
            start_year=start_year,
            start_semester=start_semester,
            prior_completed=prior_completed,
            preferred_electives=preferred_electives,
            excluded_courses=excluded_courses,
            no_summer=no_summer,
        )

        gap = self.free_elective_gap(major_name, campus=campus, mode=mode) if major_name else 0
        if gap <= 0:
            if transfer_credits > 0:
                base_plan.transfer_credits = transfer_credits
            return base_plan, []

        # Reduce gap by transfer credits the student already has.
        effective_gap = max(0, gap - transfer_credits)
        if effective_gap <= 0:
            if transfer_credits > 0:
                base_plan.transfer_credits = transfer_credits
            return base_plan, []

        # Identify filler candidates in two passes:
        #   Pass 1 (same-prefix): courses whose 3-digit code prefix matches
        #           subjects already in the base plan. These are the most
        #           relevant free electives for the student's programme.
        #   Pass 2 (broadened): when pass 1 cannot cover the full gap, fall
        #           back to ANY undergrad-level course in the catalogue that
        #           is schedulable in the requested campus/mode.
        # Both passes respect the excluded_courses list and the per-course
        # level cap (no higher than max_level + 100 to stay broadly coherent).\
        planned_codes = {c.code for s in base_plan.semesters for c in s.courses}
        prior_codes   = {c.code for c in base_plan.prior_completed}

        # Also exclude codes that appear in the major's own elective pools.
        # When a pool code is also selected as a filler code it gets double-
        # counted: the scheduler places it once but both the pool requirement
        # and the filler pool requirement claim it, leaving the degree short
        # of the total-credit target.  Excluding pool codes from the filler
        # candidates prevents this overlap.
        resolved_for_pool = self._resolve_major(major_name) if major_name else []
        major_pool_codes: set[str] = set()
        for _m in resolved_for_pool:
            _rt = self._build_major_req_tree(_m)
            from coursemap.domain.requirement_utils import collect_elective_nodes as _cen
            for _node in _cen(_rt):
                if isinstance(_node, _CCR):
                    major_pool_codes.update(_node.course_codes)

        excluded_all  = planned_codes | prior_codes | excluded_courses | major_pool_codes

        prefix_counts = _Counter(code[:3] for code in planned_codes)
        prefix_rank   = {pfx: rank for rank, (pfx, _) in enumerate(prefix_counts.most_common())}
        max_level = max(
            (self.courses[c].level for c in planned_codes if c in self.courses),
            default=100,
        )

        def _is_schedulable(course) -> bool:
            # Must have at least one offering in the requested campus/mode.
            # When no_summer=True, the course must be available in S1 or S2
            # (not SS-only), otherwise it can never be scheduled and will
            # cause an infinite loop in the generator.
            offerings = [o for o in course.offerings if o.campus == campus and o.mode == mode]
            if not offerings:
                return False
            if no_summer:
                return any(o.semester in ("S1", "S2") for o in offerings)
            return True

        def _level_ok(course) -> bool:
            # For undergrad fill: cap at level 300 or max_level+100, whichever is lower.
            # Also exclude postgrad-only courses (level 700+).
            return course.level <= 300 and course.level <= max_level + 100

        # Pass 1: same-subject-prefix candidates (ordered: preferred > prefix rank > level > code)
        same_prefix: list[tuple] = []
        for code, course in self.courses.items():
            if code in excluded_all:
                continue
            if not _is_schedulable(course):
                continue
            if not _level_ok(course):
                continue
            pfx = code[:3]
            if pfx in prefix_rank:
                prefer = 0 if code in preferred_electives else 1
                same_prefix.append((prefer, prefix_rank[pfx], course.level, code))
        same_prefix.sort()

        filler_codes: list[str] = []
        running = 0
        for _, _, _, code in same_prefix:
            if running >= effective_gap:
                break
            cr = self.courses[code].credits
            if running + cr > effective_gap + 14:
                continue
            filler_codes.append(code)
            running += cr

        # Pass 2: broaden to full undergrad catalogue when same-prefix pool is exhausted.
        if running < effective_gap:
            selected_set = set(filler_codes)
            # Candidates that were not already in pass 1 (different prefix or not preferred).
            # Ordered: preferred > level > code (no prefix bias - open elective).
            broad: list[tuple] = []
            for code, course in self.courses.items():
                if code in excluded_all or code in selected_set:
                    continue
                if not _is_schedulable(course):
                    continue
                if not _level_ok(course):
                    continue
                pfx = code[:3]
                if pfx in prefix_rank:
                    continue  # already considered in pass 1
                prefer = 0 if code in preferred_electives else 1
                broad.append((prefer, course.level, code))
            broad.sort()
            for _, _, code in broad:
                if running >= effective_gap:
                    break
                cr = self.courses[code].credits
                if running + cr > effective_gap + 14:
                    continue
                filler_codes.append(code)
                running += cr

        if not filler_codes:
            if transfer_credits > 0:
                base_plan.transfer_credits = transfer_credits
            return base_plan, []

        # Second pass: inject filler codes as a new CHOOSE_CREDITS pool appended
        # to the major's requirement tree, then re-run PlanSearch end-to-end.
        # This preserves full elective selection, prerequisite ordering, and all
        # four rebalancing/equalisation passes for the combined course set.
        filler_pool = _CCR(
            credits=running,
            course_codes=frozenset(filler_codes),
        )
        resolved = self._resolve_major(major_name)

        parsed_majors_filled = []
        for m in resolved:
            req_tree = self._build_major_req_tree(m)
            # Attach filler pool alongside the major's own requirements.
            augmented_req = _AllOf((req_tree, filler_pool))

            # Build the degree tree from augmented_req so TotalCreditsRequirement
            # accounts for the filler credits. Without this, PlanSearch computes
            # schedulable_pool_contribution including the filler 150cr, then caps
            # required_codes to degree_total - pool_contribution = 210cr, which
            # truncates the 210cr major working set to 150cr.
            #
            # By passing augmented_req (210cr required + 150cr filler pool = 360cr)
            # as schedulable_major_credits, build_degree_tree includes
            # TotalCreditsRequirement(360) and PlanSearch treats the full 360cr
            # as the intended plan size.
            name_m = m["name"]
            qual = self._qual_map.get(name_m)
            if qual is not None:
                from coursemap.domain.requirement_utils import collect_course_codes as _ccc
                from coursemap.rules.degree_rules import profile_for as _pfor, filter_requirement_tree as _frt
                all_aug_codes = _ccc(augmented_req)
                schedulable_aug = frozenset(
                    code for code in all_aug_codes
                    if code in self.courses
                    and any(o.campus == campus and o.mode == mode for o in self.courses[code].offerings)
                )
                schedulable_aug_credits = sum(self.courses[c].credits for c in schedulable_aug)
                filtered_aug = _frt(augmented_req, schedulable_aug, {c: self.courses[c].credits for c in self.courses}) or augmented_req
                from coursemap.rules.degree_rules import build_degree_tree as _bdt
                # force_total_credits=True because the augmented tree now
                # includes filler courses that bring the working set to the
                # degree credit target, so PlanSearch must schedule all of them.
                degree_tree = _bdt(
                    major_req=filtered_aug,
                    qual_level=qual["level"],
                    qual_length=qual["length"],
                    major_name=name_m,
                    schedulable_major_credits=schedulable_aug_credits,
                    force_total_credits=True,
                )
            else:
                degree_tree = self._build_degree_tree(m, req_tree, campus=campus, mode=mode)

            parsed_majors_filled.append({
                "name":         m["name"],
                "url":          m.get("url", ""),
                "raw":          m,
                "requirement":  augmented_req,
                "degree_tree":  degree_tree,
            })

        generator_template = PlanGenerator(
            self.courses,
            max_credits_per_semester=max_credits_per_semester,
            max_courses_per_semester=max_courses_per_semester,
            campus=campus,
            mode=mode,
            start_year=start_year,
            start_semester=start_semester,
            no_summer=no_summer,
        )

        # preferred_electives for the filled pass includes filler codes so
        # PlanSearch's _select_electives picks them from the new pool.
        augmented_preferred = preferred_electives | frozenset(filler_codes)

        search = PlanSearch(
            courses=self.courses,
            majors=parsed_majors_filled,
            generator_template=generator_template,
            prior_completed=prior_completed,
            preferred_electives=augmented_preferred,
            excluded_courses=excluded_courses,
        )

        try:
            filled_plan = search.search()
        except ValueError:
            # Filling failed - return the original plan with the filler list.
            if transfer_credits > 0:
                base_plan.transfer_credits = transfer_credits
            return base_plan, filler_codes

        self.last_plan_stats = search.best_generator_stats

        if transfer_credits > 0:
            filled_plan.transfer_credits = transfer_credits
        return filled_plan, filler_codes

    def degree_total_credits(
        self,
        major_name: str,
    ) -> int:
        """
        Return the total credit target for the degree associated with this major.

        Uses the qualification's level and length to look up the standard Massey
        credit profile. Falls back to 360 when qualification metadata is missing.
        """
        resolved = self._resolve_major(major_name)
        if not resolved:
            return 360
        qual = self._qual_map.get(resolved[0]["name"])
        if qual is None:
            return 360
        return profile_for(qual["level"], qual["length"]).total_credits

    def free_elective_gap(
        self,
        major_name: str,
        campus: str = "D",
        mode: str = "DIS",
    ) -> int:
        """
        Return the number of additional free-elective credits needed beyond the
        major-specific courses captured in the dataset.

        Many majors include fewer credits in the scraped data than the full
        degree total because free electives (unrestricted course choices) are
        not listed on the major page. A positive return value means the student
        must self-select that many credits from the wider Massey catalogue.

        The calculation uses the minimum schedulable credits from the requirement
        tree: required course credits + elective pool *targets* (not the sum of
        all alternatives in a pool, which would overcount).

        Returns 0 when the major data fully covers the degree credit target.
        """
        resolved = self._resolve_major(major_name)
        if not resolved:
            return 0
        major = resolved[0]
        name  = major["name"]
        qual  = self._qual_map.get(name)
        if qual is None:
            return 0

        major_req = self._build_major_req_tree(major)

        # Collect per-pool credit targets (not all members) for CHOOSE_CREDITS nodes.
        elective_nodes = collect_elective_nodes(major_req)
        pool_codes: set[str] = {c for n in elective_nodes for c in n.course_codes}

        # Required (non-pool) course credits that are schedulable.
        all_codes   = collect_course_codes(major_req)
        req_codes   = all_codes - pool_codes
        req_credits = sum(
            self.courses[c].credits
            for c in req_codes
            if c in self.courses
            and any(o.campus == campus and o.mode == mode for o in self.courses[c].offerings)
        )

        # Pool contribution = min(pool.credits target, schedulable pool member credits).
        pool_credits = 0
        for node in elective_nodes:
            schedulable_in_pool = sum(
                self.courses[c].credits
                for c in node.course_codes
                if c in self.courses
                and any(o.campus == campus and o.mode == mode for o in self.courses[c].offerings)
            )
            target = node.credits if node.credits > 0 else schedulable_in_pool
            pool_credits += min(target, schedulable_in_pool)

        schedulable = req_credits + pool_credits
        profile = profile_for(qual["level"], qual["length"])
        return max(0, profile.total_credits - schedulable)

    def campus_excluded_courses(
        self,
        major_name: str,
        campus: str = "D",
        mode: str = "DIS",
    ) -> list[str]:
        """
        Return course codes that are required by this major but have no offering
        in the given campus/mode.

        These are courses the student cannot take by distance (or at the specified
        campus) and which are excluded from both scheduling and validation. The CLI
        uses this to inform the student that some requirements need on-campus study.
        """
        resolved = self._resolve_major(major_name)
        if not resolved:
            return []
        major = resolved[0]
        major_req = self._build_major_req_tree(major)
        all_codes = collect_course_codes(major_req)
        pool_codes = {
            c
            for n in collect_elective_nodes(major_req)
            if isinstance(n, ChooseCreditsRequirement)
            for c in n.course_codes
        }
        required_codes = all_codes - pool_codes
        return sorted(
            code for code in required_codes
            if code in self.courses
            and not any(o.campus == campus and o.mode == mode for o in self.courses[code].offerings)
        )

    def generate_filled_double_major_plan(
        self,
        major_name: str,
        second_major_name: str,
        max_credits_per_semester: int = 60,
        max_courses_per_semester: int | None = None,
        campus: str = "D",
        mode: str = "DIS",
        start_year: int = 2026,
        start_semester: str = "S1",
        prior_completed: frozenset = frozenset(),
        preferred_electives: frozenset = frozenset(),
        excluded_courses: frozenset = frozenset(),
        no_summer: bool = False,
        transfer_credits: int = 0,
    ) -> tuple["DegreePlan", dict, list[str]]:
        """
        Generate a combined double-major plan and auto-fill the free-elective gap.

        The combined gap is calculated as:
            max(first_degree_total, second_degree_total)
            - schedulable credits from merged requirement tree

        This ensures the student meets the higher degree's credit requirement
        (typically both are 360cr) while counting shared courses only once.

        Returns (plan, double_info, filler_codes).
        """
        from collections import Counter as _Counter
        from coursemap.domain.requirement_nodes import (
            AllOfRequirement as _AllOf,
            ChooseCreditsRequirement as _CCR,
        )
        from coursemap.optimisation.search import PlanSearch as _PlanSearch

        # --- Step 1: generate the unfilled double-major plan -----------------
        base_plan, info = self.generate_double_major_plan(
            major_name=major_name,
            second_major_name=second_major_name,
            max_credits_per_semester=max_credits_per_semester,
            max_courses_per_semester=max_courses_per_semester,
            campus=campus,
            mode=mode,
            start_year=start_year,
            prior_completed=prior_completed,
            preferred_electives=preferred_electives,
            excluded_courses=excluded_courses,
            no_summer=no_summer,
            transfer_credits=transfer_credits,
        )

        # --- Step 2: compute gap ---------------------------------------------
        first_total  = self.degree_total_credits(major_name)
        second_total = self.degree_total_credits(second_major_name)
        degree_target = max(first_total, second_total)

        credits_planned = base_plan.total_credits() + base_plan.prior_credits()
        gap = max(0, degree_target - credits_planned)
        effective_gap = max(0, gap - transfer_credits)

        if effective_gap <= 0:
            return base_plan, info, []

        # --- Step 3: find filler candidates ----------------------------------
        # Two-pass, SS-aware, pool-exclusion - mirrors generate_filled_plan.
        planned_codes = {c.code for s in base_plan.semesters for c in s.courses}
        prior_codes   = {c.code for c in base_plan.prior_completed}

        # Exclude codes in either major's own elective pools to prevent overlap.
        first_resolved_tmp  = self._resolve_major(major_name)
        second_resolved_tmp = self._resolve_major(second_major_name)
        dm_pool_codes: set[str] = set()
        for _mr in [first_resolved_tmp[0], second_resolved_tmp[0]]:
            _rt = self._build_major_req_tree(_mr)
            from coursemap.domain.requirement_utils import collect_elective_nodes as _cen2
            for _node in _cen2(_rt):
                if isinstance(_node, _CCR):
                    dm_pool_codes.update(_node.course_codes)

        excluded_all  = planned_codes | prior_codes | excluded_courses | dm_pool_codes

        prefix_counts = _Counter(code[:3] for code in planned_codes)
        prefix_rank   = {pfx: rank for rank, (pfx, _) in enumerate(prefix_counts.most_common())}
        max_level = max(
            (self.courses[c].level for c in planned_codes if c in self.courses),
            default=100,
        )

        def _dm_schedulable(course) -> bool:
            offs = [o for o in course.offerings if o.campus == campus and o.mode == mode]
            if not offs:
                return False
            if no_summer:
                return any(o.semester in ("S1", "S2") for o in offs)
            return True

        def _dm_level_ok(course) -> bool:
            return course.level <= 300 and course.level <= max_level + 100

        # Pass 1: same subject-prefix
        same_prefix_dm: list[tuple] = []
        for code, course in self.courses.items():
            if code in excluded_all or not _dm_schedulable(course) or not _dm_level_ok(course):
                continue
            pfx = code[:3]
            if pfx in prefix_rank:
                same_prefix_dm.append((0 if code in preferred_electives else 1, prefix_rank[pfx], course.level, code))
        same_prefix_dm.sort()

        filler_codes: list[str] = []
        running = 0
        for _, _, _, code in same_prefix_dm:
            if running >= effective_gap: break
            cr = self.courses[code].credits
            if running + cr > effective_gap + 14: continue
            filler_codes.append(code); running += cr

        # Pass 2: broaden to full undergrad catalogue when prefix pool runs out
        if running < effective_gap:
            selected_set = set(filler_codes)
            broad_dm: list[tuple] = []
            for code, course in self.courses.items():
                if code in excluded_all or code in selected_set: continue
                if not _dm_schedulable(course) or not _dm_level_ok(course): continue
                if code[:3] in prefix_rank: continue
                broad_dm.append((0 if code in preferred_electives else 1, course.level, code))
            broad_dm.sort()
            for _, _, code in broad_dm:
                if running >= effective_gap: break
                cr = self.courses[code].credits
                if running + cr > effective_gap + 14: continue
                filler_codes.append(code); running += cr

        if not filler_codes:
            return base_plan, info, []

        # --- Step 4: re-run the double-major plan with filler injected -------
        first_resolved  = self._resolve_major(major_name)
        second_resolved = self._resolve_major(second_major_name)
        first_major  = first_resolved[0]
        second_major = second_resolved[0]

        first_req  = self._build_major_req_tree(first_major)
        second_req = self._build_major_req_tree(second_major)

        filler_pool = _CCR(credits=running, course_codes=frozenset(filler_codes))
        merged_req = _AllOf((first_req, second_req, filler_pool))

        def _major_subtree(tree: "RequirementNode") -> "RequirementNode":
            from coursemap.domain.requirement_nodes import AllOfRequirement as _A, TotalCreditsRequirement as _T
            if isinstance(tree, _A) and len(tree.children) == 2:
                non_total = [c for c in tree.children if not isinstance(c, _T)]
                if len(non_total) == 1:
                    return non_total[0]
            return tree

        first_tree  = self._build_degree_tree(first_major,  first_req,  campus=campus, mode=mode)
        second_tree = self._build_degree_tree(second_major, second_req, campus=campus, mode=mode)

        # Add TotalCreditsRequirement for the combined plan so PlanSearch
        # schedules up to the degree target (typically 360cr).
        from coursemap.rules.degree_rules import TotalCreditsRequirement as _TCR
        merged_tree = _AllOf((
            _TCR(degree_target),
            _major_subtree(first_tree),
            _major_subtree(second_tree),
        ))

        parsed_combined = [{
            "name": f"{first_major['name']} + {second_major['name']}",
            "url":  "",
            "raw":  {},
            "requirement":  merged_req,
            "degree_tree":  merged_tree,
        }]

        generator_template = PlanGenerator(
            self.courses,
            max_credits_per_semester=max_credits_per_semester,
            max_courses_per_semester=max_courses_per_semester,
            campus=campus,
            mode=mode,
            start_year=start_year,
            start_semester=start_semester,
            no_summer=no_summer,
        )

        augmented_preferred = preferred_electives | frozenset(filler_codes)
        search = _PlanSearch(
            courses=self.courses,
            majors=parsed_combined,
            generator_template=generator_template,
            prior_completed=prior_completed,
            preferred_electives=augmented_preferred,
            excluded_courses=excluded_courses,
        )

        try:
            filled_plan = search.search()
        except ValueError:
            return base_plan, info, filler_codes

        self.last_plan_stats = search.best_generator_stats

        if prior_completed:
            prior_objects = tuple(
                self.courses[c] for c in prior_completed if c in self.courses
            )
            filled_plan = type(filled_plan)(
                semesters=filled_plan.semesters,
                prior_completed=prior_objects,
            )

        if transfer_credits > 0:
            filled_plan.transfer_credits = transfer_credits

        return filled_plan, info, filler_codes

    def student_excluded_required_courses(
        self,
        major_name: str,
        excluded_courses: frozenset,
        campus: str = "D",
        mode: str = "DIS",
    ) -> list[str]:
        """
        Return required course codes that the student has excluded via --exclude
        but which are mandatory for the degree (COURSE nodes, not pool members).

        The CLI uses this to warn students that their exclusions conflict with
        degree requirements, rather than letting the plan silently fail validation.
        """
        resolved = self._resolve_major(major_name)
        if not resolved:
            return []
        major = resolved[0]
        major_req = self._build_major_req_tree(major)
        all_codes = collect_course_codes(major_req)
        pool_codes = {
            c
            for n in collect_elective_nodes(major_req)
            if isinstance(n, ChooseCreditsRequirement)
            for c in n.course_codes
        }
        required_codes = all_codes - pool_codes
        return sorted(code for code in excluded_courses if code in required_codes)
