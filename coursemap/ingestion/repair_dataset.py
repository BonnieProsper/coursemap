"""
repair_dataset.py: offline data repair for coursemap datasets.

Run from repo root:
    python -m coursemap.ingestion.repair_dataset [--force | --reset] [--dry-run]

Flags are checked by substring match on sys.argv, not argparse -- the
recognised flags are:
    --force / --reset   discard any existing .bak files and re-repair from
                         the live datasets, instead of re-repairing from the
                         previously-saved originals.
    --dry-run           run every pass and log what WOULD change, but never
                         write courses.json / majors.json.
There is no --help; passing an unrecognised flag is silently ignored and
the repair runs anyway.
"""

from __future__ import annotations
import json, logging, shutil
from pathlib import Path
from collections import Counter, defaultdict, deque

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

_DS = Path(__file__).resolve().parents[2] / "datasets"
_NOISE = {"627739", "219206"}


# ── I/O ────────────────────────────────────────────────────────────────────────

def _load(name: str):
    with open(_DS / name, encoding="utf-8") as f:
        return json.load(f)

def _save(name: str, data) -> None:
    path = _DS / name
    bak = path.with_suffix(".json.bak")
    if not bak.exists():
        shutil.copy2(path, bak)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    log.info("Wrote %s  (%d items)", path.name, len(data))

def _clean(raw: str) -> str:
    s = str(raw).strip()
    if s.lower().startswith("course code:"):
        s = s[len("course code:"):].strip()
    return s


# ── PREREQUISITE REPAIR ────────────────────────────────────────────────────────

def repair_prereqs(courses: list[dict]) -> tuple[list[dict], dict]:
    """
    Pass 1 – basic cleaning:
      • strip self-refs, admission noise, phantom codes, duplicates
      • strip inverted-level edges (where prereq.level > own.level)
        – these are always scraper errors

    `prerequisites` can be in one of four shapes depending on which scraper
    produced it (see dataset_loader.parse_prereqs for the canonical
    handling this mirrors):
        None                  -> no prerequisite, nothing to clean
        "115230"              -> a single code, already structured
        {"op": ..., "args": [...]} -> AND/OR expression, already structured
        ["115230", "627739"]  -> OLD flat-list format from the original
                                  regex scraper -- THIS is the only shape
                                  the noise-stripping logic below actually
                                  applies to.

    Structured (str/dict) prerequisites are already accurate (parsed
    directly from the page's "Prerequisite courses" section) and are passed
    through untouched -- running list-shaped noise heuristics on them would
    silently destroy real AND/OR semantics (e.g. flattening "159201 OR
    159234" into something that reads as an AND), which is strictly worse
    than doing nothing. Only genuinely list-shaped data is cleaned here.
    """
    cm = {c["course_code"]: c for c in courses}
    stats: dict[str, int] = defaultdict(int)

    out = []
    for c in courses:
        code = c["course_code"]
        own_lvl = c.get("course_level") or 0
        raw_prereqs = c.get("prerequisites")

        if raw_prereqs is None or isinstance(raw_prereqs, (str, dict)):
            # Already structured (or genuinely empty) -- not this pass's job.
            stats["already_structured"] += 1
            out.append(c)
            continue

        if not isinstance(raw_prereqs, list):
            # Unknown shape -- don't guess, leave it untouched rather than crash.
            stats["unknown_shape"] += 1
            out.append(c)
            continue

        seen: set[str] = set()
        clean: list[str] = []

        for raw in raw_prereqs:
            p = _clean(raw)
            if not p or p == code:
                stats["self"] += 1; continue
            if p in _NOISE:
                stats["noise"] += 1; continue
            if p not in cm:
                stats["phantom"] += 1; continue
            if p in seen:
                stats["dup"] += 1; continue
            # Remove inverted-level edges (scraper noise: page grabbed higher-level codes)
            p_lvl = cm[p].get("course_level") or 0
            if p_lvl > own_lvl and p_lvl - own_lvl >= 100:
                stats["inverted_lvl"] += 1; continue
            # Remove cross-subject prerequisites that span large discipline gaps.
            # Threshold: subject prefix numeric diff > 50 = different faculty = scraper noise.
            # e.g. Health(214) -> Animal Science(117): diff=97 -> strip (noise)
            #      CS(159) -> Stats(161): diff=2 -> keep (genuine academic relationship)
            #      Accounting(110) -> Finance(115): diff=5 -> keep (related business subjects)
            # Also strip same-level cross-subject (always noise regardless of distance).
            if p[:3] != code[:3] and own_lvl > 0:
                try:
                    prefix_diff = abs(int(p[:3]) - int(code[:3]))
                except ValueError:
                    prefix_diff = 999
                if p_lvl >= own_lvl or prefix_diff > 50:
                    stats["cross_noise"] += 1; continue
            seen.add(p)
            clean.append(p)
            stats["kept"] += 1

        out.append({**c, "prerequisites": clean})

    return out, dict(stats)


