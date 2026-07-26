"""
Tests for coursemap.ingestion.repair_dataset.

repair_prereqs and break_all_cycles must handle all four shapes the
`prerequisites` field takes across courses.json: None, a single code
string, an AND/OR dict ({"op": ..., "args": [...]}), and the old flat-list
format from the original regex scraper. Before this test file existed,
repair_prereqs crashed outright on None (`for raw in c.get("prerequisites",
[])` iterates None when the key is present-but-null, which is true for 256
real courses in the bundled dataset) and break_all_cycles silently
flattened AND/OR structure into nonsense. See repair_dataset.py docstrings
for the full story.
"""
import pytest

from coursemap.ingestion.repair_dataset import (
    repair_prereqs,
    break_all_cycles,
    apply_verified_prereq_fixes,
    _VERIFIED_PREREQ_FIXES,
    apply_verified_qualification_length_fixes,
    _VERIFIED_QUALIFICATION_LENGTH_FIXES,
    fix_stale_free_elective_pool_sizes,
    _UNRESOLVED_NEGATIVE_ELECTIVE_POOL_MAJORS,
    _raw_prereq_hard_codes,
    _remove_raw_prereq_code,
    main,
)


def _course(code, prereqs=None, level=200, offerings=True):
    return {
        "course_code": code,
        "title": f"Course {code}",
        "credits": 15,
        "course_level": level,
        "level": level,
        "offerings": [{"campus_code": "D", "delivery_mode": "DIS", "semester": "Semester 1"}] if offerings else [],
        "prerequisites": prereqs,
    }


# Realistic-looking 6-digit codes sharing a subject prefix (159xxx), so the
# cross-subject-noise heuristic in repair_prereqs (intended for real Massey
# codes, keyed on a 3-digit subject prefix) doesn't misfire on short
# alphabetic test codes the way "A"/"B" would.
A, B, C, D, X = "159100", "159101", "159102", "159103", "159104"


# ---------------------------------------------------------------------------
# repair_prereqs: must not crash on any real-world shape
# ---------------------------------------------------------------------------

def test_repair_prereqs_handles_none():
    """The real bug: prerequisites=None must not crash `for raw in c.get(...)`."""
    courses = [_course(A, prereqs=None), _course(B, prereqs=[A])]
    out, stats = repair_prereqs(courses)
    a = next(c for c in out if c["course_code"] == A)
    assert a["prerequisites"] is None
    assert stats["already_structured"] == 1


def test_repair_prereqs_handles_dict_and_or_untouched():
    """Structured AND/OR dicts must pass through byte-for-byte, never flattened."""
    expr = {"op": "OR", "args": [A, B]}
    courses = [_course(A), _course(B), _course(C, prereqs=expr)]
    out, stats = repair_prereqs(courses)
    c = next(c for c in out if c["course_code"] == C)
    assert c["prerequisites"] == expr
    assert stats["already_structured"] >= 1


def test_repair_prereqs_handles_single_string():
    courses = [_course(A), _course(B, prereqs=A)]
    out, stats = repair_prereqs(courses)
    b = next(c for c in out if c["course_code"] == B)
    assert b["prerequisites"] == A


def test_repair_prereqs_cleans_old_flat_list_format():
    """The old scraper format IS this function's actual job: strip noise/dupes/phantoms."""
    courses = [
        _course(A),
        _course(B, prereqs=[A, A, "999999", B, "627739"]),  # dup, phantom, self, admission-noise
    ]
    out, stats = repair_prereqs(courses)
    b = next(c for c in out if c["course_code"] == B)
    assert b["prerequisites"] == [A]
    assert stats["dup"] == 1
    assert stats["phantom"] == 1
    assert stats["self"] == 1
    assert stats["noise"] == 1


def test_repair_prereqs_mixed_shapes_in_same_dataset():
    """The real dataset has all four shapes simultaneously. Must not crash."""
    courses = [
        _course(A, prereqs=None),
        _course(B, prereqs=A),
        _course(C, prereqs={"op": "AND", "args": [A, B]}),
        _course(D, prereqs=[A, B]),
    ]
    out, stats = repair_prereqs(courses)
    assert len(out) == 4
    by_code = {c["course_code"]: c for c in out}
    assert by_code[A]["prerequisites"] is None
    assert by_code[B]["prerequisites"] == A
    assert by_code[C]["prerequisites"] == {"op": "AND", "args": [A, B]}
    assert by_code[D]["prerequisites"] == [A, B]


