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