def _raw_prereq_hard_codes(raw, known: set[str]) -> list[str]:
    """
    Extract the codes that are HARD requirements (must be scheduled before
    this course) from a raw JSON prerequisites value, in any of the four
    shapes courses.json uses: None, a single code string, an AND/OR dict
    `{"op": ..., "args": [...]}`, or a flat list (old scraper format).

    For OR nodes, only codes present in every branch are "hard" -- mirrors
    the same convention used by dataset_validator._prereq_hard_codes and
    planner/generator._prereq_codes_or_aware, just operating on raw dicts
    instead of parsed PrerequisiteExpression / domain objects, since this
    module runs before anything is parsed into domain form.

    Used only for cycle detection in break_all_cycles -- NOT a general
    substitute for dataset_loader.parse_prereqs, which remains the one
    place that builds the real PrerequisiteExpression tree the app uses.
    """
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw] if raw in known else []
    if isinstance(raw, list):
        return [p for p in raw if p in known]
    if isinstance(raw, dict):
        op = raw.get("op", "AND").upper()
        branch_sets = [set(_raw_prereq_hard_codes(a, known)) for a in raw.get("args", [])]
        branch_sets = [b for b in branch_sets if b or op == "AND"]
        if op == "OR":
            trackable = [b for b in branch_sets if b]
            if not trackable:
                return []
            result = trackable[0]
            for b in trackable[1:]:
                result = result & b
            return list(result)
        # AND (default): union of all branches
        result: set[str] = set()
        for b in branch_sets:
            result |= b
        return list(result)
    return []


def _remove_raw_prereq_code(raw, victim: str):
    """
    Return a copy of a raw prerequisites value with `victim` removed,
    preserving AND/OR structure where present. Used by break_all_cycles to
    break a cycle edge without flattening structured data the way a naive
    `[p for p in prereqs if p != victim]` would.
    """
    if raw is None:
        return None
    if isinstance(raw, str):
        return None if raw == victim else raw
    if isinstance(raw, list):
        return [p for p in raw if p != victim]
    if isinstance(raw, dict):
        new_args = [_remove_raw_prereq_code(a, victim) for a in raw.get("args", [])]
        new_args = [a for a in new_args if a is not None]
        if not new_args:
            return None
        if len(new_args) == 1:
            return new_args[0]
        return {**raw, "args": new_args}
    return raw


def break_all_cycles(courses: list[dict]) -> tuple[list[dict], int]:
    """
    Pass 2 – use Kahn's topological sort to detect ALL cycle nodes, then
    iteratively remove the 'lightest' back-edges (fewest downstream dependents)
    until no cycles remain.  Guarantees a DAG.

    Cycle *detection* uses only hard-required codes (AND-of-all, OR-only-if-
    in-every-branch) via _raw_prereq_hard_codes, so an OR alternative that
    would never actually deadlock scheduling doesn't get treated as a cycle
    edge. Cycle *breaking* removes the offending code from the raw structure
    via _remove_raw_prereq_code, which preserves AND/OR shape rather than
    collapsing it to a flat list.
    """
    def kahn_cycle_nodes(hard_map: dict[str, list[str]], all_codes: set[str]) -> set[str]:
        in_deg: dict[str, int] = defaultdict(int)
        children: dict[str, list[str]] = defaultdict(list)
        for code, ps in hard_map.items():
            for p in ps:
                if p in all_codes:
                    children[p].append(code)
                    in_deg[code] += 1
        q = deque(c for c in all_codes if in_deg[c] == 0)
        visited: set[str] = set()
        while q:
            n = q.popleft(); visited.add(n)
            for ch in children[n]:
                in_deg[ch] -= 1
                if in_deg[ch] == 0:
                    q.append(ch)
        return all_codes - visited

    cm = {c["course_code"]: c for c in courses}
    all_codes = set(cm)
    raw_map = {c["course_code"]: c.get("prerequisites") for c in courses}
    hard_map = {code: _raw_prereq_hard_codes(raw, all_codes) for code, raw in raw_map.items()}
    total_removed = 0

    for _iteration in range(200):          # safety cap
        cycle_nodes = kahn_cycle_nodes(hard_map, all_codes)
        if not cycle_nodes:
            break

        # For each cycle node, find edges that point INTO the cycle
        # and remove the one on the course with the highest level
        # (heuristic: a high-level course should not be prereq of a low-level one)
        removed_any = False
        for code in sorted(cycle_nodes):
            bad = [p for p in hard_map.get(code, []) if p in cycle_nodes]
            if bad:
                # Remove the first bad prereq edge; re-run Kahn next iteration
                victim = bad[0]
                raw_map[code] = _remove_raw_prereq_code(raw_map[code], victim)
                hard_map[code] = [p for p in hard_map[code] if p != victim]
                log.debug("Break cycle: remove %s→%s", code, victim)
                total_removed += 1
                removed_any = True
                break   # restart Kahn after each removal

        if not removed_any:
            # Shouldn't happen, but guard infinite loop
            break

    remaining = kahn_cycle_nodes(hard_map, all_codes)
    if remaining:
        log.warning("Could not fully break cycles; %d nodes remain", len(remaining))

    repaired = [{**c, "prerequisites": raw_map[c["course_code"]]} for c in courses]
    return repaired, total_removed


# ── MAJORS REPAIR ──────────────────────────────────────────────────────────────

def _dominant_level(codes: list[str], cm: dict) -> int:
    lvls = [cm[c].get("course_level", 0) for c in codes if c in cm and cm[c].get("course_level")]
    return Counter(lvls).most_common(1)[0][0] if lvls else 200