# ---------------------------------------------------------------------------
# _raw_prereq_hard_codes: OR-aware extraction from raw JSON shapes
# ---------------------------------------------------------------------------

def test_hard_codes_none():
    assert _raw_prereq_hard_codes(None, {A, B}) == []


def test_hard_codes_single_string():
    assert _raw_prereq_hard_codes(A, {A, B}) == [A]


def test_hard_codes_and_is_union():
    result = set(_raw_prereq_hard_codes({"op": "AND", "args": [A, B]}, {A, B}))
    assert result == {A, B}


def test_hard_codes_or_is_intersection_of_trackable_branches():
    """OR(A, B): neither A nor B is individually required, so the hard set is empty."""
    result = _raw_prereq_hard_codes({"op": "OR", "args": [A, B]}, {A, B})
    assert result == []


def test_hard_codes_or_with_shared_dependency():
    """OR(AND(A,X), AND(B,X)): X is required by every branch, so it IS hard."""
    expr = {
        "op": "OR",
        "args": [
            {"op": "AND", "args": [A, X]},
            {"op": "AND", "args": [B, X]},
        ],
    }
    result = _raw_prereq_hard_codes(expr, {A, B, X})
    assert result == [X]


def test_hard_codes_flat_list():
    assert set(_raw_prereq_hard_codes([A, B], {A, B})) == {A, B}


# ---------------------------------------------------------------------------
# _remove_raw_prereq_code: structure-preserving removal
# ---------------------------------------------------------------------------

def test_remove_code_from_list():
    assert _remove_raw_prereq_code([A, B], A) == [B]


def test_remove_code_from_string():
    assert _remove_raw_prereq_code(A, A) is None
    assert _remove_raw_prereq_code(A, B) == A


def test_remove_code_collapses_single_remaining_branch():
    expr = {"op": "AND", "args": [A, B]}
    assert _remove_raw_prereq_code(expr, A) == B


def test_remove_code_preserves_or_structure():
    expr = {"op": "OR", "args": [A, B, C]}
    result = _remove_raw_prereq_code(expr, B)
    assert result == {"op": "OR", "args": [A, C]}


# ---------------------------------------------------------------------------
# break_all_cycles: must use hard-required codes only, and preserve structure
# ---------------------------------------------------------------------------

def test_break_cycles_no_op_on_acyclic_graph():
    courses = [
        _course(A, prereqs=None),
        _course(B, prereqs=A),
        _course(C, prereqs={"op": "OR", "args": [A, B]}),
    ]
    out, n_removed = break_all_cycles(courses)
    assert n_removed == 0
    by_code = {c["course_code"]: c for c in out}
    assert by_code[C]["prerequisites"] == {"op": "OR", "args": [A, B]}


def test_break_cycles_detects_and_breaks_simple_cycle():
    courses = [
        _course(A, prereqs=B),
        _course(B, prereqs=A),
    ]
    out, n_removed = break_all_cycles(courses)
    assert n_removed >= 1
    # Confirm the result is now acyclic.
    out2, n_removed2 = break_all_cycles(out)
    assert n_removed2 == 0


def test_break_cycles_does_not_treat_or_alternative_as_cycle():
    """
    OR(A, B) where B happens to require A back is fine *as long as the OR
    branch through A doesn't*. Hard-code extraction must not manufacture a
    phantom cycle out of an OR alternative nobody is forced to take.
    """
    courses = [
        _course(A, prereqs=None),
        _course(B, prereqs={"op": "OR", "args": [A, C]}),
        _course(C, prereqs=B),
    ]
    # C -> B is hard. B -> {A or C} is NOT hard (OR, not every branch shared).
    # So there should be no cycle detected here.
    out, n_removed = break_all_cycles(courses)
    assert n_removed == 0


# ---------------------------------------------------------------------------
# main(): dry-run must never write, and must not crash on the real dataset
# ---------------------------------------------------------------------------