def repair_majors(majors: list[dict], cm: dict) -> tuple[list[dict], dict]:
    """
    • Strip 'Course code:' prefix from all pool codes
    • Remove phantom pool codes
    • Expand pools with same-subject, same-level courses from catalogue
      (level-aware: 200-lvl pools only get 200-lvl additions, etc.)
    """
    stats: dict[str, int] = defaultdict(int)

    def collect_required(req: dict) -> set[str]:
        codes: set[str] = set()
        if req.get("type") == "COURSE":
            c = _clean(req.get("course_code", ""))
            if c: codes.add(c)
        for ch in req.get("children", []):
            codes |= collect_required(ch)
        return codes

    def fix_pool(node: dict, excluded: set[str]) -> dict:
        raw = node.get("course_codes", [])
        credits = node.get("credits", 0)

        # Clean + dedupe + phantom-strip
        cleaned: list[str] = []
        seen: set[str] = set()
        for r in raw:
            c = _clean(r)
            if not c or c in seen: continue
            if c not in cm:
                stats["pool_phantom"] += 1; continue
            seen.add(c); cleaned.append(c)
            stats["pool_prefix"] += 1

        dom_lvl = _dominant_level(cleaned, cm)
        prefixes = {c[:3] for c in cleaned if len(c) == 6}

        expanded = list(cleaned)
        exp_set = set(cleaned)

        # Only expand SINGLE-prefix pools.
        # Multi-prefix pools are intentionally curated interdisciplinary selections
        # (e.g. health programs choosing across 147/150/179 subject codes).
        # Expanding them would add unrelated courses and break credit targets.
        if len(prefixes) == 1:
            pfx = next(iter(prefixes))
            for code in sorted(cm):
                if (code.startswith(pfx)
                        and cm[code].get("course_level", 0) == dom_lvl
                        and cm[code].get("credits", 0) > 0
                        and code not in excluded
                        and code not in exp_set):
                    expanded.append(code); exp_set.add(code)
                    stats["pool_added"] += 1

        return {"type": "CHOOSE_CREDITS", "credits": credits, "course_codes": expanded}

    def fix_node(node: dict, excluded: set[str]) -> dict:
        if node.get("type") == "CHOOSE_CREDITS":
            return fix_pool(node, excluded)
        if node.get("type") == "COURSE":
            return {"type": "COURSE", "course_code": _clean(node.get("course_code", ""))}
        return {**node, "children": [fix_node(ch, excluded) for ch in node.get("children", [])]}

    out = []
    for m in majors:
        req = m.get("requirement", {})
        required = collect_required(req)
        out.append({**m, "requirement": fix_node(req, required)})
    return out, dict(stats)


# ── MANUALLY-VERIFIED PREREQUISITE FIXES ───────────────────────────────────────
#
# These are NOT inferred or auto-repaired. Each entry was individually checked
# against the live Massey course page (and, where the prerequisite is a
# qualification-wide pattern, cross-checked against several qualification
# regulation pages that all independently state the same prerequisite) during
# a manual audit. See DATA_QUALITY.md, "Prerequisite Coverage", for the
# equivalent earlier fix list (159302, 159352, 158222, 159333, etc.) that this
# follows the same approach as.
#
# Massey's real prerequisite text for these courses uses two patterns this
# schema cannot represent exactly (see DATA_QUALITY.md's note on this):
#   - "1611xx" / similarly a 3-digit-prefix wildcard meaning "any course
#     starting with this prefix", approximated here as an OR over every
#     course code in courses.json that currently starts with that prefix.
#     This is an approximation: it will under-match if Massey adds a new
#     1611xx course later without this list being refreshed, and it cannot
#     represent the "at this level" qualifier separately from "this prefix"
#     (the schema has no construct for prefix+level jointly; OR-ing the
#     specific existing courses is the closest available approximation).
#   - "Two 1613xx courses" (161380), a choose-2-from-pool requirement, which
#     this schema cannot express as a prerequisite at all (same limitation
#     documented for 159333's "two of 158222, 1592xx"). Approximated here as
#     a single representative course (161304, the most foundational of the
#     1613xx pool) rather than the full choose-2 semantics. This is a known,
#     deliberate under-approximation, not a verified match.
_VERIFIED_PREREQ_FIXES: dict[str, dict | str] = {
    # 161222 Design and Analysis of Experiments. Stored as [] (empty).
    # Real: "1611xx" (https://www.massey.ac.nz/study/courses/design-and-analysis-of-experiments-161222/
    # and https://www.massey.ac.nz/massey/learning/programme-course/course.cfm?course_code=161222,
    # both: "Prerequisite(s): 1611xx General Prerequisite: At least 45 credits from 100 level.")
    "161222": {"op": "OR", "args": ["161101", "161111", "161122", "161140"]},

    # 161250 Data Analysis. Stored as ["161111"] (one specific course, too narrow).
    # Real: "1611xx or 297101" (https://www.massey.ac.nz/study/courses/data-analysis-161250/
    # and consistently across BSc/BA/GradDip Information Sciences qualification
    # regulation pages, e.g. massey.ac.nz/about/.../qualification-regulations/bachelor-of-science/)
    "161250": {"op": "OR", "args": ["161101", "161111", "161122", "161140", "297101"]},

    # 161251 Regression Modelling. Stored as ["161111"] (one specific course, too narrow).
    # Real: "1611xx or 297101" (https://www.massey.ac.nz/study/courses/regression-modelling-161251/
    # and the same qualification regulation pages as 161250 above. Both consistently
    # list "1611xx or 297101" for 161251).
    "161251": {"op": "OR", "args": ["161101", "161111", "161122", "161140", "297101"]},

    # 161380 Statistical Analysis Project. Stored as [] (empty).
    # Real: "Two 1613xx courses" (https://www.massey.ac.nz/study/courses/statistical-analysis-project-161380/
    # and the Graduate Diploma in Applied Statistics qualification regulations page).
    # APPROXIMATED as a single representative 1613xx course, 161304 (see
    # module-level note above) rather than true choose-2 semantics, which
    # this schema cannot express. This course is restricted to Graduate
    # Diploma in Applied Statistics students only and has no offerings in
    # the current dataset, so the approximation has no practical effect on
    # any DIS undergraduate plan. Included for completeness/correctness of
    # the stored data, not because any current plan generation depends on it.
    "161380": "161304",

    # 160212 Discrete Mathematics. Stored as a flat AND of every code in
    # both clauses (i.e. requiring all of 160101/160102/160103/160105/
    # 160111/160112/160132/160133/228171/228172 AND 159101/159171/230112),
    # the same "comma-list misread as AND" bug already fixed elsewhere in
    # this file. Real (https://www.massey.ac.nz/study/courses/discrete-
    # mathematics-160212/, "Course planning information" > "Prerequisite
    # courses"): "One of (160101, 160102, 160103, 160105, 160111, 160112,
    # 160132, 160133, 228171 or 228172) and one of (159101, 159171 or
    # 230112)" - two independent "one of" clauses, not one big AND. This
    # was also the cause of Mathematics - Bachelor of Science appearing
    # self-contradictory (it directly requires both 160101 and 160102,
    # which the mis-scraped AND then also forced in via 160212's
    # prerequisite chain, and 160105 mutually restricts both) - fixed by
    # this correction alone, no scheduler change needed.
    "160212": {
        "op": "AND",
        "args": [
            {"op": "OR", "args": [
                "160101", "160102", "160103", "160105", "160111",
                "160112", "160132", "160133", "228171", "228172",
            ]},
            {"op": "OR", "args": ["159101", "159171", "230112"]},
        ],
    },

    # 123201 Chemical Energetics. Stored as a flat nested AND of every code
    # in both clauses (effectively requiring nine courses at once,
    # including 160101 AND 160102 AND 160105 simultaneously - impossible in
    # isolation, since 160105 mutually restricts both). Real
    # (https://www.massey.ac.nz/study/courses/chemical-energetics-123201/):
    # "One of (123102, 123105, 124104 or 123172) and one of (160101,
    # 160102, 160105, 160132 or 160133)". Unlike the other entries in this
    # registry, this is NOT a parser limitation - parse_prerequisite_text()
    # already returns the correct tree for this exact phrasing (verified
    # directly, same "one of (...) and one of (...)" pattern already fixed
    # for 123305). This entry is only a stopgap for stale data scraped
    # before that fix shipped; a fresh refresh_prerequisites run should
    # make it redundant (and this stays correct either way, since applying
    # an already-correct value is a no-op).
    "123201": {
        "op": "AND",
        "args": [
            {"op": "OR", "args": ["123102", "123105", "124104", "123172"]},
            {"op": "OR", "args": ["160101", "160102", "160105", "160132", "160133"]},
        ],
    },

    # The following four were all stored as flat ANDs of every code
    # across all clauses - the same bug as 160212/123201 above, each
    # confirmed a genuine restriction conflict (two of the required
    # codes mutually restrict each other, impossible as scraped). All
    # four real requirements are plain "one of" lists, live-verified.

    # 117226 Performance Animal Nutrition.
    # https://www.massey.ac.nz/study/courses/performance-animal-nutrition-117226/
    # "One of 117152, 117153, 117155 or 194101"
    "117226": {"op": "OR", "args": ["117152", "117153", "117155", "194101"]},

    # 117243 Animal Reproduction and Lactation in Livestock.
    # https://www.massey.ac.nz/study/courses/animal-reproduction-and-lactation-in-livestock-117243/
    # "One of 117153, 117155 or 194101"
    "117243": {"op": "OR", "args": ["117153", "117155", "194101"]},

    # 120303 Plant Diversity.
    # https://www.massey.ac.nz/study/courses/plant-diversity-120303/
    # "One of (120201, 120218, 120219, 196205, 196207 or 203210)"
    "120303": {"op": "OR", "args": ["120201", "120218", "120219", "196205", "196207", "203210"]},

    # 286321 Responses to Training in the Equine Athlete.
    # https://www.massey.ac.nz/study/courses/responses-to-training-in-the-equine-athlete-286321/
    # "One of 117152, 117153, 117155 or 194101"
    "286321": {"op": "OR", "args": ["117152", "117153", "117155", "194101"]},

    # 267860 Professional Inquiry. Stored as AND(267740, 267782, 267783,
    # OR(267741, 267721)) - requiring all four/five prerequisite courses.
    # Real (https://www.massey.ac.nz/study/all-qualifications-and-degrees/
    # master-of-arts-PMART/education-PMART1SEDCT1/, "Courses you can enrol
    # in" > Part Two: Coursework Pathway > 267860 > Prerequisites): "One
    # of 267740, 267782, 267783, 267741 or 267721" - the whole group is a
    # single OR, not an AND wrapping a smaller OR. Found while trying to
    # apply the correlated-pathway fix to Education - MA (see
    # test_education_ma_still_has_wrong_part_two_course_codes in
    # test_integration.py): 267740/267782/267783 don't exist in the
    # current dataset, so the mis-scraped AND currently has no visible
    # effect (unknown codes resolve as satisfied) - fixing it anyway for
    # correctness, in case any of those three ever get added to the
    # dataset in a future refresh, which would otherwise silently make
    # this course permanently unschedulable via a compound requirement
    # nobody intended.
    "267860": {"op": "OR", "args": ["267740", "267782", "267783", "267741", "267721"]},
}