def test_dry_run_does_not_write_files(tmp_path, monkeypatch):
    import json
    import coursemap.ingestion.repair_dataset as rd

    courses = [_course(A, prereqs=None), _course(B, prereqs=A)]
    majors = [{"name": "Test Major", "requirement": {"type": "COURSE", "course_code": A}}]

    (tmp_path / "courses.json").write_text(json.dumps(courses), encoding="utf-8")
    (tmp_path / "majors.json").write_text(json.dumps(majors), encoding="utf-8")
    (tmp_path / "qualifications.json").write_text(json.dumps([]), encoding="utf-8")
    (tmp_path / "specialisations.json").write_text(json.dumps([]), encoding="utf-8")

    monkeypatch.setattr(rd, "_DS", tmp_path)
    monkeypatch.setattr("sys.argv", ["repair_dataset.py", "--dry-run"])

    before_courses = (tmp_path / "courses.json").read_text(encoding="utf-8")
    before_majors = (tmp_path / "majors.json").read_text(encoding="utf-8")

    main()

    assert (tmp_path / "courses.json").read_text(encoding="utf-8") == before_courses
    assert (tmp_path / "majors.json").read_text(encoding="utf-8") == before_majors
    # --dry-run must not even create a .bak (nothing was saved)
    assert not (tmp_path / "courses.json.bak").exists()


def test_real_dataset_repair_is_idempotent_and_preserves_and_or(tmp_path, monkeypatch):
    """
    Regression test for the exact bug this whole module was rewritten for:
    running repair_dataset against the REAL bundled dataset must not crash
    on None-shaped prerequisites, and must leave already-correct AND/OR
    expressions (the ones documented as manually fixed in DATA_QUALITY.md)
    byte-for-byte unchanged.
    """
    import json
    import shutil
    import coursemap.ingestion.repair_dataset as rd
    from pathlib import Path

    real_datasets = Path(__file__).resolve().parents[1] / "datasets"
    for name in ("courses.json", "majors.json", "qualifications.json", "specialisations.json"):
        shutil.copy2(real_datasets / name, tmp_path / name)

    monkeypatch.setattr(rd, "_DS", tmp_path)
    monkeypatch.setattr("sys.argv", ["repair_dataset.py"])

    with open(tmp_path / "courses.json", encoding="utf-8") as f:
        before = {c["course_code"]: c.get("prerequisites") for c in json.load(f)}

    main()  # must not raise

    with open(tmp_path / "courses.json", encoding="utf-8") as f:
        after = {c["course_code"]: c.get("prerequisites") for c in json.load(f)}

    # The documented-correct AND/OR fixes must survive untouched.
    for code in ("159302", "159352", "159342", "159336"):
        if code in before:
            assert after[code] == before[code], f"{code} prerequisites changed unexpectedly"


# ---------------------------------------------------------------------------
# apply_verified_prereq_fixes: manually-verified Statistics prerequisite
# corrections (161222, 161250, 161251, 161380, see DATA_QUALITY.md,
# "The 45cr Level-Progression Rule" section and CHANGELOG.md for the
# source citations each fix is based on)
# ---------------------------------------------------------------------------

def test_verified_fixes_applies_every_documented_code():
    """Every code in _VERIFIED_PREREQ_FIXES must actually get corrected,
    and codes not in the fix list must be left completely untouched."""
    courses = [
        _course("161222", prereqs=[]),
        _course("161250", prereqs=["161111"]),
        _course("161251", prereqs=["161111"]),
        _course("161380", prereqs=[]),
        _course("160212", prereqs=["160101"]),
        _course("123201", prereqs=["123102"]),
        _course("117226", prereqs=["117152"]),
        _course("117243", prereqs=["117153"]),
        _course("120303", prereqs=["120201"]),
        _course("286321", prereqs=["117152"]),
        _course("999999", prereqs=["161111"]),  # not in the fix list, must be untouched
    ]
    fixed, n = apply_verified_prereq_fixes(courses)
    by_code = {c["course_code"]: c for c in fixed}

    assert n == len(_VERIFIED_PREREQ_FIXES)
    for code, expected in _VERIFIED_PREREQ_FIXES.items():
        if code in by_code:
            assert by_code[code]["prerequisites"] == expected
    assert by_code["999999"]["prerequisites"] == ["161111"], (
        "A course not in _VERIFIED_PREREQ_FIXES was modified"
    )