def apply_verified_prereq_fixes(courses: list[dict]) -> tuple[list[dict], int]:
    """
    Apply the manually-verified prerequisite corrections in
    _VERIFIED_PREREQ_FIXES. Unlike repair_prereqs (which only cleans
    already-scraped data), this adds prerequisite information that was
    never scraped at all. Each entry was individually checked against a
    live Massey source. Idempotent: running this twice has no further
    effect, since it simply overwrites with the same verified value.
    """
    fixes = _VERIFIED_PREREQ_FIXES
    out = []
    n_fixed = 0
    for c in courses:
        code = c["course_code"]
        if code in fixes:
            out.append({**c, "prerequisites": fixes[code]})
            n_fixed += 1
        else:
            out.append(c)
    return out, n_fixed


# ── CREDIT / LEVEL NORMALISATION ───────────────────────────────────────────────

# Massey's Swiftype `qual_length` field (scraped into qualifications.json's
# `length`) is a coarse duration category from Massey's own backend, not a
# precise total-credits proxy - the rest of this codebase assumes
# total_credits = length * 120 (see rules/degree_rules.py's DegreeProfile
# table), which breaks for any qualification whose real total isn't a whole
# number of years. Every one of the 47 Level-9 (Master's) qualifications in
# qualifications.json reports length=2 except a handful explicitly marked 1
# year - which is itself a strong signal that `qual_length` is a rounded/
# bucketed category (probably "up to N years"), not a literal figure, for at
# least some of them. Only the entries below have actually been checked
# against a live subject page; the other ~40 Level-9 entries have NOT been
# verified either way and may or may not be affected - see DATA_QUALITY.md.
_VERIFIED_QUALIFICATION_LENGTH_FIXES: dict[str, float] = {
    # PMART Master of Arts. Stored as length=2 (implying 240cr via the
    # length*120 default). Real: 180cr / "3 semesters of full-time study"
    # (https://www.massey.ac.nz/study/all-qualifications-and-degrees/master-of-arts-PMART/geography-PMART1SGGRP1/
    # and .../education-PMART1SEDCT1/, both state, word for word: "Massey's
    # Master of Arts is 180 credits. This means you can complete an MA in 3
    # semesters of full-time study."). 1.5 years, not 2. Requires a matching
    # (9, 1.5) entry in rules/degree_rules.py's _DEGREE_PROFILES, which
    # exists.
    "PMART": 1.5,
    # PMSCN Master of Science. Stored as length=2 (240cr). Real, per its own
    # qualification page: "Massey University's Master of Science is a
    # 180-credit master qualification (a 240-credit MSc is also available)."
    # (https://www.massey.ac.nz/study/all-qualifications-and-degrees/master-of-science-PMSCN/)
    # 180cr is the standard/headline qualification; 240cr is a real but
    # separate, alternate pathway this project has no way to ask the
    # student about or select between (no pathway-choice input exists
    # anywhere in the planner). Defaulting to 180cr matches every subject
    # page checked so far (Chemistry, Mathematics, Animal Science,
    # Agricultural Science, Biological Sciences - all describe the
    # identical Part One (60cr) -> Part Two (120cr thesis) = 180cr
    # structure), and is consistent with the qualification's own official
    # regulations page. Requires the same (9, 1.5) DegreeProfile entry as
    # PMART.
    "PMSCN": 1.5,
    # The four below were found via a systematic sweep of the qualification
    # regulations pages (https://www.massey.ac.nz/about/university-calendar-
    # and-regulations/qualification-regulations/), which state the total
    # credits explicitly and authoritatively (e.g. "shall follow a...
    # programme of study... totalling at least N credits") - a more direct
    # source than the description-page prose PMART/PMSCN were checked
    # against, and available for every Master's qualification at once via
    # the same index. All four other Level-9-length-2 qualifications
    # checked in the same sweep (PMAPC Master of Applied Social Work, PMCLR
    # Master of Clinical Practice (Nursing), PMSCW Master of Social Work)
    # were confirmed correct at 240cr and need no entry here.
    #
    # PMSPL Master of Speech and Language Therapy. Regulations: "courses
    # totalling at least 180 credits" (.../qualification-regulations/
    # master-of-speech-and-language-therapy/).
    "PMSPL": 1.5,
    # PMFDS Master of Food Safety and Quality. Regulations: "courses
    # totalling at least 180 credits" (.../qualification-regulations/
    # master-of-food-safety-and-quality/). Corroborated by a third-party
    # aggregator independently describing it as an "18 months" programme.
    "PMFDS": 1.5,
    # PMANL Master of Analytics. Regulations: "courses totalling at least
    # 180 credits" (.../qualification-regulations/master-of-analytics/).
    "PMANL": 1.5,
    # PMFNN Master of Finance. Regulations: "courses totalling at least 180
    # credits" (.../qualification-regulations/master-of-finance/). All
    # three subjects (Financial Analytics and Research, Financial
    # Technology, Risk Analytics) are independently listed as 180 credits
    # each on the same page.
    "PMFNN": 1.5,
    # Second batch from the same sweep, same source pattern (each
    # qualification's own official regulations page at
    # .../qualification-regulations/<slug>/, stating "totalling at least
    # N credits" or equivalent). Confirmed correct at 240cr in this batch
    # and needing no entry: PMCLP Clinical Psychology, PMMRV Māori Visual
    # Arts, PMRSE Resource and Environmental Planning, PMNRS Nursing,
    # PMPBH Public Health, PMPRA Professional Accountancy (Chartered
    # Accountant), PMBSA Executive MBA, PMEDV Educational and Developmental
    # Psychology (240cr is the default pathway; a 180cr alternate pathway
    # exists only for candidates already holding a specific named diploma,
    # which this project has no way to ask about - same unresolved-pathway
    # situation as PMSCN above).
    #
    # All of the following are the identical 240-stored/180-actual pattern
    # as PMSPL/PMFDS/PMANL/PMFNN above unless noted:
    "PMSSD": 1.5,  # Sustainable Development Goals
    "PMCRW": 1.5,  # Creative Writing
    "PMENM": 1.5,  # Environmental Management
    "PMMNG": 1.5,  # Management
    "PMAPL": 1.5,  # Applied Linguistics
    "PMCMM": 1.5,  # Communication
    "PMEDC": 1.5,  # Education
    "PMHLM": 1.5,  # Health Service Management
    "PMINC": 1.5,  # International Security
    "PMIND": 1.5,  # International Development
    "PMINS": 1.5,  # Information Sciences
    "PMDSG": 1.5,  # Design
    "PMPRC": 1.5,  # Professional Accountancy
    "PMBSS": 1.5,  # Business Studies
    "PMHLS": 1.5,  # Health Science
    "PMVTT": 1.5,  # Veterinary Studies
    "PMEMM": 1.5,  # Emergency Management
    "PMCNT": 1.5,  # Construction
    "PMSCA": 1.5,  # Screen Arts
    "PMCMS": 1.5,  # Commercial Music
    "PMMRS": 1.5,  # Māori Studies (confirmed via its own description page:
    # "Time to complete: 1 year 6 months full-time (180 credits)" -
    # regulations-page search for this one didn't surface the total
    # directly, so the description page was used instead, same standard
    # as PMART/PMSCN).
    # PMFNA Master of Fine Arts. Regulations: 180 credits (Part One 60cr +
    # Part Two 120cr thesis). One older cached search snippet showed 240cr
    # for this qualification with no visible date; the current dated
    # regulations page (checked directly) says 180 and is internally
    # consistent with the 60+120 Part structure, so it was trusted over
    # the undated snippet. Worth a second look if this ever looks off.
    "PMFNA": 1.5,
    # PMSPT Master of Specialist Teaching. Regulations: 180cr is the default
    # pathway; shorter alternate pathways (120cr) exist for candidates with
    # specific prior qualifications, same unresolved-pathway caveat as
    # PMSCN/PMEDV above.
    "PMSPT": 1.5,
    # PMCNS Master of Counselling. Different magnitude from every other
    # entry here: regulations state 120 credits total, not 180 - stored
    # length=2 (240cr) is 2x too high, not 1.33x. Reuses the existing
    # (9, 1) DegreeProfile entry (120cr) rather than (9, 1.5).
    "PMCNS": 1.0,
    # Final two from the sweep, completing all 41 originally-unverified
    # Level-9-length-2 qualifications. Same 240-stored/180-actual pattern:
    "PMAGC": 1.5,  # Agribusiness
    "PMFDT": 1.5,  # Food Technology (default pathway; 120cr alt pathway
    # exists for candidates admitted via a specific route, same
    # unresolved-pathway caveat as PMSCN/PMEDV/PMSPT above)
}


def apply_verified_qualification_length_fixes(
    qualifications: list[dict],
) -> tuple[list[dict], int]:
    """
    Apply the manually-verified qualification-length corrections in
    _VERIFIED_QUALIFICATION_LENGTH_FIXES. Each entry was individually
    checked against a live Massey subject page, not assumed from the
    scraped `qual_length` field. Idempotent, same as
    apply_verified_prereq_fixes.
    """
    fixes = _VERIFIED_QUALIFICATION_LENGTH_FIXES
    out = []
    n_fixed = 0
    for q in qualifications:
        code = q.get("qual_code")
        if code in fixes:
            out.append({**q, "length": fixes[code]})
            n_fixed += 1
        else:
            out.append(q)
    return out, n_fixed


# Two majors under length-fixed qualifications hit the exact same stale-240
# arithmetic (fixed_credits + old_open_credits == 240) but produce a NEGATIVE
# corrected value: their own explicitly-modelled, non-open pools already sum
# to 210cr, more than the real 180cr total, even before the trailing open
# node is touched at all. Deliberately NOT auto-corrected by this function:
# unlike the other 48 (a single mechanical subtraction, self-evidently
# required once the qualification total was already verified), guessing a
# fix here would mean inventing curriculum content without checking it,
# exactly what _VERIFIED_PREREQ_FIXES-style corrections are meant to avoid.
#
# Two majors used to be listed here (Occupational Health and Safety and
# Māori Health - Master of Health Science), hitting the same stale-240
# arithmetic and producing a NEGATIVE corrected value: their own
# explicitly-modelled, non-open pools already summed to 210cr, more than
# the real 180cr total, even before the trailing open node was touched.
# Deliberately not auto-corrected by this function at the time - guessing
# a fix would have meant inventing curriculum content without checking it.
#
# Both are now fixed. Live-verifying (rather than guessing) confirmed both
# were instances of the same Geography/Sociology-MA "Part One credit range
# correlated with Part Two pathway choice" structural gap - and that this
# was NOT a domain-model limitation at all: AnyOfRequirement nesting
# AllOfRequirement children already expresses two correlated choices
# correctly, with zero code changes needed anywhere. Both majors' whole
# requirement trees were hand re-encoded directly in majors.json (not by
# this function), the same way as Geography, Sociology, and Ecology and
# Conservation before them - see test_ohs_and_maori_health_correlated_
# pathway_fixed in test_integration.py and DATA_QUALITY.md for the full
# story. Kept as an empty frozenset (not deleted) so a future dataset
# refresh that reintroduces the stale-240 pattern for either of these two,
# or for any other major, has an obvious place to list it again rather
# than silently falling through fix_stale_free_elective_pool_sizes's
# negative-value skip with no explanation on file.
_UNRESOLVED_NEGATIVE_ELECTIVE_POOL_MAJORS: frozenset[str] = frozenset()