def test_verified_fixes_is_idempotent():
    """Running the fix twice must produce exactly the same result as once.
    these are corrections, not cumulative transformations."""
    courses = [_course(code, prereqs=[]) for code in _VERIFIED_PREREQ_FIXES]
    once,  n1 = apply_verified_prereq_fixes(courses)
    twice, n2 = apply_verified_prereq_fixes(once)
    assert n1 == n2 == len(_VERIFIED_PREREQ_FIXES)
    assert once == twice


# ---------------------------------------------------------------------------
# apply_verified_qualification_length_fixes: manually-verified qualification
# length corrections (PMART / Master of Arts, see DATA_QUALITY.md and
# rules/degree_rules.py's (9, 1.5) DegreeProfile entry for the source
# citations this is based on)
# ---------------------------------------------------------------------------

def test_qualification_length_fixes_applies_every_documented_code():
    """Every qual_code in _VERIFIED_QUALIFICATION_LENGTH_FIXES must actually
    get corrected, and qual_codes not in the fix list must be untouched."""
    quals = [{"qual_code": c, "title": c, "length": 2} for c in _VERIFIED_QUALIFICATION_LENGTH_FIXES]
    quals.append({"qual_code": "PMNRS", "title": "Master of Nursing", "length": 2})
    fixed, n = apply_verified_qualification_length_fixes(quals)
    by_code = {q["qual_code"]: q for q in fixed}

    assert n == len(_VERIFIED_QUALIFICATION_LENGTH_FIXES)
    for code, expected in _VERIFIED_QUALIFICATION_LENGTH_FIXES.items():
        assert by_code[code]["length"] == expected
    assert by_code["PMNRS"]["length"] == 2, (
        "A qualification not in _VERIFIED_QUALIFICATION_LENGTH_FIXES was modified"
    )


def test_qualification_length_fixes_is_idempotent():
    """Running the fix twice must produce exactly the same result as once."""
    quals = [{"qual_code": c, "length": 2} for c in _VERIFIED_QUALIFICATION_LENGTH_FIXES]
    once, n1 = apply_verified_qualification_length_fixes(quals)
    twice, n2 = apply_verified_qualification_length_fixes(once)
    assert n1 == n2 == len(_VERIFIED_QUALIFICATION_LENGTH_FIXES)
    assert once == twice


def test_pmart_length_fix_produces_180cr_profile():
    """
    Regression test tying the two halves of this fix together: PMART's
    corrected length (1.5) must actually resolve to a 180cr DegreeProfile,
    not silently fall through to the length*120 default (which would
    coincidentally also give 180 - this checks the real (9, 1.5) table
    entry is used, not the fallback, by checking level constraints aren't
    silently dropped the way the fallback does).
    """
    from coursemap.rules.degree_rules import profile_for, _DEGREE_PROFILES

    assert (9, 1.5) in _DEGREE_PROFILES, (
        "(9, 1.5) must be a real table entry, not rely on the length*120 fallback"
    )
    profile = profile_for(9, 1.5)
    assert profile.total_credits == 180


def test_pmcns_length_fix_produces_120cr_profile():
    """
    Same tie-together as test_pmart_length_fix_produces_180cr_profile, for
    the (9, 1.0) profile - PMCNS (Master of Counselling) is the first real
    qualification in _VERIFIED_QUALIFICATION_LENGTH_FIXES to use it, so
    nothing previously exercised this path.
    """
    from coursemap.rules.degree_rules import profile_for, _DEGREE_PROFILES

    assert (9, 1.0) in _DEGREE_PROFILES, (
        "(9, 1.0) must be a real table entry, not rely on the length*120 fallback"
    )
    profile = profile_for(9, 1.0)
    assert profile.total_credits == 120


def test_verified_fixes_only_touches_listed_codes():
    """Courses not present in _VERIFIED_PREREQ_FIXES must be returned
    byte-for-byte identical (same dict, not just equal prerequisites)."""
    untouched = _course("110109", prereqs=None)
    fixed, n = apply_verified_prereq_fixes([untouched])
    assert n == 0
    assert fixed[0] == untouched