def fix_stale_free_elective_pool_sizes(
    majors: list[dict],
    qualifications: list[dict],
    specialisations: list[dict],
    cm: dict,
) -> tuple[list[dict], int]:
    """
    Fixes the root cause behind the Chemistry/Mathematics - MSc "free
    electives" DegreeValidator failure, and 48 other majors sharing the
    identical bug, discovered while investigating that pair.

    Every major's requirement tree that has a trailing, unconstrained
    CHOOSE_CREDITS node (`course_codes: []`, meaning "any course, from
    anywhere" - the generic free-electives placeholder) was sized as
    (240 - explicitly-modelled credits), using qual_length's OLD, WRONG
    240cr-implying value for every qualification later corrected by
    _VERIFIED_QUALIFICATION_LENGTH_FIXES - not the real total. Confirmed
    empirically, not assumed: every one of the 51 majors under a
    length-fixed qualification with exactly one such open node sums to
    precisely 240 (explicitly-modelled credits + the stored open-node size),
    with zero exceptions - this is exactly what you'd expect if whoever (or
    whatever process) built majors.json derived "remaining credits for free
    electives" from the qualification's stored (wrong) total at build time,
    baking in a stale absolute number instead of a value computed against
    the correct one.

    This is a mechanical correction, not a new claim about curriculum
    content: the open node's whole job is "whatever's left over to reach
    the total", and the total itself was already independently
    live-verified via _VERIFIED_QUALIFICATION_LENGTH_FIXES - correcting the
    placeholder to be internally consistent with that already-verified
    total doesn't require checking a live page again. Only applies to
    majors with a plain ALL_OF root and exactly one open CHOOSE_CREDITS
    node; anything else (already-ANY_OF majors like Geography/English/
    Sociology, multi-open-node majors, non-ALL_OF roots) is left untouched.
    Idempotent: recomputes from the unchanged non-open credits each time,
    so running twice is a no-op.

    _UNRESOLVED_NEGATIVE_ELECTIVE_POOL_MAJORS lists the 3 majors where this
    arithmetic goes negative (their own non-open pools already exceed the
    real total) - explicitly skipped rather than guessed at. If a future
    dataset update produces a new negative case not in that set, it's
    skipped too (never silently written as a negative or clamped-to-zero
    credit target) and will show up as a lower fix count here to catch it.
    """
    fixed_quals, _ = apply_verified_qualification_length_fixes(qualifications)
    qual_by_code = {q["qual_code"]: q for q in fixed_quals}
    title_to_qualcode = {s["title"]: s["qual_code"] for s in specialisations}
    fixed_qual_codes = set(_VERIFIED_QUALIFICATION_LENGTH_FIXES)

    out = []
    n_fixed = 0
    for m in majors:
        qual_code = title_to_qualcode.get(m["name"])
        req = m.get("requirement")
        if (
            qual_code not in fixed_qual_codes
            or m["name"] in _UNRESOLVED_NEGATIVE_ELECTIVE_POOL_MAJORS
            or not req
            or req.get("type") != "ALL_OF"
        ):
            out.append(m)
            continue

        fixed_credits = 0
        open_nodes = []
        for child in req.get("children", []):
            if child["type"] == "COURSE":
                fixed_credits += cm.get(child["course_code"], {}).get("credits", 0)
            elif child["type"] == "CHOOSE_CREDITS":
                if child.get("course_codes"):
                    fixed_credits += child["credits"]
                else:
                    open_nodes.append(child)

        if len(open_nodes) != 1:
            out.append(m)
            continue

        real_total = int(qual_by_code[qual_code]["length"] * 120)
        new_credits = real_total - fixed_credits
        if new_credits < 0 or new_credits == open_nodes[0]["credits"]:
            out.append(m)
            continue

        target = open_nodes[0]
        new_children = [
            {**c, "credits": new_credits} if c is target else c
            for c in req["children"]
        ]
        out.append({**m, "requirement": {**req, "children": new_children}})
        n_fixed += 1
    return out, n_fixed