def test_verified_fixes_161222_is_or_of_current_1611xx_courses():
    """
    161222's real prerequisite is the prefix pattern "1611xx" (verified
    against https://www.massey.ac.nz/study/courses/design-and-analysis-of-experiments-161222/
    "Prerequisite(s): 1611xx General Prerequisite: At least 45 credits
    from 100 level."). The schema has no prefix-pattern construct (same
    limitation as 158222/159333 in DATA_QUALITY.md), so it's approximated
    as an OR of the specific 1611xx courses that exist in the dataset.
    """
    fix = _VERIFIED_PREREQ_FIXES["161222"]
    assert fix["op"] == "OR"
    assert set(fix["args"]) == {"161101", "161111", "161122", "161140"}


def test_verified_fixes_real_dataset_201250_and_161251_load_without_crashing():
    """
    Sanity check against the real dataset_loader parsing path: the OR-dict
    shape used by these fixes must parse into a valid PrerequisiteExpression,
    not just look right as raw JSON.
    """
    from coursemap.ingestion.dataset_loader import parse_prereqs

    for code in ("161222", "161250", "161251"):
        expr = parse_prereqs(_VERIFIED_PREREQ_FIXES[code], own_code=code, own_level=200)
        assert expr is not None
        # OR-aware satisfaction: any one of the prefix-matched courses should satisfy it
        assert expr.is_satisfied({"161111"})
        assert not expr.is_satisfied(set())


# ---------------------------------------------------------------------------
# fix_stale_free_elective_pool_sizes (see repair_dataset.py's docstring for
# the full root-cause story: every one of 51 majors under a length-fixed
# qualification had its "free electives from anywhere" placeholder sized
# against the qualification's OLD 240cr total, not the corrected one)
# ---------------------------------------------------------------------------

def _cm(codes_credits):
    return {code: {"course_code": code, "credits": cr} for code, cr in codes_credits.items()}


def test_fix_stale_free_elective_pool_sizes_corrects_chemistry_shaped_major():
    """Chemistry MSc's real shape: two 30cr compulsory courses + a 120cr
    thesis pool + a stale 60cr open node (30+30+120+60=240, the OLD wrong
    total) - should become 0cr (180-180) against the corrected 180cr
    total."""
    quals = [{"qual_code": "PMSCN", "title": "Master of Science", "length": 2}]
    specs = [{"title": "Chemistry – Master of Science", "qual_code": "PMSCN"}]
    majors = [{
        "name": "Chemistry – Master of Science",
        "requirement": {
            "type": "ALL_OF",
            "children": [
                {"type": "COURSE", "course_code": "123711"},
                {"type": "COURSE", "course_code": "123713"},
                {"type": "CHOOSE_CREDITS", "credits": 120, "course_codes": ["123899"]},
                {"type": "CHOOSE_CREDITS", "credits": 60, "course_codes": []},
            ],
        },
    }]
    cm = _cm({"123711": 30, "123713": 30, "123899": 120})

    fixed, n = fix_stale_free_elective_pool_sizes(majors, quals, specs, cm)
    assert n == 1
    open_node = fixed[0]["requirement"]["children"][-1]
    assert open_node["credits"] == 0
    assert open_node["course_codes"] == []


def test_fix_stale_free_elective_pool_sizes_corrects_mathematics_shaped_major():
    """Mathematics MSc's real shape: a 120cr thesis pool + a stale 120cr
    open node (120+120=240) - should become 60cr (180-120) against the
    corrected total."""
    quals = [{"qual_code": "PMSCN", "title": "Master of Science", "length": 2}]
    specs = [{"title": "Mathematics – Master of Science", "qual_code": "PMSCN"}]
    majors = [{
        "name": "Mathematics – Master of Science",
        "requirement": {
            "type": "ALL_OF",
            "children": [
                {"type": "CHOOSE_CREDITS", "credits": 120, "course_codes": ["160899"]},
                {"type": "CHOOSE_CREDITS", "credits": 120, "course_codes": []},
            ],
        },
    }]
    cm = _cm({"160899": 120})

    fixed, n = fix_stale_free_elective_pool_sizes(majors, quals, specs, cm)
    assert n == 1
    assert fixed[0]["requirement"]["children"][-1]["credits"] == 60