def normalise_courses(courses: list[dict]) -> list[dict]:
    out = []
    for c in courses:
        # float→int credits
        try:
            f = float(c.get("credits", 0))
            cred = int(f) if f == int(f) else c["credits"]
        except (ValueError, TypeError):
            cred = c.get("credits", 0)

        # fill `level` from `course_level`
        lvl = c.get("level") or c.get("course_level")
        out.append({**c, "credits": cred, "level": lvl})
    return out


# ── MAIN ───────────────────────────────────────────────────────────────────────

def main() -> None:
    # Always work from originals (*.bak) if they exist, else from live files
    import sys
    force = "--force" in sys.argv or "--reset" in sys.argv
    dry_run = "--dry-run" in sys.argv

    def src(name):
        bak = _DS / (name + ".bak")
        if force and bak.exists():
            log.info("--force: removing stale backup %s", bak.name)
            bak.unlink()
        return bak.name if bak.exists() else name

    log.info("Loading datasets …")
    orig_courses: list[dict] = _load(src("courses.json"))
    courses: list[dict] = orig_courses
    majors:  list[dict] = _load(src("majors.json"))
    qualifications: list[dict] = _load(src("qualifications.json"))
    specialisations: list[dict] = _load(src("specialisations.json"))
    cm = {c["course_code"]: c for c in courses}

    # ── courses ──
    log.info("Pass 1 – clean prerequisites (%d courses) …", len(courses))
    courses, stats1 = repair_prereqs(courses)
    log.info("  %s", stats1)

    log.info("Pass 1.5 – apply manually-verified prerequisite fixes …")
    courses, n_verified_fixed = apply_verified_prereq_fixes(courses)
    log.info("  %d course(s) corrected (see _VERIFIED_PREREQ_FIXES)", n_verified_fixed)

    log.info("Pass 2 – break prerequisite cycles …")
    courses, n_broken = break_all_cycles(courses)
    log.info("  broke %d edges", n_broken)

    log.info("Pass 3 – normalise credits/level …")
    courses = normalise_courses(courses)

    # rebuild cm with clean data for pool expansion
    cm = {c["course_code"]: c for c in courses}

    # ── majors ──
    log.info("Repairing %d majors …", len(majors))
    before = sum(
        len(node.get("course_codes", []))
        for m in majors
        for node in _iter_nodes(m["requirement"])
        if node.get("type") == "CHOOSE_CREDITS"
    )
    majors, stats2 = repair_majors(majors, cm)
    after = sum(
        len(node.get("course_codes", []))
        for m in majors
        for node in _iter_nodes(m["requirement"])
        if node.get("type") == "CHOOSE_CREDITS"
    )
    log.info("  pool codes: %d → %d (+%d)  %s", before, after, after - before, stats2)

    # ── qualifications ──
    log.info("Pass 4 – apply manually-verified qualification-length fixes …")
    qualifications, n_qual_fixed = apply_verified_qualification_length_fixes(qualifications)
    log.info(
        "  %d qualification(s) corrected (see _VERIFIED_QUALIFICATION_LENGTH_FIXES)",
        n_qual_fixed,
    )

    log.info("Pass 5 – recompute stale free-elective pool sizes …")
    majors, n_pool_fixed = fix_stale_free_elective_pool_sizes(
        majors, qualifications, specialisations, cm,
    )
    log.info(
        "  %d major(s) corrected (see fix_stale_free_elective_pool_sizes)",
        n_pool_fixed,
    )

    if dry_run:
        n_changed = sum(
            1 for a, b in zip(orig_courses, courses)
            if a.get("prerequisites") != b.get("prerequisites")
        )
        log.info(
            "--dry-run: not writing files. %d course(s) would have their "
            "prerequisites changed; %d major pool code(s) would be added.",
            n_changed, after - before,
        )
        log.info("Run without --dry-run to actually write courses.json / majors.json.")
        return

    log.info("Saving …")
    _save("courses.json", courses)
    _save("majors.json", majors)
    _save("qualifications.json", qualifications)
    log.info("Done.  Run `coursemap validate` to verify.")


def _iter_nodes(req: dict):
    yield req
    for ch in req.get("children", []):
        yield from _iter_nodes(ch)



def remove_ghost_prerequisites(courses: list[dict]) -> int:
    """
    Remove prerequisite references to courses that have no offerings at all.

    A course with zero offerings is retired or a data ghost. It can never be
    taken, so requiring it as a prerequisite permanently blocks all downstream
    courses. This is the most common cause of plan-bloat in the scheduler.

    Returns the number of courses fixed.
    """
    no_offerings: set[str] = {
        c["course_code"] for c in courses if not c.get("offerings")
    }

    def _prune(node):
        if node is None:
            return None
        if isinstance(node, str):
            return None if node in no_offerings else node
        if isinstance(node, list):
            cleaned = [p for p in node if p not in no_offerings]
            return cleaned if cleaned else None
        if isinstance(node, dict):
            op = node.get("op")
            args = [_prune(a) for a in node.get("args", [])]
            args = [a for a in args if a is not None]
            if not args:
                return None
            if len(args) == 1:
                return args[0]
            return {"op": op, "args": args}
        return node

    fixed = 0
    for course in courses:
        prereqs = course.get("prerequisites")
        if not prereqs:
            continue
        pruned = _prune(prereqs)
        if pruned != prereqs:
            course["prerequisites"] = pruned
            fixed += 1

    return fixed


if __name__ == "__main__":
    main()