def test_fix_stale_free_elective_pool_sizes_skips_known_negative_majors():
    """The 3 majors in _UNRESOLVED_NEGATIVE_ELECTIVE_POOL_MAJORS have their
    OWN non-open pools already exceeding the real total (a distinct,
    unresolved bug) - must be left completely untouched, not clamped or
    guessed at."""
    name = next(iter(_UNRESOLVED_NEGATIVE_ELECTIVE_POOL_MAJORS))
    quals = [{"qual_code": "PMSCN", "title": "Master of Science", "length": 2}]
    specs = [{"title": name, "qual_code": "PMSCN"}]
    original_req = {
        "type": "ALL_OF",
        "children": [
            {"type": "CHOOSE_CREDITS", "credits": 210, "course_codes": ["999999"]},
            {"type": "CHOOSE_CREDITS", "credits": 30, "course_codes": []},
        ],
    }
    majors = [{"name": name, "requirement": original_req}]
    cm = _cm({"999999": 210})

    fixed, n = fix_stale_free_elective_pool_sizes(majors, quals, specs, cm)
    assert n == 0
    assert fixed[0]["requirement"] == original_req


def test_fix_stale_free_elective_pool_sizes_skips_qualifications_not_in_fix_table():
    """A major under a qualification never touched by
    _VERIFIED_QUALIFICATION_LENGTH_FIXES must be left alone, even with the
    same open-node shape - there's no verified 'correct total' to recompute
    against."""
    quals = [{"qual_code": "PDSCN", "title": "Postgraduate Diploma", "length": 1}]
    specs = [{"title": "Untouched Subject – Some Diploma", "qual_code": "PDSCN"}]
    original_req = {
        "type": "ALL_OF",
        "children": [
            {"type": "COURSE", "course_code": "111111"},
            {"type": "CHOOSE_CREDITS", "credits": 90, "course_codes": []},
        ],
    }
    majors = [{"name": "Untouched Subject – Some Diploma", "requirement": original_req}]
    cm = _cm({"111111": 30})

    fixed, n = fix_stale_free_elective_pool_sizes(majors, quals, specs, cm)
    assert n == 0
    assert fixed[0]["requirement"] == original_req


def test_fix_stale_free_elective_pool_sizes_is_idempotent():
    quals = [{"qual_code": "PMSCN", "title": "Master of Science", "length": 2}]
    specs = [{"title": "Chemistry – Master of Science", "qual_code": "PMSCN"}]
    majors = [{
        "name": "Chemistry – Master of Science",
        "requirement": {
            "type": "ALL_OF",
            "children": [
                {"type": "COURSE", "course_code": "123711"},
                {"type": "COURSE", "course_code": "123713"},
                {"type": "CHOOSE_CREDITS", "credits": 120, "course_codes": ["123899"]},
                {"type": "CHOOSE_CREDITS", "credits": 60, "course_codes": []},
            ],
        },
    }]
    cm = _cm({"123711": 30, "123713": 30, "123899": 120})

    once, n1 = fix_stale_free_elective_pool_sizes(majors, quals, specs, cm)
    twice, n2 = fix_stale_free_elective_pool_sizes(once, quals, specs, cm)
    assert n1 == 1
    assert n2 == 0  # already correct on the second pass, nothing left to fix
    assert once == twice


def test_fix_stale_free_elective_pool_sizes_leaves_multi_open_node_majors_alone():
    """A major with more than one open CHOOSE_CREDITS node is a shape this
    function has never seen in the real dataset - don't guess which one is
    the 'real' free-electives placeholder, leave both untouched."""
    quals = [{"qual_code": "PMSCN", "title": "Master of Science", "length": 2}]
    specs = [{"title": "Hypothetical – Master of Science", "qual_code": "PMSCN"}]
    original_req = {
        "type": "ALL_OF",
        "children": [
            {"type": "CHOOSE_CREDITS", "credits": 30, "course_codes": []},
            {"type": "CHOOSE_CREDITS", "credits": 30, "course_codes": []},
        ],
    }
    majors = [{"name": "Hypothetical – Master of Science", "requirement": original_req}]
    fixed, n = fix_stale_free_elective_pool_sizes(majors, quals, specs, _cm({}))
    assert n == 0
    assert fixed[0]["requirement"] == original_req
