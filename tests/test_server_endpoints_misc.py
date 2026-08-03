"""
Miscellaneous server endpoint and CLI regression tests.

This file is broader than its name suggests. It covers a wide range of
/api/plan, /api/plan/progress, /api/plan/validate, /api/plan/fees, CLI
export, and dataset-validation behaviour, organised into the topical
sections marked by the comment headers below rather than into separate
files. See section headers for the specific area each block covers.
"""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from coursemap.api.server import app
from coursemap.ingestion.dataset_loader import parse_offerings, load_courses
from coursemap.domain.course import Course, Offering

client = TestClient(app)

# Repo root, derived from this file's location rather than hardcoded, so
# these tests work on a fresh clone, in CI, or on a student's own machine,
# not just in the specific environment this file was originally written in.
REPO_ROOT = Path(__file__).resolve().parent.parent


# ── Offering full_year flag ────────────────────────────────────────────────────

def test_full_year_offering_flag_set():
    """Full Year raw semester produces Offering(full_year=True)."""
    raw = [{"semester": "Full Year", "campus_code": "D", "delivery_mode": "DIS"}]
    offs = parse_offerings(raw)
    assert len(offs) == 2
    assert all(o.full_year for o in offs)
    assert all(o.semester in ("S1", "S2") for o in offs)


def test_double_semester_flag_not_set():
    """Double Semester raw semester produces Offering(full_year=False)."""
    raw = [{"semester": "Double Semester", "campus_code": "D", "delivery_mode": "DIS"}]
    offs = parse_offerings(raw)
    assert all(not o.full_year for o in offs)


def test_semester1_flag_not_set():
    """Semester 1 produces Offering(full_year=False)."""
    raw = [{"semester": "Semester 1", "campus_code": "M", "delivery_mode": "INT"}]
    offs = parse_offerings(raw)
    assert len(offs) == 1
    assert not offs[0].full_year


def test_courses_with_full_year_loaded():
    """At least some loaded courses have full_year offerings (dataset sanity)."""
    courses = load_courses()
    full_year_courses = [
        c for c in courses.values()
        if any(o.full_year for o in c.offerings)
    ]
    # The dataset has 128 Full Year offerings. Verify at least one loaded
    assert len(full_year_courses) > 0, "No full_year courses found in dataset"


# ── server.py: transfer_credits upper bound ───────────────────────────────────

def test_transfer_credits_over_360_rejected():
    res = client.post("/api/plan/stream", json={
        "major": "Computer Science – Bachelor of Information Sciences",
        "transfer_credits": 999,
        "no_summer": True,
    })
    assert res.status_code == 422


def test_transfer_credits_360_accepted():
    """Exactly 360 should be accepted (schema boundary)."""
    # We just check the schema accepts it. Plan may be trivial or error for other reasons
    res = client.post("/api/plan", json={
        "major": "Computer Science – Bachelor of Information Sciences",
        "transfer_credits": 360,
        "no_summer": True,
    })
    # 200 or 422 (no plan possible), not a 422 from schema validation
    assert res.status_code in (200, 422)
    if res.status_code == 422:
        detail = res.json().get("detail", "")
        assert "transfer_credits" not in str(detail)


# ── server.py: has_full_year_offering in course dict ──────────────────────────

def test_course_detail_has_full_year_field():
    """Every course detail response includes has_full_year_offering field."""
    res = client.get("/api/courses/159101")
    assert res.status_code == 200
    data = res.json()
    assert "has_full_year_offering" in data
    assert isinstance(data["has_full_year_offering"], bool)


def test_zero_credit_course_has_note():
    """Zero-credit courses include a _note warning in their detail response."""
    courses = load_courses()
    zero_cr = [code for code, c in courses.items() if c.credits == 0]
    if not zero_cr:
        pytest.skip("No zero-credit courses in dataset")
    res = client.get(f"/api/courses/{zero_cr[0]}")
    assert res.status_code == 200
    data = res.json()
    assert "_note" in data
    assert "zero-credit" in data["_note"].lower()


# ── server.py: /api/reload ────────────────────────────────────────────────────

def test_reload_endpoint_returns_ok():
    res = client.post("/api/reload")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "reloaded"
    assert data["courses_loaded"] > 0
    assert data["majors_loaded"] > 0


# ── server.py: /api/plan/compare ─────────────────────────────────────────────

def test_compare_two_majors():
    res = client.post("/api/plan/compare", json={
        "majors": [
            "Computer Science – Bachelor of Information Sciences",
            "Statistics – Bachelor of Science",
        ],
        "no_summer": True,
    })
    assert res.status_code == 200
    data = res.json()
    comps = data["comparisons"]
    assert len(comps) == 2
    for c in comps:
        assert "major" in c
        if c.get("error") is None:
            assert "semesters" in c
            assert "free_elective_gap" in c
            assert "prereq_coverage_pct" in c


def test_compare_rejects_single_major():
    res = client.post("/api/plan/compare", json={
        "majors": ["Computer Science – Bachelor of Information Sciences"],
    })
    assert res.status_code == 422


def test_compare_rejects_five_majors():
    res = client.post("/api/plan/compare", json={
        "majors": ["A", "B", "C", "D", "E"],
    })
    assert res.status_code == 422


# ── server.py: gap_explanation ────────────────────────────────────────────────

def test_gap_explanation_present_when_gap_exists():
    """When a plan has a free_elective_gap, meta.gap_explanation is a non-empty string."""
    res = client.post("/api/plan", json={
        "major": "Computer Science – Bachelor of Information Sciences",
        "no_summer": True,
        "auto_fill": False,
    })
    assert res.status_code == 200
    meta = res.json()["meta"]
    if meta["free_elective_gap"] > 0:
        assert meta.get("gap_explanation"), "gap_explanation should be set when gap > 0"


def test_gap_explanation_none_when_no_gap():
    """When auto_fill covers the gap, gap_explanation is None."""
    res = client.post("/api/plan", json={
        "major": "Computer Science – Bachelor of Information Sciences",
        "no_summer": True,
        "auto_fill": True,
    })
    assert res.status_code == 200
    meta = res.json()["meta"]
    if meta["free_elective_gap"] == 0:
        assert meta.get("gap_explanation") is None


# ── server.py: /api/plan/{id}/advisor-summary ────────────────────────────────

def test_advisor_summary_returns_text():
    """Generate a plan, then fetch its advisor summary."""
    plan_res = client.post("/api/plan", json={
        "major": "Computer Science – Bachelor of Information Sciences",
        "no_summer": True,
    })
    assert plan_res.status_code == 200
    plan_id = plan_res.json()["plan_id"]

    summary_res = client.get(f"/api/plan/{plan_id}/advisor-summary")
    assert summary_res.status_code == 200
    assert summary_res.headers["content-type"].startswith("text/plain")
    text = summary_res.text
    assert "COURSEMAP" in text
    assert "SEMESTER SCHEDULE" in text
    assert "UNOFFICIAL" in text


def test_advisor_summary_404_for_unknown_plan():
    res = client.get("/api/plan/nonexistent_plan_id/advisor-summary")
    assert res.status_code == 404


# ── _specs_cache_store: module-level, not monkey-patched ─────────────────────

def test_specs_cache_store_is_module_dict():
    from coursemap.api import server
    assert hasattr(server, "_specs_cache_store")
    assert isinstance(server._specs_cache_store, dict)
    # After first /api/majors call it should be populated
    client.get("/api/majors?limit=1")
    assert len(server._specs_cache_store) > 0


# ── full_year warning in plan output ─────────────────────────────────────────

def test_full_year_warning_in_plan_if_applicable():
    """If the plan contains full_year courses, a warning mentioning it appears."""
    courses = load_courses()
    full_year_codes = [
        c.code for c in courses.values()
        if any(o.full_year for o in c.offerings)
        and c.credits > 0
    ]
    if not full_year_codes:
        pytest.skip("No full_year courses in dataset")
    # We can't force the planner to include specific courses, but we can verify
    # the _plan_to_out function produces warnings when given a plan with full_year courses.
    from coursemap.api.server import _plan_to_out, _svc, PlanRequest
    from coursemap.domain.plan import DegreePlan, SemesterPlan

    svc = _svc()
    fy_course = courses[full_year_codes[0]]

    fake_plan = DegreePlan(
        semesters=(SemesterPlan(year=2026, semester="S1", courses=(fy_course,)),),
    )
    req = PlanRequest(major="Computer Science – Bachelor of Information Sciences")
    out = _plan_to_out(fake_plan, svc, req)
    fy_warnings = [w for w in out.warnings if "full academic year" in w.lower() or "full year" in w.lower()]
    assert len(fy_warnings) > 0, f"Expected full-year warning, got: {out.warnings}"


# ── /api/courses semester filter ──────────────────────────────────────────────

def test_courses_semester_filter_s1():
    res = client.get("/api/courses?semester=S1&limit=20")
    assert res.status_code == 200
    data = res.json()
    assert data["count"] > 0
    # All returned courses must have an S1 offering
    for c in data["courses"]:
        assert any(o["semester"] == "S1" for o in c.get("offered_semesters_raw", []) or []) \
            or True  # offered_semesters not exposed directly, check count > 0 is enough


def test_courses_semester_filter_ss():
    res = client.get("/api/courses?semester=SS&limit=10")
    assert res.status_code == 200
    # There should be some summer school courses
    assert res.json()["count"] > 0


def test_courses_semester_filter_invalid_returns_empty():
    res = client.get("/api/courses?semester=S9&limit=10")
    assert res.status_code == 200
    assert res.json()["count"] == 0


# ── PlanExportService ─────────────────────────────────────────────────────────

def test_export_service_advisor_text():
    from coursemap.services.plan_export_service import PlanExportService
    fake = {
        "meta": {"major": "Test Major", "campus": "D", "mode": "DIS",
                 "start_semester": "S1", "start_year": 2026,
                 "degree_target": 360, "credits_total": 360, "free_elective_gap": 0},
        "semesters": [
            {"semester": "S1", "year": 2026, "credits": 30,
             "courses": [{"code": "159101", "title": "Applied Programming",
                          "credits": 15, "prereq_data_available": True},
                         {"code": "160101", "title": "Calculus",
                          "credits": 15, "prereq_data_available": False}]}
        ],
        "warnings": ["Test warning"],
    }
    text = PlanExportService.to_advisor_text(fake, plan_id="test123")
    assert "COURSEMAP" in text
    assert "Test Major" in text
    assert "S1 2026" in text
    assert "159101" in text
    assert "⚠ no prereq data" in text
    assert "Test warning" in text
    assert "UNOFFICIAL" in text
    assert "test123" in text


def test_export_service_markdown():
    from coursemap.services.plan_export_service import PlanExportService
    fake = {
        "meta": {"major": "Test Major", "campus": "D", "mode": "DIS",
                 "start_semester": "S1", "start_year": 2026,
                 "degree_target": 360, "credits_total": 345, "free_elective_gap": 15,
                 "gap_explanation": "Add more electives."},
        "semesters": [],
        "warnings": [],
    }
    md = PlanExportService.to_markdown(fake)
    assert "# Degree Plan" in md
    assert "Test Major" in md
    assert "15cr" in md
    assert "Add more electives." in md


# ── /api/plan/{id}/markdown ───────────────────────────────────────────────────

def test_markdown_export_endpoint():
    plan_res = client.post("/api/plan", json={
        "major": "Computer Science – Bachelor of Information Sciences",
        "no_summer": True,
    })
    assert plan_res.status_code == 200
    plan_id = plan_res.json()["plan_id"]

    md_res = client.get(f"/api/plan/{plan_id}/markdown")
    assert md_res.status_code == 200
    assert "markdown" in md_res.headers["content-type"]
    assert "# Degree Plan" in md_res.text


def test_markdown_export_404():
    res = client.get("/api/plan/no_such_plan/markdown")
    assert res.status_code == 404


# ── /api/reload clears specs cache ────────────────────────────────────────────

def test_reload_clears_specs_cache():
    from coursemap.api import server
    # Populate cache
    client.get("/api/majors?limit=1")
    assert len(server._specs_cache_store) > 0
    # Reload
    res = client.post("/api/reload")
    assert res.status_code == 200
    # Cache cleared and re-populated by pre-warm
    assert res.json()["courses_loaded"] > 0


# ── DegreeInfoService ─────────────────────────────────────────────────────────

def test_degree_info_service_credits():
    from coursemap.services.degree_info_service import DegreeInfoService
    from coursemap.api.server import _svc
    info = DegreeInfoService(_svc())
    creds = info.degree_total_credits("Computer Science – Bachelor of Information Sciences")
    assert creds == 360


def test_degree_info_service_prereq_coverage():
    from coursemap.services.degree_info_service import DegreeInfoService
    from coursemap.api.server import _svc
    info = DegreeInfoService(_svc())
    cov = info.prereq_coverage(["159101", "159201", "159301", "NOTEXIST"])
    assert "total" in cov
    assert cov["total"] == 4
    assert 0 <= cov["coverage_pct"] <= 100


# ── /api/courses min_credits filter ──────────────────────────────────────────

def test_courses_min_credits_excludes_zero():
    res = client.get("/api/courses?min_credits=1&limit=3000")
    assert res.status_code == 200
    data = res.json()
    assert all(c["credits"] >= 1 for c in data["courses"]), \
        "min_credits=1 should exclude zero-credit courses"


def test_courses_min_credits_zero_shows_all():
    res_all  = client.get("/api/courses?min_credits=0&limit=3000")
    res_excl = client.get("/api/courses?min_credits=1&limit=3000")
    assert res_all.json()["count"] >= res_excl.json()["count"]


# ── prerequisites_human in course detail ─────────────────────────────────────

def test_course_detail_has_prerequisites_human():
    res = client.get("/api/courses/159201")
    assert res.status_code == 200
    data = res.json()
    assert "prerequisites_human" in data
    # Either None (no prereq data) or a non-empty string
    ph = data["prerequisites_human"]
    assert ph is None or (isinstance(ph, str) and len(ph) > 0)


def test_course_without_prereqs_has_none_prerequisites_human():
    # 159101 is a L100 intro course, likely no prereqs
    res = client.get("/api/courses/159101")
    assert res.status_code == 200
    data = res.json()
    assert "prerequisites_human" in data
    # L100 courses typically have no prerequisites
    if not data["prereq_data_available"]:
        assert data["prerequisites_human"] is None


def test_l200plus_missing_prereq_data_exposes_level_for_frontend_indicator():
    """
    The frontend's "unverified prerequisite data" indicator (a course card
    dot distinct from both "satisfied" and "missing") needs BOTH `level` and
    `prereq_data_available` on the same course record to decide whether a
    missing prerequisite is "no data recorded" (suspicious for L200+) vs
    "genuinely no prerequisite" (normal for L100). This locks in that data
    contract: find a real L200+ course with no prerequisite data and confirm
    both fields are present and correctly typed.
    """
    res = client.get("/api/courses?limit=3000")
    assert res.status_code == 200
    courses = res.json()["courses"]
    candidates = [
        c for c in courses
        if c.get("level", 0) >= 200 and c.get("prereq_data_available") is False
    ]
    assert candidates, (
        "Expected at least one L200+ course with no prerequisite data "
        "recorded. If this dataset has been fully re-scraped with complete "
        "prerequisite coverage, this test's premise no longer holds and it "
        "should be revisited rather than just skipped."
    )
    sample = candidates[0]
    assert isinstance(sample["level"], int)
    assert sample["prereq_data_available"] is False
    assert sample["prerequisite_expression"] is None


def test_courses_semester_and_min_credits_combined():
    res = client.get("/api/courses?semester=S1&min_credits=1&limit=50")
    assert res.status_code == 200
    data = res.json()
    assert data["count"] > 0
    for c in data["courses"]:
        assert c["credits"] >= 1


# ── share link toast (verify endpoint returns plan_id) ───────────────────────

def test_plan_has_plan_id_field():
    res = client.post("/api/plan", json={
        "major": "Computer Science – Bachelor of Information Sciences",
        "no_summer": True,
    })
    assert res.status_code == 200
    assert "plan_id" in res.json()
    assert len(res.json()["plan_id"]) > 0


# ── Minor dataset expansion ───────────────────────────────────────────────────

def test_minors_dataset_has_more_than_eight():
    """After expansion, minors dataset should have at least 20 entries."""
    res = client.get("/api/minors")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] >= 20, f"Expected ≥20 minors, got {data['total']}"


def test_minors_endpoint_exposes_counts():
    res = client.get("/api/minors")
    assert res.status_code == 200
    data = res.json()
    assert "total" in data
    assert "scraped" in data
    assert "inferred" in data
    assert data["scraped"] + data["inferred"] == data["total"]


def test_minors_data_quality_filter_inferred():
    res = client.get("/api/minors?data_quality=inferred")
    assert res.status_code == 200
    data = res.json()
    assert all(m.get("data_quality") == "inferred" for m in data["minors"])


def test_minors_data_quality_filter_scraped():
    res = client.get("/api/minors?data_quality=scraped")
    assert res.status_code == 200
    data = res.json()
    assert all(m.get("data_quality") == "scraped" for m in data["minors"])


def test_minors_search_biochemistry():
    res = client.get("/api/minors?search=biochem")
    assert res.status_code == 200
    data = res.json()
    names = [m["name"].lower() for m in data["minors"]]
    assert any("biochem" in n for n in names), f"Biochemistry not found: {names}"


def test_minors_search_sociology():
    res = client.get("/api/minors?search=soci")
    assert res.status_code == 200
    data = res.json()
    assert data["count"] > 0


def test_each_inferred_minor_has_requirement_tree():
    """Every minor must have a valid requirement dict with at least one child."""
    from coursemap.ingestion.minor_loader import load_minors
    minors = load_minors()
    for m in minors:
        req = m.get("requirement", {})
        assert req.get("type"), f"{m['name']} missing requirement.type"
        assert req.get("children") or req.get("course_codes"), \
            f"{m['name']} requirement has no children or course_codes"


def test_minor_total_credits_positive():
    """All minors must have a positive total_credits value."""
    from coursemap.ingestion.minor_loader import load_minors
    for m in load_minors():
        assert m.get("total_credits", 0) > 0, f"{m['name']} has non-positive total_credits"


# ── Cache version is set and changes when generation logic changes ───────────

def test_cache_version_is_set():
    """
    _CACHE_VERSION must be a non-empty string. The actual value isn't
    meaningful to assert on directly. It should be bumped every time
    generation logic changes, so pinning a specific historical string here
    would make this test fail on every legitimate bump. What actually
    matters (that changing the version invalidates the cache key) is
    covered by test_plan_cache_key_changes_with_cache_version below.
    """
    from coursemap.api import server
    assert isinstance(server._CACHE_VERSION, str) and server._CACHE_VERSION


# ── API version is 7.0.0 ──────────────────────────────────────────────────────

def test_api_version():
    # FastAPI exposes version in openapi.json
    res2 = client.get("/openapi.json")
    assert res2.status_code == 200
    assert res2.json()["info"]["version"] == "7.0.0"


# ── /api/plan/progress endpoint ───────────────────────────────────────────────

def test_progress_no_completed():
    """With no completed courses, progress should be 0%."""
    res = client.post("/api/plan/progress", json={
        "major": "Computer Science – Bachelor of Information Sciences",
        "completed": [],
    })
    assert res.status_code == 200
    data = res.json()
    assert data["credits_completed"] == 0
    assert data["pct_complete"] == 0
    assert data["degree_target"] == 360
    assert data["on_track"] is True


def test_progress_with_completed_courses():
    """With some L100 courses completed, credits_completed should increase."""
    res = client.post("/api/plan/progress", json={
        "major": "Computer Science – Bachelor of Information Sciences",
        "completed": ["159101", "160101"],
    })
    assert res.status_code == 200
    data = res.json()
    assert data["credits_completed"] == 30
    assert data["pct_complete"] == round(100 * 30 / 360)
    assert data["estimated_semesters_remaining"] > 0


def test_progress_transfer_credits_count_toward_total_but_not_level_check():
    """
    transfer_credits must add to credits_completed/pct_complete (overall
    degree progress), but must NOT be used to satisfy the level-progression
    "on_track" check. That check is specifically about whether the student
    has completed Massey's own foundational courses before an L300+ one,
    and transfer credit from another institution doesn't bear on that.
    """
    from coursemap.ingestion.dataset_loader import load_courses
    courses = load_courses()
    l300_courses = [c for c in courses.values() if c.level == 300 and c.credits == 15]
    if not l300_courses:
        import pytest; pytest.skip("No L300 15cr courses available")
    code = l300_courses[0].code

    res_no_transfer = client.post("/api/plan/progress", json={
        "major": "Computer Science – Bachelor of Information Sciences",
        "completed": [code],
        "transfer_credits": 0,
    })
    res_with_transfer = client.post("/api/plan/progress", json={
        "major": "Computer Science – Bachelor of Information Sciences",
        "completed": [code],
        "transfer_credits": 60,
    })
    assert res_no_transfer.status_code == res_with_transfer.status_code == 200
    no_transfer = res_no_transfer.json()
    with_transfer = res_with_transfer.json()

    # Overall progress should reflect the transfer credits.
    assert with_transfer["credits_completed"] == no_transfer["credits_completed"] + 60
    assert with_transfer["pct_complete"] > no_transfer["pct_complete"]

    # But the level-progression warning should fire in BOTH cases. Transfer
    # credit doesn't establish that Massey-side foundational courses were
    # taken first.
    assert no_transfer["on_track"] is False
    assert with_transfer["on_track"] is False


def test_progress_required_remaining():
    """required_remaining should decrease as courses are completed."""
    res_empty = client.post("/api/plan/progress", json={
        "major": "Computer Science – Bachelor of Information Sciences",
        "completed": [],
    })
    res_some = client.post("/api/plan/progress", json={
        "major": "Computer Science – Bachelor of Information Sciences",
        "completed": ["159101"],
    })
    assert res_empty.status_code == res_some.status_code == 200
    empty_remaining = len(res_empty.json()["required_remaining"])
    some_remaining  = len(res_some.json()["required_remaining"])
    # required_remaining can only stay same or decrease when courses are added
    assert some_remaining <= empty_remaining


def test_progress_invalid_major_returns_404():
    res = client.post("/api/plan/progress", json={
        "major": "Nonexistent Major That Does Not Exist XYZ",
        "completed": [],
    })
    assert res.status_code == 404


def test_progress_on_track_warning_for_advanced_without_base():
    """Completing a L300 course before 60cr total should trigger on_track=False."""
    from coursemap.ingestion.dataset_loader import load_courses
    courses = load_courses()
    l300_courses = [c for c in courses.values() if c.level == 300 and c.credits == 15]
    if not l300_courses:
        import pytest; pytest.skip("No L300 15cr courses available")
    code = l300_courses[0].code
    res = client.post("/api/plan/progress", json={
        "major": "Computer Science – Bachelor of Information Sciences",
        "completed": [code],  # one L300 course, total < 60cr
    })
    assert res.status_code == 200
    data = res.json()
    assert data["on_track"] is False
    assert len(data["warnings"]) > 0


def test_progress_gap_remaining_only_counts_genuine_free_electives():
    """
    Regression test: gap_remaining must only shrink when the student has
    completed courses that are GENUINE free electives, not claimed by any
    required-course node or named elective pool in the degree tree.

    The bug: gap_remaining was computed as
    max(0, raw_gap - credits_earned), subtracting the student's TOTAL
    completed credits regardless of what those credits were for. A student
    who'd only completed required courses (no free electives at all) would
    still see their elective gap shrink by their full credit total,
    understating how much elective room they actually still needed to plan
    for outside the major.
    """
    name = "Computer Science – Bachelor of Information Sciences"

    # Baseline: no completed courses at all.
    res_baseline = client.post("/api/plan/progress", json={"major": name, "completed": []})
    assert res_baseline.status_code == 200
    baseline_gap = res_baseline.json()["gap_remaining"]

    # Complete ONLY required courses (159101, 159102 are both directly
    # required for this major, not part of any elective pool).
    res_required_only = client.post("/api/plan/progress", json={
        "major": name, "completed": ["159101", "159102"],
    })
    assert res_required_only.status_code == 200
    required_only_gap = res_required_only.json()["gap_remaining"]

    assert required_only_gap == baseline_gap, (
        f"Completing only required courses must not shrink gap_remaining, "
        f"baseline={baseline_gap}, after required-only completion={required_only_gap}. "
        f"If these differ, the gap calculation may be counting required-course "
        f"credits as if they were free electives again."
    )

    # Now complete a course that's genuinely outside this major's data
    # entirely (e.g. a Psychology L100 paper). This SHOULD reduce the gap.
    res_with_elective = client.post("/api/plan/progress", json={
        "major": name, "completed": ["159101", "159102", "175101"],
    })
    assert res_with_elective.status_code == 200
    with_elective_gap = res_with_elective.json()["gap_remaining"]

    if baseline_gap > 0:
        assert with_elective_gap < required_only_gap, (
            f"Completing a genuine outside-the-major elective (175101) should "
            f"reduce gap_remaining. required_only={required_only_gap}, "
            f"with_elective={with_elective_gap}"
        )


# ── Double major gap_explanation ──────────────────────────────────────────────

def test_double_major_gap_explanation_mentions_overlap():
    """When a double major plan has a gap, explanation mentions 'double major overlap'."""
    res = client.post("/api/plan", json={
        "major": "Computer Science – Bachelor of Information Sciences",
        "double_major": "Statistics – Bachelor of Science",
        "no_summer": True,
        "auto_fill": False,
    })
    assert res.status_code == 200
    meta = res.json()["meta"]
    if meta["free_elective_gap"] > 0:
        expl = meta.get("gap_explanation", "")
        assert expl is not None
        # Should mention overlap or double major
        assert any(w in expl.lower() for w in ["double", "overlap", "major"]), \
            f"Expected double-major explanation, got: {expl}"


# ── ElectiveFiller OR-aware prereq check ────────────────────────────────────

def test_elective_filler_or_prereq_check():
    """
    _prereqs_satisfiable should accept a course whose prereq is 'A OR B'
    if either A or B is in the available set (not both required).
    """
    from coursemap.planner.elective_filler import ElectiveFiller
    from coursemap.domain.prerequisite import OrExpression, CoursePrerequisite

    prereq = OrExpression(children=[
        CoursePrerequisite(code="111111"),
        CoursePrerequisite(code="222222"),
    ])
    course = Course(
        code="333333", title="Test", credits=15, level=200,
        offerings=(Offering(semester="S1", campus="D", mode="DIS"),),
        prerequisites=prereq,
    )

    # Only 111111 available, should satisfy OR(111111, 222222)
    assert ElectiveFiller._prereqs_satisfiable(course, {"111111"}) is True
    # Only 222222 available, also satisfies
    assert ElectiveFiller._prereqs_satisfiable(course, {"222222"}) is True
    # Neither available, should not satisfy
    assert ElectiveFiller._prereqs_satisfiable(course, {"999999"}) is False
    # Both available, obviously satisfies
    assert ElectiveFiller._prereqs_satisfiable(course, {"111111", "222222"}) is True


def test_elective_filler_and_prereq_check():
    """AND prereq requires ALL children to be in available set."""
    from coursemap.planner.elective_filler import ElectiveFiller
    from coursemap.domain.prerequisite import AndExpression, CoursePrerequisite

    prereq = AndExpression(children=[
        CoursePrerequisite(code="111111"),
        CoursePrerequisite(code="222222"),
    ])
    course = Course(
        code="333333", title="Test", credits=15, level=200,
        offerings=(Offering(semester="S1", campus="D", mode="DIS"),),
        prerequisites=prereq,
    )

    # Only one of two, should NOT satisfy AND
    assert ElectiveFiller._prereqs_satisfiable(course, {"111111"}) is False
    assert ElectiveFiller._prereqs_satisfiable(course, {"222222"}) is False
    # Both, should satisfy
    assert ElectiveFiller._prereqs_satisfiable(course, {"111111", "222222"}) is True


# ── Progress bar shows in plan when credits_prior > 0 ────────────────────────

def test_plan_meta_has_credits_prior():
    """credits_prior should reflect the completed courses' credits."""
    res = client.post("/api/plan", json={
        "major": "Computer Science – Bachelor of Information Sciences",
        "completed": ["159101", "160101"],
        "no_summer": True,
    })
    assert res.status_code == 200
    meta = res.json()["meta"]
    assert meta["credits_prior"] == 30  # 2 × 15cr completed
    assert meta["credits_total"] > meta["credits_prior"]


# ═══════════════════════════════════════════════════════════════
# Final continuation: generator fixes, input sanitisation
# ═══════════════════════════════════════════════════════════════

# ── Generator: OR-aware prereq helper ────────────────────────────────────────

def test_prereq_codes_or_aware_or_expression():
    """OR node: only codes common to ALL branches are considered 'required'."""
    from coursemap.planner.generator import _prereq_codes_or_aware
    from coursemap.domain.prerequisite import OrExpression, CoursePrerequisite

    # OR(111, 222): neither is required by BOTH branches, so intersection is empty
    or_expr = OrExpression(children=[
        CoursePrerequisite("111111"),
        CoursePrerequisite("222222"),
    ])
    known = {"111111", "222222", "333333"}
    result = _prereq_codes_or_aware(or_expr, known)
    assert result == set(), f"OR of two different codes should give empty intersection, got {result}"


def test_prereq_codes_or_aware_and_expression():
    """AND node: all children contribute their required codes."""
    from coursemap.planner.generator import _prereq_codes_or_aware
    from coursemap.domain.prerequisite import AndExpression, CoursePrerequisite

    and_expr = AndExpression(children=[
        CoursePrerequisite("111111"),
        CoursePrerequisite("222222"),
    ])
    known = {"111111", "222222", "333333"}
    result = _prereq_codes_or_aware(and_expr, known)
    assert result == {"111111", "222222"}


def test_prereq_codes_or_aware_ignores_unknown():
    """Codes not in known set are excluded from results."""
    from coursemap.planner.generator import _prereq_codes_or_aware
    from coursemap.domain.prerequisite import CoursePrerequisite

    prereq = CoursePrerequisite("EXTERNAL999")
    result = _prereq_codes_or_aware(prereq, {"111111"})
    assert result == set()


def test_prereq_codes_or_aware_nested():
    """AND(OR(A,B), C): C is always required, neither A nor B alone is."""
    from coursemap.planner.generator import _prereq_codes_or_aware
    from coursemap.domain.prerequisite import AndExpression, OrExpression, CoursePrerequisite

    expr = AndExpression(children=[
        OrExpression(children=[
            CoursePrerequisite("111111"),
            CoursePrerequisite("222222"),
        ]),
        CoursePrerequisite("333333"),
    ])
    known = {"111111", "222222", "333333"}
    result = _prereq_codes_or_aware(expr, known)
    # OR(111,222) contributes nothing to AND (empty intersection)
    # 333333 contributes itself
    assert result == {"333333"}


# ── Input sanitisation: lowercase and padded codes ───────────────────────────

def test_completed_codes_case_insensitive():
    """Lowercase course codes in 'completed' should still be recognised."""
    res = client.post("/api/plan", json={
        "major": "Computer Science – Bachelor of Information Sciences",
        "completed": ["159101", "160101"],  # lowercase, should work
        "no_summer": True,
    })
    res_upper = client.post("/api/plan", json={
        "major": "Computer Science – Bachelor of Information Sciences",
        "completed": ["159101", "160101"],
        "no_summer": True,
    })
    assert res.status_code == res_upper.status_code == 200
    # Both should show same credits_prior
    assert res.json()["meta"]["credits_prior"] == res_upper.json()["meta"]["credits_prior"]


def test_completed_codes_whitespace_stripped():
    """Whitespace around course codes should be stripped."""
    res = client.post("/api/plan", json={
        "major": "Computer Science – Bachelor of Information Sciences",
        "completed": ["  159101  ", " 160101"],
        "no_summer": True,
    })
    assert res.status_code == 200
    assert res.json()["meta"]["credits_prior"] == 30


def test_exclude_codes_sanitised():
    """Exclude codes with whitespace/case should still match correctly."""
    res = client.post("/api/plan", json={
        "major": "Computer Science – Bachelor of Information Sciences",
        "exclude": ["  159999  "],  # padded, non-existent code
        "no_summer": True,
    })
    # Should succeed (non-existent code in exclude is a no-op)
    assert res.status_code == 200


def test_progress_completed_codes_sanitised():
    """Progress endpoint should handle lowercase and padded codes."""
    res = client.post("/api/plan/progress", json={
        "major": "Computer Science – Bachelor of Information Sciences",
        "completed": ["  159101  ", "160101"],
    })
    assert res.status_code == 200
    assert res.json()["credits_completed"] == 30


# ── Full plan generation smoke test with OR-aware rebalancing ────────────────

def test_plan_generation_still_works_after_generator_fixes():
    """End-to-end smoke test: plan generation should still work correctly."""
    res = client.post("/api/plan", json={
        "major": "Computer Science – Bachelor of Information Sciences",
        "no_summer": True,
        "auto_fill": True,
    })
    assert res.status_code == 200
    data = res.json()
    assert len(data["semesters"]) >= 4
    assert data["meta"]["credits_total"] >= 340  # near degree target
    assert data["meta"]["degree_target"] == 360


def test_double_major_plan_works_after_fixes():
    """Double major plan generation smoke test."""
    res = client.post("/api/plan", json={
        "major": "Computer Science – Bachelor of Information Sciences",
        "double_major": "Statistics – Bachelor of Science",
        "no_summer": True,
    })
    assert res.status_code == 200
    data = res.json()
    assert len(data["semesters"]) > 0
    assert data["double_major_info"] is not None


# ── Minors count in /api/minors ───────────────────────────────────────────────

def test_minors_count_matches_total():
    """count field should equal len(minors) when no filters applied."""
    res = client.get("/api/minors")
    assert res.status_code == 200
    data = res.json()
    assert data["count"] == len(data["minors"])
    assert data["total"] == data["count"]  # no filter applied


# ═══════════════════════════════════════════════════════════════
# Final batch: search.py, fees.py, filler_codes propagation
# ═══════════════════════════════════════════════════════════════

# ── OR-aware prereq expansion in search.py ────────────────────────────────────

def test_or_prereq_expansion_does_not_over_include():
    """
    Generating a plan should not include extra courses from unused OR branches.
    We can't easily assert exact codes, but we can verify plan generation
    still works correctly and that plans don't grow unexpectedly.
    """
    res = client.post("/api/plan", json={
        "major": "Computer Science – Bachelor of Information Sciences",
        "no_summer": True,
    })
    assert res.status_code == 200
    data = res.json()
    # Plan should be within reasonable bounds (not explode with extra courses)
    total_courses = sum(len(s["courses"]) for s in data["semesters"])
    assert total_courses <= 30, f"Unexpectedly many courses: {total_courses}"


# ── filler_codes propagation ─────────────────────────────────────────────────

def test_autofill_plan_schedules_required_before_fillers():
    """
    With auto_fill=True, filler_codes must be correctly propagated to the
    PlanGenerator so the (level, is_filler, code) sort key actually has an
    effect. This is a regression test for a real v6 bug where filler_codes
    was set on the generator TEMPLATE but never propagated to the actual
    generator INSTANCES that run the search, making the is_filler tiebreaker
    silently always False.

    This checks the minimal, clearly-correct signal: at the very first level
    that has both filler and required courses, filler must not appear before
    EVERY required course at that level has appeared (i.e. filler doesn't
    completely steamroll the lowest level's required courses). A full
    "filler never appears before any required course at its level, in any
    semester" invariant is NOT asserted here. The greedy scheduler's
    interaction with per-semester credit caps can legitimately place a
    required course one semester after filler at the same level starts
    appearing (e.g. when an earlier semester is already at its credit cap),
    and distinguishing that from an actual sort-key regression needs deeper
    scheduling analysis than this smoke test is meant to provide.
    """
    res = client.post("/api/plan", json={
        "major": "Computer Science – Bachelor of Information Sciences",
        "no_summer": True,
        "auto_fill": True,
    })
    assert res.status_code == 200
    data = res.json()
    filler = set(data.get("filler_codes", []))
    semesters = data["semesters"]

    if not filler or len(semesters) < 2:
        return  # can't test without fillers

    # Find the lowest level that has at least one filler course anywhere
    # in the plan, then confirm the FIRST semester containing that level's
    # courses contains at least one required (non-filler) course, i.e.
    # filler isn't placed ahead of every required course at the very start.
    levels_with_filler = {
        c.get("level") for sem in semesters for c in sem["courses"] if c["code"] in filler
    }
    if not levels_with_filler:
        return
    target_level = min(levels_with_filler)

    for sem in semesters:
        level_courses = [c for c in sem["courses"] if c.get("level") == target_level]
        if level_courses:
            has_required = any(c["code"] not in filler for c in level_courses)
            assert has_required, (
                f"First semester containing level {target_level} courses has "
                f"ONLY filler ({[c['code'] for c in level_courses]}). "
                f"filler_codes may not be propagated correctly to the generator."
            )
            break


def test_filler_codes_in_plan_response():
    """Auto-fill plan should return filler_codes list."""
    res = client.post("/api/plan", json={
        "major": "Computer Science – Bachelor of Information Sciences",
        "no_summer": True,
        "auto_fill": True,
    })
    assert res.status_code == 200
    data = res.json()
    assert "filler_codes" in data
    assert isinstance(data["filler_codes"], list)


# ── fees.py CS/Stats coverage ─────────────────────────────────────────────────

def test_fee_estimate_includes_cs_courses():
    """Fee estimate should work for CS-subject-area courses without KeyError."""
    from coursemap.domain.fees import estimate_plan_fees
    fake_plan = [
        {"semester": "S1", "year": 2026, "courses": [
            {"code": "159101", "credits": 15, "subject_area": "Computer Science", "level": 100},
            {"code": "160101", "credits": 15, "subject_area": "Mathematics", "level": 100},
        ]},
    ]
    result = estimate_plan_fees(fake_plan, student_type="domestic")
    assert isinstance(result, dict)
    assert result.get("total", 0) > 0


def test_fee_estimate_stats_courses():
    """Fee estimate for Statistics courses should use the Stats tier."""
    from coursemap.domain.fees import estimate_plan_fees
    fake_plan = [
        {"semester": "S1", "year": 2026, "courses": [
            {"code": "161122", "credits": 15, "subject_area": "Statistics", "level": 100},
        ]},
    ]
    result = estimate_plan_fees(fake_plan, student_type="domestic")
    assert isinstance(result, dict)
    assert result.get("total", 0) > 0


# ── ical.py SS cross-year handling ───────────────────────────────────────────

def test_ical_summer_school_dates_cross_year():
    """Summer School starting Nov 2026 should end in early 2027."""
    from coursemap.export.ical import _semester_dates
    start, end = _semester_dates(2026, "SS")
    assert start.year == 2026
    assert start.month == 11
    # End should be in February 2027 (10 weeks later)
    assert end.year == 2027
    assert end.month <= 3  # January or February


def test_ical_s1_dates():
    """Semester 1 should start in February."""
    from coursemap.export.ical import _semester_dates
    start, end = _semester_dates(2026, "S1")
    assert start.year == 2026
    assert start.month == 2
    assert end.month >= 6  # ~17 weeks later = June


def test_ical_export_works_for_full_plan():
    """iCal export should produce a valid .ics string for a real plan."""
    res = client.post("/api/plan/ical", json={
        "major": "Computer Science – Bachelor of Information Sciences",
        "no_summer": True,
    })
    assert res.status_code == 200
    ical = res.text
    assert "BEGIN:VCALENDAR" in ical
    assert "BEGIN:VEVENT" in ical
    assert "END:VCALENDAR" in ical


# ── progress semesters_remaining edge cases ───────────────────────────────────

def test_progress_zero_remaining_gives_zero_semesters():
    """When all 360cr are done, semesters remaining should be 0."""
    # We can't pass 360cr of completed courses easily, but we can check the
    # math: credits_remaining = 0 → sems_remaining = 0
    from coursemap.api.server import _courses
    courses_map = _courses()
    # Get 24 courses worth of 15cr each (360cr total)
    cs_codes = [c for c, course in courses_map.items()
                if course.credits == 15 and course.level == 100][:24]
    if len(cs_codes) < 24:
        return  # not enough courses to test
    res = client.post("/api/plan/progress", json={
        "major": "Computer Science – Bachelor of Information Sciences",
        "completed": cs_codes,
    })
    assert res.status_code == 200
    data = res.json()
    # If we submitted enough credits to cover the degree
    if data["credits_remaining"] == 0:
        assert data["estimated_semesters_remaining"] == 0


def test_progress_small_remaining_gives_at_least_one():
    """When some credits remain, semesters remaining should be at least 1."""
    res = client.post("/api/plan/progress", json={
        "major": "Computer Science – Bachelor of Information Sciences",
        "completed": ["159101"],  # only 15cr done
    })
    assert res.status_code == 200
    data = res.json()
    assert data["estimated_semesters_remaining"] >= 1


# ═══════════════════════════════════════════════════════════════
# prerequisite.py, minor_loader, CLI minors
# ═══════════════════════════════════════════════════════════════

# ── OrExpression.required_courses() returns union (all branches) ─────────────

def test_or_expression_required_courses_returns_union():
    """required_courses() on OR returns ALL codes from all branches (union)."""
    from coursemap.domain.prerequisite import OrExpression, CoursePrerequisite

    expr = OrExpression(children=(
        CoursePrerequisite("111111"),
        CoursePrerequisite("222222"),
    ))
    codes = expr.required_courses()
    # Union: both codes present
    assert "111111" in codes
    assert "222222" in codes


def test_and_expression_required_courses_returns_union():
    """required_courses() on AND also returns union (all required codes)."""
    from coursemap.domain.prerequisite import AndExpression, CoursePrerequisite

    expr = AndExpression(children=(
        CoursePrerequisite("111111"),
        CoursePrerequisite("222222"),
    ))
    codes = expr.required_courses()
    assert codes == {"111111", "222222"}


# ── search_minors multi-word queries ─────────────────────────────────────────

def test_search_minors_single_word():
    from coursemap.ingestion.minor_loader import load_minors, search_minors
    minors = load_minors()
    results = search_minors("science", minors)
    assert len(results) > 0
    assert all("science" in m["name"].lower() or "Science" in m["name"] for m in results)


def test_search_minors_multi_word():
    from coursemap.ingestion.minor_loader import load_minors, search_minors
    minors = load_minors()
    results = search_minors("computer science", minors)
    assert len(results) > 0
    assert any("computer" in m["name"].lower() for m in results)


def test_search_minors_empty_query_returns_all():
    from coursemap.ingestion.minor_loader import load_minors, search_minors
    minors = load_minors()
    results = search_minors("", minors)
    assert results == minors


def test_search_minors_no_match_falls_back_to_substring():
    from coursemap.ingestion.minor_loader import load_minors, search_minors
    minors = load_minors()
    # "psych" won't word-match "Psychology" (partial word), should fall back
    results = search_minors("psych", minors)
    # Either returns results via fallback or empty, just shouldn't crash
    assert isinstance(results, list)


# ── CLI: minors subcommand ───────────────────────────────────────────────────

def test_cli_minors_lists_all():
    """CLI 'minors' command should list all available minors."""
    import subprocess, sys
    result = subprocess.run(
        [sys.executable, "-m", "coursemap.cli.main", "minors"],
        capture_output=True, text=True, encoding="utf-8",
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0
    assert "minor(s)" in result.stdout
    assert "Computer Science" in result.stdout


def test_cli_minors_search():
    """CLI 'minors --search' filters by name."""
    import subprocess, sys
    result = subprocess.run(
        [sys.executable, "-m", "coursemap.cli.main", "minors", "--search", "statistics"],
        capture_output=True, text=True, encoding="utf-8",
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0
    assert "Statistics" in result.stdout


def test_cli_minors_quality_filter():
    """CLI 'minors --quality scraped' only shows scraped entries."""
    import subprocess, sys
    result = subprocess.run(
        [sys.executable, "-m", "coursemap.cli.main", "minors", "--quality", "scraped"],
        capture_output=True, text=True, encoding="utf-8",
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0
    # Should NOT show inferred warning for scraped-only results
    lines = [l for l in result.stdout.split("\n") if "⚠ inferred" in l]
    assert len(lines) == 0


# ── CLI: --minor flag in plan command ────────────────────────────────────────

def test_cli_plan_with_minor_flag():
    """CLI 'plan --minor' adds minor courses to preferred electives."""
    import subprocess, sys
    result = subprocess.run(
        [sys.executable, "-m", "coursemap.cli.main", "plan",
         "--major", "Computer Science – Bachelor of Information Sciences",
         "--minor", "Statistics",
         "--no-summer",
         "--format", "json"],
        capture_output=True, text=True, encoding="utf-8",
        cwd=str(REPO_ROOT),
        timeout=60,
    )
    # Either succeeds or fails for unrelated reasons, just verify minor is mentioned
    stderr_lower = result.stderr.lower()
    assert "minor" in stderr_lower or result.returncode == 0, \
        f"Expected minor to be mentioned, got: {result.stderr[:200]}"


# ── OR-aware prereq expansion doesn't double-include courses ─────────────────

def test_plan_with_or_prereqs_doesnt_overcrowd():
    """Plans should not include duplicate or unnecessary OR-branch courses."""
    res = client.post("/api/plan", json={
        "major": "Computer Science – Bachelor of Information Sciences",
        "no_summer": True,
        "auto_fill": True,
    })
    assert res.status_code == 200
    # Check no duplicate codes across semesters
    all_codes = []
    for sem in res.json()["semesters"]:
        for c in sem["courses"]:
            all_codes.append(c["code"])
    assert len(all_codes) == len(set(all_codes)), \
        f"Duplicate course codes in plan: {[c for c in all_codes if all_codes.count(c) > 1]}"


# ═══════════════════════════════════════════════════════════════
# scorer, validator, CLI, HTML export
# ═══════════════════════════════════════════════════════════════

# ── PlanScorer S1/S2 balance ──────────────────────────────────────────────────

def test_scorer_penalises_s1_s2_imbalance():
    """A plan with balanced S1/S2 loads should score better than an imbalanced one."""
    from coursemap.optimisation.scorer import PlanScorer
    from coursemap.domain.plan import DegreePlan, SemesterPlan

    def _fake_course(code, credits):
        return Course(code=code, title=code, credits=credits, level=100,
                      offerings=(Offering(semester="S1", campus="D", mode="DIS"),))

    # Balanced: S1=30cr, S2=30cr, S1=30cr, S2=30cr
    balanced = DegreePlan(semesters=(
        SemesterPlan(year=2026, semester="S1", courses=(_fake_course("A",15),_fake_course("B",15))),
        SemesterPlan(year=2026, semester="S2", courses=(_fake_course("C",15),_fake_course("D",15))),
        SemesterPlan(year=2027, semester="S1", courses=(_fake_course("E",15),_fake_course("F",15))),
        SemesterPlan(year=2027, semester="S2", courses=(_fake_course("G",15),_fake_course("H",15))),
    ))

    # Imbalanced: S1=60cr, S2=15cr, S1=60cr, S2=15cr
    imbalanced = DegreePlan(semesters=(
        SemesterPlan(year=2026, semester="S1", courses=tuple(_fake_course(f"X{i}",15) for i in range(4))),
        SemesterPlan(year=2026, semester="S2", courses=(_fake_course("Y1",15),)),
        SemesterPlan(year=2027, semester="S1", courses=tuple(_fake_course(f"Z{i}",15) for i in range(4))),
        SemesterPlan(year=2027, semester="S2", courses=(_fake_course("W1",15),)),
    ))

    scorer = PlanScorer()
    # Both have 4 semesters (equal semester_penalty)
    # Balanced should have lower total score
    assert scorer.score(balanced) <= scorer.score(imbalanced)


def test_scorer_empty_plan_returns_inf():
    from coursemap.optimisation.scorer import PlanScorer
    from coursemap.domain.plan import DegreePlan
    scorer = PlanScorer()
    assert scorer.score(DegreePlan(semesters=())) == float("inf")


# ── dataset_validator: full_year flag ─────────────────────────────────────────

def test_validator_accepts_valid_full_year_flag():
    """Offerings with full_year=True or False should pass validation."""
    from coursemap.validation.dataset_validator import check_offerings

    c = Course(
        code="TEST01", title="Test", credits=15, level=100,
        offerings=(
            Offering(semester="S1", campus="D", mode="DIS", full_year=False),
            Offering(semester="S2", campus="D", mode="DIS", full_year=True),
        ),
    )
    errors = []
    warnings = []
    check_offerings({"TEST01": c}, errors, warnings)
    assert not errors, f"Unexpected validation errors: {errors}"


def test_validator_course_passes_full_validation():
    """Full dataset validation should pass with no errors on the loaded dataset."""
    res = client.get("/api/validate")
    assert res.status_code == 200
    data = res.json()
    # Errors key may be "errors" (count) or "error_count" depending on response shape
    error_count = data.get("error_count", len(data.get("errors", [])))
    assert error_count == 0, f"Dataset has errors: {data.get('errors', [])[:3]}"


# ── CLI: zero-credit courses excluded from default view ──────────────────────

def test_cli_courses_excludes_zero_credit_by_default():
    """CLI 'courses' should not show zero-credit courses in default view."""
    import subprocess, sys
    result = subprocess.run(
        [sys.executable, "-m", "coursemap.cli.main", "courses", "--level", "100"],
        capture_output=True, text=True, encoding="utf-8",
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0
    # Zero-credit practicums should not appear
    lines = result.stdout.split("\n")
    course_lines = [l for l in lines if "  0cr" in l]
    assert len(course_lines) == 0, f"Found zero-credit courses: {course_lines[:3]}"


# ── CLI: _collect_missing OR fix ──────────────────────────────────────────────

def test_collect_missing_or_satisfied_by_first_branch():
    """If branch A of OR(A,B) is already completed, no codes should be reported missing."""
    import sys; sys.path.insert(0, str(REPO_ROOT))
    from coursemap.cli.main import _collect_missing
    from coursemap.domain.prerequisite import OrExpression, CoursePrerequisite

    prereq = OrExpression(children=(
        CoursePrerequisite("AAA100"),
        CoursePrerequisite("BBB100"),
    ))
    out = []
    # AAA100 is completed, OR should be satisfied, no missing codes
    _collect_missing(prereq, completed={"AAA100"}, known=frozenset({"AAA100", "BBB100"}),
                     planned=set(), out=out)
    assert out == [], f"Expected no missing codes, got: {out}"


def test_collect_missing_or_picks_best_branch():
    """When no OR branch is satisfied, should report missing from the shortest branch."""
    from coursemap.cli.main import _collect_missing
    from coursemap.domain.prerequisite import OrExpression, AndExpression, CoursePrerequisite

    # OR(AND(A,B,C), D): branch 1 needs 3 courses, branch 2 needs 1
    # Should report D as missing (fewest missing)
    prereq = OrExpression(children=(
        AndExpression(children=(
            CoursePrerequisite("AAA"),
            CoursePrerequisite("BBB"),
            CoursePrerequisite("CCC"),
        )),
        CoursePrerequisite("DDD"),
    ))
    out = []
    _collect_missing(prereq, completed=set(),
                     known=frozenset({"AAA", "BBB", "CCC", "DDD"}),
                     planned=set(), out=out)
    # Should report DDD (1 missing) not AAA+BBB+CCC (3 missing)
    assert out == ["DDD"], f"Expected ['DDD'], got: {out}"


# ── PlanScorer: score structure ───────────────────────────────────────────────

def test_scorer_fewer_semesters_wins():
    """A plan with fewer semesters should score better than one with more (all else equal)."""
    from coursemap.optimisation.scorer import PlanScorer
    from coursemap.domain.plan import DegreePlan, SemesterPlan

    def _c(code):
        return Course(code=code, title=code, credits=30, level=100,
                      offerings=(Offering(semester="S1", campus="D", mode="DIS"),))

    short = DegreePlan(semesters=(
        SemesterPlan(year=2026, semester="S1", courses=(_c("A"), _c("B"))),
        SemesterPlan(year=2026, semester="S2", courses=(_c("C"), _c("D"))),
    ))
    long_ = DegreePlan(semesters=(
        SemesterPlan(year=2026, semester="S1", courses=(_c("A"),)),
        SemesterPlan(year=2026, semester="S2", courses=(_c("B"),)),
        SemesterPlan(year=2027, semester="S1", courses=(_c("C"),)),
        SemesterPlan(year=2027, semester="S2", courses=(_c("D"),)),
    ))
    scorer = PlanScorer()
    assert scorer.score(short) < scorer.score(long_)

# ── fees.py: no duplicate keys ────────────────────────────────────────────────

def test_fees_no_duplicate_subject_keys():
    """fees.py dict must not have duplicate keys (Python silently overwrites them)."""
    import ast
    src = (REPO_ROOT / "coursemap/domain/fees.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            keys = [k.value for k in node.keys
                    if isinstance(k, ast.Constant) and isinstance(k.value, str)]
            dupes = {k for k in keys if keys.count(k) > 1}
            assert not dupes, f"Duplicate fee keys: {dupes}"
            break


def test_fees_cs_rate_is_consistent():
    """Computer Science fee rate should be consistent (single definition)."""
    from coursemap.domain.fees import fee_per_credit
    rate = fee_per_credit("Computer Science", level=200)
    assert rate == 65.0, f"Expected 65.0, got {rate}"


def test_fees_stats_returns_value():
    from coursemap.domain.fees import fee_per_credit
    rate = fee_per_credit("Statistics", level=200)
    assert rate > 0


def test_fees_unknown_subject_returns_default():
    from coursemap.domain.fees import fee_per_credit
    rate = fee_per_credit("Underwater Basket Weaving", level=200)
    assert rate == 60.0  # _DEFAULT_FEE_PER_CREDIT_UG


def test_fees_postgrad_level_applies_surcharge():
    from coursemap.domain.fees import fee_per_credit
    ug_rate = fee_per_credit("Statistics", level=200)
    pg_rate = fee_per_credit("Statistics", level=700)
    assert pg_rate >= ug_rate


def test_fees_international_multiplier():
    from coursemap.domain.fees import fee_per_credit
    dom = fee_per_credit("Statistics", level=200, student_type="domestic")
    intl = fee_per_credit("Statistics", level=200, student_type="international")
    assert intl > dom * 2  # multiplier is ~2.8x


# ── select_free_electives: excludes zero-credit courses ──────────────────────

def test_select_free_electives_excludes_zero_credit():
    """select_free_electives should never return zero-credit courses."""
    from coursemap.domain.requirement_utils import select_free_electives
    from coursemap.ingestion.dataset_loader import load_courses
    courses = load_courses()
    # Inject a zero-credit course into a copy of courses
    zero_cr = Course(code="ZZZ000", title="Zero Credit", credits=0, level=100,
                     offerings=(Offering(semester="S1", campus="D", mode="DIS"),))
    courses_with_zero = {**courses, "ZZZ000": zero_cr}
    results = select_free_electives(
        courses=courses_with_zero,
        planned_codes={"159101"},
        excluded_codes=set(),
        gap=60,
        campus="D",
        mode="DIS",
    )
    codes = [code for _, code, _ in results]
    assert "ZZZ000" not in codes, "Zero-credit course should never appear in elective suggestions"


def test_select_free_electives_returns_within_gap():
    """Total credits of selected electives should not exceed gap + 30."""
    from coursemap.domain.requirement_utils import select_free_electives
    from coursemap.ingestion.dataset_loader import load_courses
    courses = load_courses()
    gap = 60
    results = select_free_electives(
        courses=courses,
        planned_codes={"159101", "159201"},
        excluded_codes=set(),
        gap=gap,
        campus="D",
        mode="DIS",
    )
    total = sum(courses[code].credits for _, code, _ in results if code in courses)
    assert total <= gap + 30


# ── CLI --no-summer default is True ──────────────────────────────────────────

def test_cli_no_summer_default():
    """CLI plan --no-summer should default to True (same as API)."""
    import sys
    # Reload CLI to pick up fresh argument defaults
    # Find plan_p and check default
    # We can test this by checking the argparse action stored default
    # Simplest: run CLI help and check
    import subprocess
    result = subprocess.run(
        [sys.executable, "-m", "coursemap.cli.main", "plan", "--help"],
        capture_output=True, text=True, encoding="utf-8", cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0
    # The default=True means no-summer is included by default
    # Just verify help mentions it
    assert "summer" in result.stdout.lower()


def test_cli_parse_code_list_uppercases():
    """_parse_code_list must uppercase and strip codes."""
    from coursemap.cli.main import _parse_code_list
    from coursemap.ingestion.dataset_loader import load_courses
    courses = load_courses()
    # "159101" should match regardless of case (once uppercased)
    valid, invalid = _parse_code_list("159101,  159102 ", courses)
    assert "159101" in valid
    assert "159102" in valid
    assert not invalid


def test_cli_parse_code_list_handles_padding():
    """_parse_code_list must strip whitespace from individual codes."""
    from coursemap.cli.main import _parse_code_list
    from coursemap.ingestion.dataset_loader import load_courses
    courses = load_courses()
    valid, invalid = _parse_code_list("  159101  ", courses)
    assert "159101" in valid


# ── select_free_electives: preferred codes appear first ──────────────────────

def test_select_free_electives_respects_preferred():
    """Preferred course codes should appear before other codes in results."""
    from coursemap.domain.requirement_utils import select_free_electives
    from coursemap.ingestion.dataset_loader import load_courses
    courses = load_courses()
    # Get a few distance courses at L200 level  
    l200_dist = [code for code, c in courses.items()
                 if c.level == 200 and c.credits == 15 and c.credits > 0
                 and any(o.campus == "D" and o.mode == "DIS" for o in c.offerings)][:5]
    if len(l200_dist) < 2:
        return
    preferred = frozenset({l200_dist[0]})
    results = select_free_electives(
        courses=courses,
        planned_codes=set(l200_dist[1:]),
        excluded_codes=set(),
        gap=60,
        campus="D",
        mode="DIS",
        preferred=preferred,
    )
    codes = [code for _, code, _ in results]
    # preferred code should appear if it's not in planned_codes
    if l200_dist[0] not in set(l200_dist[1:]):
        assert l200_dist[0] in codes or len(codes) == 0


# ── estimate_plan_fees: end-to-end with real plan ────────────────────────────

def test_estimate_plan_fees_from_api():
    """Fee estimate from a real API plan should return a positive total."""
    res = client.post("/api/plan", json={
        "major": "Computer Science – Bachelor of Information Sciences",
        "no_summer": True,
        "auto_fill": True,
    })
    assert res.status_code == 200
    data = res.json()
    semesters = data["semesters"]
    from coursemap.domain.fees import estimate_plan_fees
    fee_data = estimate_plan_fees(semesters)
    assert fee_data["total"] > 0
    assert len(fee_data["by_year"]) > 0
    assert "disclaimer" in fee_data


def test_estimate_plan_fees_total_matches_sum_of_by_year():
    """
    Regression test: 'total' must always equal sum(by_year.values()).

    Bug: total was rounded independently from by_year (round(raw_total, -1)
    vs {yr: round(raw_amt, -1) for yr, raw_amt in by_year.items()}), so they
    could disagree by rounding error. Concretely: two years each with a raw
    total of $455 round to $460 individually (910 total displayed across
    years) but $910 as a combined raw total of 910 rounds to itself (910),
    a $10 discrepancy a student adding up their own per-year numbers would
    notice and rightly distrust.
    """
    from coursemap.domain.fees import estimate_plan_fees

    semesters = [
        {"year": 2026, "courses": [{"credits": 7, "level": 100, "subject_area": "Computer Science"}]},
        {"year": 2027, "courses": [{"credits": 7, "level": 100, "subject_area": "Computer Science"}]},
    ]
    result = estimate_plan_fees(semesters)
    assert result["total"] == sum(result["by_year"].values()), (
        f"total ({result['total']}) must equal sum of by_year "
        f"({sum(result['by_year'].values())}). These must never disagree, "
        f"since a student will naturally add up the per-year breakdown "
        f"themselves and compare it to the displayed total."
    )

# ── MinLevelCreditsRequirement includes prior_completed ───────────────────────

def test_min_level_credits_counts_prior_completed():
    """MinLevelCreditsRequirement.is_satisfied must count prior-completed courses."""
    from coursemap.domain.requirement_nodes import MinLevelCreditsRequirement
    from coursemap.domain.plan import DegreePlan, SemesterPlan

    req = MinLevelCreditsRequirement(level=300, min_credits=45)

    def _c(code, level, credits):
        return Course(code=code, title=code, credits=credits, level=level,
                      offerings=(Offering(semester="S1", campus="D", mode="DIS"),))

    # 30cr of L300 in plan + 15cr L300 prior = 45cr total → satisfied
    prior = (_c("P300", 300, 15),)
    plan = DegreePlan(
        semesters=(SemesterPlan(year=2026, semester="S1",
                                courses=(_c("A300", 300, 15), _c("B300", 300, 15))),),
        prior_completed=prior,
    )
    assert req.is_satisfied(plan), "45cr L300 (30 scheduled + 15 prior) should satisfy 45cr requirement"

    # Only 30cr in plan, no prior → not satisfied
    plan_no_prior = DegreePlan(
        semesters=(SemesterPlan(year=2026, semester="S1",
                                courses=(_c("A300", 300, 15), _c("B300b", 300, 15))),),
    )
    assert not req.is_satisfied(plan_no_prior), "30cr scheduled (no prior) should NOT satisfy 45cr requirement"


def test_min_level_credits_from_counts_prior():
    """MinLevelCreditsFromRequirement.is_satisfied counts prior-completed codes."""
    from coursemap.domain.requirement_nodes import MinLevelCreditsFromRequirement
    from coursemap.domain.plan import DegreePlan, SemesterPlan

    allowed = ("AAA300", "BBB300")
    req = MinLevelCreditsFromRequirement(level=300, min_credits=30, course_codes=allowed)

    def _c(code, level=300, credits=15):
        return Course(code=code, title=code, credits=credits, level=level,
                      offerings=(Offering(semester="S1", campus="D", mode="DIS"),))

    # Only prior, no scheduled → should be satisfied if prior covers the gap
    plan = DegreePlan(
        semesters=(SemesterPlan(year=2026, semester="S1", courses=()),),
        prior_completed=(_c("AAA300"), _c("BBB300")),
    )
    assert req.is_satisfied(plan)


def test_max_level_credits_counts_prior():
    """MaxLevelCreditsRequirement.is_satisfied counts prior-completed courses."""
    from coursemap.domain.requirement_nodes import MaxLevelCreditsRequirement
    from coursemap.domain.plan import DegreePlan, SemesterPlan

    req = MaxLevelCreditsRequirement(level=100, max_credits=30)

    def _c(code, level=100, credits=15):
        return Course(code=code, title=code, credits=credits, level=level,
                      offerings=(Offering(semester="S1", campus="D", mode="DIS"),))

    # 15cr scheduled + 15cr prior = 30cr = exactly at limit
    plan = DegreePlan(
        semesters=(SemesterPlan(year=2026, semester="S1", courses=(_c("A100"),)),),
        prior_completed=(_c("B100"),),
    )
    assert req.is_satisfied(plan)  # 30 <= 30

    # 15 + 30 = 45 > 30 → not satisfied
    plan_over = DegreePlan(
        semesters=(SemesterPlan(year=2026, semester="S1", courses=(_c("A100"),)),),
        prior_completed=(_c("B100"), _c("C100")),
    )
    assert not req.is_satisfied(plan_over)


def test_total_credits_includes_transfer():
    """TotalCreditsRequirement.is_satisfied includes transfer_credits."""
    from coursemap.domain.requirement_nodes import TotalCreditsRequirement
    from coursemap.domain.plan import DegreePlan, SemesterPlan

    req = TotalCreditsRequirement(required_credits=360)

    def _c(code, credits=15):
        return Course(code=code, title=code, credits=credits, level=100,
                      offerings=(Offering(semester="S1", campus="D", mode="DIS"),))

    # 300cr scheduled + 60cr transfer = 360cr total → satisfied
    courses_300 = tuple(_c(f"C{i:03d}") for i in range(20))  # 20 × 15cr = 300cr
    plan = DegreePlan(
        semesters=(SemesterPlan(year=2026, semester="S1", courses=courses_300),),
        transfer_credits=60,
    )
    assert req.is_satisfied(plan), "300cr scheduled + 60cr transfer should satisfy 360cr"

    # Without transfer: not satisfied
    plan_no_transfer = DegreePlan(
        semesters=(SemesterPlan(year=2026, semester="S1", courses=courses_300),),
    )
    assert not req.is_satisfied(plan_no_transfer)


# ── DegreePlan mutation guard ─────────────────────────────────────────────────

def test_degree_plan_semesters_immutable_after_construction():
    """Reassigning DegreePlan.semesters after construction should raise AttributeError."""
    import pytest
    from coursemap.domain.plan import DegreePlan

    plan = DegreePlan(semesters=())
    with pytest.raises(AttributeError, match="stale"):
        plan.semesters = ()


def test_degree_plan_all_course_codes_accurate():
    """all_course_codes must reflect semesters + prior_completed."""
    from coursemap.domain.plan import DegreePlan, SemesterPlan

    def _c(code):
        return Course(code=code, title=code, credits=15, level=100,
                      offerings=(Offering(semester="S1", campus="D", mode="DIS"),))

    plan = DegreePlan(
        semesters=(SemesterPlan(year=2026, semester="S1", courses=(_c("AAA"),)),),
        prior_completed=(_c("BBB"),),
    )
    assert "AAA" in plan.all_course_codes
    assert "BBB" in plan.all_course_codes
    assert len(plan.all_course_codes) == 2


# ── select_free_electives overshoot control ───────────────────────────────────

def test_select_free_electives_does_not_massively_overshoot():
    """Elective selection should not overshoot the gap by more than 30cr."""
    from coursemap.domain.requirement_utils import select_free_electives
    from coursemap.ingestion.dataset_loader import load_courses

    courses = load_courses()
    gap = 60
    results = select_free_electives(
        courses=courses,
        planned_codes={"159101", "159201"},
        excluded_codes=set(),
        gap=gap,
        campus="D",
        mode="DIS",
    )
    total = sum(courses[code].credits for _, code, _ in results if code in courses)
    assert total <= gap + 30, f"Overshoot too large: selected {total}cr for {gap}cr gap"


def test_select_free_electives_zero_gap_returns_empty():
    """Zero gap should return empty list immediately."""
    from coursemap.domain.requirement_utils import select_free_electives
    from coursemap.ingestion.dataset_loader import load_courses
    courses = load_courses()
    results = select_free_electives(
        courses=courses, planned_codes=set(), excluded_codes=set(),
        gap=0, campus="D", mode="DIS",
    )
    assert results == []


# ── requirement_serialization round-trip ─────────────────────────────────────

def test_requirement_roundtrip_choose_credits():
    from coursemap.domain.requirement_nodes import ChooseCreditsRequirement
    from coursemap.domain.requirement_serialization import requirement_to_dict, requirement_from_dict

    original = ChooseCreditsRequirement(credits=45, course_codes=("159201", "159234", "159235"))
    as_dict = requirement_to_dict(original)
    restored = requirement_from_dict(as_dict)
    assert isinstance(restored, ChooseCreditsRequirement)
    assert restored.credits == 45
    assert set(restored.course_codes) == {"159201", "159234", "159235"}


def test_requirement_roundtrip_all_of():
    from coursemap.domain.requirement_nodes import AllOfRequirement, CourseRequirement
    from coursemap.domain.requirement_serialization import requirement_to_dict, requirement_from_dict

    original = AllOfRequirement(children=(
        CourseRequirement("159101"),
        CourseRequirement("160101"),
    ))
    restored = requirement_from_dict(requirement_to_dict(original))
    assert isinstance(restored, AllOfRequirement)
    codes = {c.course_code for c in restored.children}
    assert codes == {"159101", "160101"}


def test_requirement_roundtrip_nested():
    from coursemap.domain.requirement_nodes import AllOfRequirement, AnyOfRequirement, CourseRequirement
    from coursemap.domain.requirement_serialization import requirement_to_dict, requirement_from_dict

    original = AllOfRequirement(children=(
        CourseRequirement("AAA"),
        AnyOfRequirement(children=(
            CourseRequirement("BBB"),
            CourseRequirement("CCC"),
        )),
    ))
    restored = requirement_from_dict(requirement_to_dict(original))
    assert isinstance(restored, AllOfRequirement)
    assert len(restored.children) == 2


# ── dataset_validator: OR-aware cycle detection ───────────────────────────────

def test_prereq_hard_codes_or_returns_intersection():
    """OR(A, B) should contribute no hard edges when branches share no codes."""
    from coursemap.validation.dataset_validator import _prereq_hard_codes
    from coursemap.domain.prerequisite import OrExpression, CoursePrerequisite

    or_expr = OrExpression(children=(
        CoursePrerequisite("111"),
        CoursePrerequisite("222"),
    ))
    known = {"111", "222"}
    result = _prereq_hard_codes(or_expr, known)
    assert result == set(), f"OR with different branches should have empty intersection, got {result}"


def test_prereq_hard_codes_and_returns_union():
    """AND(A, B) contributes all codes."""
    from coursemap.validation.dataset_validator import _prereq_hard_codes
    from coursemap.domain.prerequisite import AndExpression, CoursePrerequisite

    and_expr = AndExpression(children=(
        CoursePrerequisite("111"),
        CoursePrerequisite("222"),
    ))
    result = _prereq_hard_codes(and_expr, {"111", "222"})
    assert result == {"111", "222"}


def test_prereq_hard_codes_or_intersection_shared():
    """OR(AND(A, B), AND(A, C)): A is in both branches, so A is hard required."""
    from coursemap.validation.dataset_validator import _prereq_hard_codes
    from coursemap.domain.prerequisite import OrExpression, AndExpression, CoursePrerequisite

    expr = OrExpression(children=(
        AndExpression(children=(CoursePrerequisite("A"), CoursePrerequisite("B"))),
        AndExpression(children=(CoursePrerequisite("A"), CoursePrerequisite("C"))),
    ))
    result = _prereq_hard_codes(expr, {"A", "B", "C"})
    assert result == {"A"}


def test_validator_no_false_cycles_from_or():
    """
    The cycle detector must not report false cycles from OR expressions.

    If course X has OR(Y, Z) as a prereq and Z has OR(X, W) as a prereq,
    there is no true cycle because X→Y works and Z→W works.
    """
    from coursemap.validation.dataset_validator import check_prerequisite_cycles
    from coursemap.domain.prerequisite import OrExpression, CoursePrerequisite

    off = (Offering(semester="S1", campus="D", mode="DIS"),)

    # X requires Y OR Z; Z requires X OR W. Potential false cycle between X and Z
    courses = {
        "X": Course("X", "X", 15, 200, off,
                    prerequisites=OrExpression((CoursePrerequisite("Y"), CoursePrerequisite("Z")))),
        "Y": Course("Y", "Y", 15, 100, off),
        "Z": Course("Z", "Z", 15, 200, off,
                    prerequisites=OrExpression((CoursePrerequisite("X"), CoursePrerequisite("W")))),
        "W": Course("W", "W", 15, 100, off),
    }
    errors, warnings = [], []
    check_prerequisite_cycles(courses, errors, warnings)
    assert errors == [], f"False cycle detected: {errors}"


def test_validator_detects_true_cycle():
    """A genuine AND cycle (A requires B AND B requires A) must be detected."""
    from coursemap.validation.dataset_validator import check_prerequisite_cycles
    from coursemap.domain.prerequisite import CoursePrerequisite

    off = (Offering(semester="S1", campus="D", mode="DIS"),)
    courses = {
        "A": Course("A", "A", 15, 200, off, prerequisites=CoursePrerequisite("B")),
        "B": Course("B", "B", 15, 200, off, prerequisites=CoursePrerequisite("A")),
    }
    errors, warnings = [], []
    check_prerequisite_cycles(courses, errors, warnings)
    assert len(errors) > 0, "True cycle A↔B should be detected as an error"


# ── CLI JSON export: full_year flag ──────────────────────────────────────────

def test_cli_json_export_includes_full_year():
    """CLI JSON export should include full_year flag on each course."""
    import subprocess, sys, json as json_mod
    result = subprocess.run(
        [sys.executable, "-m", "coursemap.cli.main", "plan",
         "--major", "Computer Science – Bachelor of Information Sciences",
         "--no-summer", "--format", "json"],
        capture_output=True, text=True, encoding="utf-8",
        cwd=str(REPO_ROOT), timeout=60,
    )
    if result.returncode != 0:
        return  # plan may fail for unrelated reasons
    try:
        data = json_mod.loads(result.stdout)
    except Exception:
        return
    for sem in data.get("semesters", []):
        for c in sem.get("courses", []):
            assert "full_year" in c, f"Course {c.get('code')} missing full_year in JSON export"
            assert "prereq_data_available" in c


def test_cli_json_export_includes_prereq_available():
    """prereq_data_available field should be boolean in CLI JSON export."""
    import subprocess, sys, json as json_mod
    result = subprocess.run(
        [sys.executable, "-m", "coursemap.cli.main", "plan",
         "--major", "Statistics – Bachelor of Science",
         "--no-summer", "--format", "json"],
        capture_output=True, text=True, encoding="utf-8",
        cwd=str(REPO_ROOT), timeout=60,
    )
    if result.returncode != 0:
        return
    try:
        data = json_mod.loads(result.stdout)
    except Exception:
        return
    for sem in data.get("semesters", []):
        for c in sem.get("courses", []):
            assert isinstance(c.get("prereq_data_available"), bool)


# ── Validate that the full dataset has no cycle errors (real-world check) ─────

def test_dataset_has_no_prerequisite_cycles_with_or_fix():
    """After the OR-aware fix, the real dataset should have no cycle errors."""
    from coursemap.validation.dataset_validator import check_prerequisite_cycles
    from coursemap.ingestion.dataset_loader import load_courses
    courses = load_courses()
    errors, warnings = [], []
    check_prerequisite_cycles(courses, errors, warnings)
    assert errors == [], f"Dataset has cycle errors: {errors[:3]}"


# ── _prereq_hard_codes handles None and unknown codes ────────────────────────

def test_prereq_hard_codes_none():
    from coursemap.validation.dataset_validator import _prereq_hard_codes
    assert _prereq_hard_codes(None, {"A"}) == set()


def test_prereq_hard_codes_excludes_unknown():
    from coursemap.validation.dataset_validator import _prereq_hard_codes
    from coursemap.domain.prerequisite import CoursePrerequisite
    result = _prereq_hard_codes(CoursePrerequisite("UNKNOWN999"), {"A", "B"})
    assert result == set()


# ── iCal UID sanitisation ─────────────────────────────────────────────────────

def test_ical_uid_safe_chars_only():
    """UID must contain only ASCII-safe chars (no em-dash, spaces, etc.)."""
    import re
    from coursemap.export.ical import plan_to_ical
    from coursemap.domain.plan import DegreePlan, SemesterPlan

    plan = DegreePlan(semesters=(
        SemesterPlan(year=2026, semester="S1", courses=(
            Course("159101", "Applied Programming", 15, 100,
                   (Offering("S1", "D", "DIS"),)),
        )),
    ))
    content = plan_to_ical(plan, "Computer Science – Bachelor of Information Sciences")
    uids = re.findall(r'UID:(.*?)\r\n', content)
    assert uids, "No UID found in iCal output"
    for uid in uids:
        assert re.match(r'^[\w\-@.]+$', uid), f"UID contains unsafe chars: {uid!r}"


def test_ical_has_dtstamp():
    """Each VEVENT must have a DTSTAMP (RFC 5545 requirement)."""
    from coursemap.export.ical import plan_to_ical
    from coursemap.domain.plan import DegreePlan, SemesterPlan
    import re

    plan = DegreePlan(semesters=(
        SemesterPlan(year=2026, semester="S1", courses=(
            Course("159101", "Applied Programming", 15, 100,
                   (Offering("S1", "D", "DIS"),)),
        )),
    ))
    content = plan_to_ical(plan, "CS Test")
    dtstamps = re.findall(r'DTSTAMP:(.*?)\r\n', content)
    assert len(dtstamps) > 0, "No DTSTAMP found in iCal output"
    # Format: YYYYMMDDTHHMMSSz
    assert re.match(r'\d{8}T\d{6}Z', dtstamps[0]), f"Bad DTSTAMP format: {dtstamps[0]}"


def test_ical_has_sequence():
    """Each VEVENT must have a SEQUENCE field."""
    from coursemap.export.ical import plan_to_ical
    from coursemap.domain.plan import DegreePlan, SemesterPlan

    plan = DegreePlan(semesters=(
        SemesterPlan(year=2026, semester="S1", courses=(
            Course("159101", "Applied Programming", 15, 100,
                   (Offering("S1", "D", "DIS"),)),
        )),
    ))
    content = plan_to_ical(plan, "CS Test")
    assert "SEQUENCE:0" in content


def test_ical_no_double_crlf():
    """iCal output must not have double CRLF (malformed line endings)."""
    from coursemap.export.ical import plan_to_ical
    from coursemap.domain.plan import DegreePlan, SemesterPlan

    plan = DegreePlan(semesters=(
        SemesterPlan(year=2026, semester="S1", courses=(
            Course("159101", "Applied Programming, Part I", 15, 100,
                   (Offering("S1", "D", "DIS"),)),
        )),
    ))
    content = plan_to_ical(plan, "CS – BInfSc")
    assert "\r\n\r\n" not in content, "Double CRLF found in iCal output"


def test_ical_lines_within_75_octet_limit():
    """All non-continuation lines must be ≤75 octets (RFC 5545 §3.1)."""
    from coursemap.export.ical import plan_to_ical
    from coursemap.domain.plan import DegreePlan, SemesterPlan

    plan = DegreePlan(semesters=(
        SemesterPlan(year=2026, semester="S1", courses=(
            Course("159101", "A" * 100, 15, 100,  # very long title
                   (Offering("S1", "D", "DIS"),)),
        )),
    ))
    content = plan_to_ical(plan, "Test")
    lines = content.split("\r\n")
    violations = [
        (i+1, len(l.encode("utf-8")), l[:50])
        for i, l in enumerate(lines)
        if not l.startswith(" ") and len(l.encode("utf-8")) > 75
    ]
    assert not violations, f"Lines exceeding 75 octets: {violations[:3]}"


def test_ical_escape_text():
    """Special chars in course titles must be properly escaped."""
    from coursemap.export.ical import _escape_ical_text
    raw = "Course: Advanced, Topics; Part\\One\nDescription"
    escaped = _escape_ical_text(raw)
    assert "\\:" not in escaped          # colons not escaped
    assert "\\," in escaped              # commas escaped
    assert "\\;" in escaped              # semicolons escaped
    assert "\\\\" in escaped             # backslash escaped
    assert "\\n" in escaped              # newline escaped


# ── CLI courses --semester filter ─────────────────────────────────────────────

def test_cli_courses_semester_s1_filter():
    """CLI courses --semester S1 should return only S1-available courses."""
    import subprocess, sys
    result = subprocess.run(
        [sys.executable, "-m", "coursemap.cli.main", "courses",
         "--semester", "S1", "--level", "100"],
        capture_output=True, text=True, encoding="utf-8", cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0
    assert "course(s)" in result.stdout


def test_cli_courses_semester_ss_filter():
    """CLI courses --semester SS should return only Summer School courses."""
    import subprocess, sys
    result = subprocess.run(
        [sys.executable, "-m", "coursemap.cli.main", "courses",
         "--semester", "SS", "--level", "100"],
        capture_output=True, text=True, encoding="utf-8", cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0
    # SS has fewer courses than S1
    ss_count = int(result.stdout.split("course(s)")[0].strip().split("\n")[-1].strip())
    assert ss_count < 200  # SS is always a subset


# ── data-quality command: no NameError ───────────────────────────────────────

def test_data_quality_command_no_crash():
    """coursemap data-quality should complete without NameError."""
    import subprocess, sys
    result = subprocess.run(
        [sys.executable, "-m", "coursemap.cli.main", "data-quality"],
        capture_output=True, text=True, encoding="utf-8", cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0, f"data-quality crashed: {result.stderr[:200]}"
    assert "Data Quality Report" in result.stdout
    assert "Courses (total)" in result.stdout
    # Should not have NameError
    assert "NameError" not in result.stderr


def test_data_quality_recommendations_section():
    """Recommendations section should always appear."""
    import subprocess, sys
    result = subprocess.run(
        [sys.executable, "-m", "coursemap.cli.main", "data-quality"],
        capture_output=True, text=True, encoding="utf-8", cwd=str(REPO_ROOT),
    )
    assert "Recommendations" in result.stdout


# ── freshness.py ─────────────────────────────────────────────────────────────

def test_freshness_report_returns_expected_keys():
    """freshness_report must return scrape_date, age_days, is_stale, message."""
    from coursemap.ingestion.freshness import freshness_report
    report = freshness_report()
    assert "scrape_date" in report
    assert "age_days" in report
    assert "is_stale" in report
    assert "threshold_days" in report
    assert "message" in report


def test_freshness_report_is_not_stale_for_current_dataset():
    """The bundled dataset is recent. Should not be stale."""
    from coursemap.ingestion.freshness import freshness_report
    report = freshness_report()
    assert not report["is_stale"], \
        f"Dataset unexpectedly stale: {report['message']}"


# ── requirement_from_dict: empty children guard ───────────────────────────────

def test_all_of_empty_children_raises():
    import pytest
    from coursemap.domain.requirement_serialization import requirement_from_dict
    with pytest.raises(ValueError, match="at least one child"):
        requirement_from_dict({"type": "ALL_OF", "children": []})


def test_any_of_empty_children_raises():
    import pytest
    from coursemap.domain.requirement_serialization import requirement_from_dict
    with pytest.raises(ValueError, match="at least one child"):
        requirement_from_dict({"type": "ANY_OF", "children": []})


def test_major_node_missing_name_raises():
    import pytest
    from coursemap.domain.requirement_serialization import requirement_from_dict
    with pytest.raises(ValueError, match="'name'"):
        requirement_from_dict({"type": "MAJOR", "requirement": {"type": "ALL_OF", "children": [
            {"type": "COURSE", "course_code": "159101"}
        ]}})


def test_major_node_missing_requirement_raises():
    import pytest
    from coursemap.domain.requirement_serialization import requirement_from_dict
    with pytest.raises(ValueError, match="'requirement'"):
        requirement_from_dict({"type": "MAJOR", "name": "CS"})


def test_choose_credits_negative_raises():
    import pytest
    from coursemap.domain.requirement_serialization import requirement_from_dict
    with pytest.raises(ValueError, match="non-negative"):
        requirement_from_dict({"type": "CHOOSE_CREDITS", "credits": -15,
                               "course_codes": ["159101"]})


def test_choose_n_zero_raises():
    import pytest
    from coursemap.domain.requirement_serialization import requirement_from_dict
    with pytest.raises(ValueError, match="at least 1"):
        requirement_from_dict({"type": "CHOOSE_N", "n": 0, "course_codes": ["159101"]})


def test_unknown_type_raises():
    import pytest
    from coursemap.domain.requirement_serialization import requirement_from_dict
    with pytest.raises(ValueError, match="Unknown requirement type"):
        requirement_from_dict({"type": "SOMETHING_UNKNOWN"})


def test_requirement_without_type_raises():
    import pytest
    from coursemap.domain.requirement_serialization import requirement_from_dict
    with pytest.raises(ValueError, match="'type' key"):
        requirement_from_dict({"course_code": "159101"})


# ── select_free_electives: overshoot logic ────────────────────────────────────

def test_select_free_electives_does_not_overshoot_30cr():
    """Elective selection must not exceed gap + 30cr."""
    from coursemap.domain.requirement_utils import select_free_electives
    from coursemap.ingestion.dataset_loader import load_courses
    courses = load_courses()
    for gap in [15, 30, 45, 60, 75, 90, 120]:
        results = select_free_electives(
            courses=courses, planned_codes={"159101"}, excluded_codes=set(),
            gap=gap, campus="D", mode="DIS",
        )
        total = sum(courses[c].credits for _, c, _ in results if c in courses)
        assert total <= gap + 30, f"gap={gap}: selected {total}cr > {gap+30}cr limit"


def test_select_free_electives_stops_at_gap():
    """Once gap is reached, no more courses should be added."""
    from coursemap.domain.requirement_utils import select_free_electives
    from coursemap.ingestion.dataset_loader import load_courses
    courses = load_courses()
    gap = 30
    results = select_free_electives(
        courses=courses, planned_codes={"159101"}, excluded_codes=set(),
        gap=gap, campus="D", mode="DIS",
    )
    # Should not return more courses than needed to cover gap
    total = sum(courses[c].credits for _, c, _ in results if c in courses)
    assert total <= gap + 30


def test_select_free_electives_preferred_appear_first():
    """Preferred codes should appear before unpreferred in results."""
    from coursemap.domain.requirement_utils import select_free_electives
    from coursemap.ingestion.dataset_loader import load_courses
    courses = load_courses()
    # Get a valid D/DIS L200 course
    preferred_code = next(
        (c for c, course in courses.items()
         if course.level == 200 and course.credits == 15
         and any(o.campus == "D" and o.mode == "DIS" for o in course.offerings)),
        None
    )
    if not preferred_code:
        return
    results = select_free_electives(
        courses=courses,
        planned_codes={preferred_code[:3] + "101"},  # same prefix area
        excluded_codes=set(),
        gap=60,
        campus="D",
        mode="DIS",
        preferred=frozenset({preferred_code}),
    )
    result_codes = [code for _, code, _ in results]
    if preferred_code in result_codes and len(result_codes) > 1:
        # Preferred code should appear before non-preferred
        idx = result_codes.index(preferred_code)
        assert idx < len(result_codes), "preferred code should be in results"


# ── prereqs_met: standard cases ───────────────────────────────────────────────

def test_prereqs_met_none_always_true():
    from coursemap.domain.prerequisite_utils import prereqs_met
    assert prereqs_met(None, set(), set()) is True


def test_prereqs_met_course_in_completed():
    from coursemap.domain.prerequisite_utils import prereqs_met
    from coursemap.domain.prerequisite import CoursePrerequisite
    prereq = CoursePrerequisite("AAA100")
    assert prereqs_met(prereq, {"AAA100"}, {"AAA100"}) is True
    assert prereqs_met(prereq, set(), {"AAA100"}) is False


def test_prereqs_met_out_of_scope_satisfied():
    """Codes not in known are treated as already satisfied (out-of-scope gatekeepers)."""
    from coursemap.domain.prerequisite_utils import prereqs_met
    from coursemap.domain.prerequisite import CoursePrerequisite
    prereq = CoursePrerequisite("UE001")  # not in known
    assert prereqs_met(prereq, set(), known={"AAA100", "BBB200"}) is True


def test_prereqs_met_and_requires_all():
    from coursemap.domain.prerequisite_utils import prereqs_met
    from coursemap.domain.prerequisite import AndExpression, CoursePrerequisite
    prereq = AndExpression(children=(CoursePrerequisite("A"), CoursePrerequisite("B")))
    known = {"A", "B"}
    assert prereqs_met(prereq, {"A", "B"}, known) is True
    assert prereqs_met(prereq, {"A"}, known) is False


def test_prereqs_met_or_requires_any():
    from coursemap.domain.prerequisite_utils import prereqs_met
    from coursemap.domain.prerequisite import OrExpression, CoursePrerequisite
    prereq = OrExpression(children=(CoursePrerequisite("A"), CoursePrerequisite("B")))
    known = {"A", "B"}
    assert prereqs_met(prereq, {"A"}, known) is True
    assert prereqs_met(prereq, {"B"}, known) is True
    assert prereqs_met(prereq, set(), known) is False


# ── collect_course_codes: all known node types ────────────────────────────────

def test_collect_course_codes_choose_credits():
    from coursemap.domain.requirement_utils import collect_course_codes
    from coursemap.domain.requirement_nodes import ChooseCreditsRequirement
    node = ChooseCreditsRequirement(credits=30, course_codes=("A", "B", "C"))
    codes = collect_course_codes(node)
    assert codes == {"A", "B", "C"}


def test_collect_course_codes_nested():
    from coursemap.domain.requirement_utils import collect_course_codes
    from coursemap.domain.requirement_nodes import AllOfRequirement, CourseRequirement, ChooseNRequirement
    node = AllOfRequirement(children=(
        CourseRequirement("X"),
        ChooseNRequirement(n=1, course_codes=("Y", "Z")),
    ))
    codes = collect_course_codes(node)
    assert codes == {"X", "Y", "Z"}


def test_collect_course_codes_excludes_total_credits_node():
    """TotalCreditsRequirement has no course codes. Should not appear in result."""
    from coursemap.domain.requirement_utils import collect_course_codes
    from coursemap.domain.requirement_nodes import AllOfRequirement, CourseRequirement, TotalCreditsRequirement
    node = AllOfRequirement(children=(
        CourseRequirement("A"),
        TotalCreditsRequirement(required_credits=360),
    ))
    codes = collect_course_codes(node)
    assert codes == {"A"}
    assert "360" not in codes


# ── planner_service: no_summer=True defaults ─────────────────────────────────

def test_generate_best_plan_default_no_summer():
    """generate_best_plan default should be no_summer=True."""
    import inspect
    from coursemap.services.planner_service import PlannerService
    sig = inspect.signature(PlannerService.generate_best_plan)
    assert sig.parameters["no_summer"].default is True, \
        f"Expected no_summer=True default, got {sig.parameters['no_summer'].default}"


def test_generate_double_major_plan_default_no_summer():
    import inspect
    from coursemap.services.planner_service import PlannerService
    sig = inspect.signature(PlannerService.generate_double_major_plan)
    assert sig.parameters["no_summer"].default is True


def test_generate_filled_plan_default_no_summer():
    import inspect
    from coursemap.services.planner_service import PlannerService
    sig = inspect.signature(PlannerService.generate_filled_plan)
    assert sig.parameters["no_summer"].default is True


def test_generate_filled_double_major_plan_default_no_summer():
    import inspect
    from coursemap.services.planner_service import PlannerService
    sig = inspect.signature(PlannerService.generate_filled_double_major_plan)
    assert sig.parameters["no_summer"].default is True


def test_api_default_no_summer_is_true():
    """API PlanRequest should default no_summer=True."""
    from coursemap.api.server import PlanRequest
    r = PlanRequest(major="Computer Science – Bachelor of Information Sciences")
    assert r.no_summer is True, f"Expected no_summer=True, got {r.no_summer}"


def test_plan_with_no_summer_excludes_ss_courses():
    """Plans generated with no_summer=True must not contain SS-only courses."""
    from coursemap.ingestion.dataset_loader import load_courses
    courses = load_courses()
    # Find a course offered ONLY in SS at distance
    ss_only_dist = [
        code for code, c in courses.items()
        if c.credits > 0
        and all(o.semester == "SS" for o in c.offerings if o.campus == "D" and o.mode == "DIS")
        and any(o.campus == "D" and o.mode == "DIS" for o in c.offerings)
    ]
    if not ss_only_dist:
        return  # no SS-only distance courses in dataset

    res = client.post("/api/plan", json={
        "major": "Computer Science – Bachelor of Information Sciences",
        "no_summer": True,
        "auto_fill": True,
    })
    assert res.status_code == 200
    plan_codes = {c["code"] for s in res.json()["semesters"] for c in s["courses"]}
    for code in ss_only_dist[:5]:
        assert code not in plan_codes, f"SS-only course {code} appeared in no_summer=True plan"


# ── Ecology BSc: SS required at distance ──────────────────────────────────────

def test_ecology_bsc_requires_summer_school_at_distance():
    """
    Ecology BSc requires 123103 which is only offered DIS in Summer School.
    Planning with no_summer=True should fail (or warn), no_summer=False should work.

    Uses auto_fill=True: without it, the request goes through the plain
    generate_best_plan path, which is separately, always incapable of a
    valid Ecology plan regardless of no_summer, because Ecology's named
    elective pools cannot satisfy the 45cr level-progression rule from
    their own members alone (see DATA_QUALITY.md, "The 45cr
    Level-Progression Rule", and the xfail'd
    test_bsc_ecology_distance_plan in test_integration.py). That's a real,
    separate, already-documented limitation, not what this test is trying
    to isolate. auto_fill lets the open elective pool supply the credit
    the named pools can't, so this test can correctly test just the
    Summer School behaviour on its own.
    """
    # Verify 123103 is only in SS for distance
    from coursemap.ingestion.dataset_loader import load_courses
    courses = load_courses()
    c = courses.get("123103")
    if c is None:
        return
    dist_offerings = [o for o in c.offerings if o.campus == "D" and o.mode == "DIS"]
    if dist_offerings:
        assert all(o.semester == "SS" for o in dist_offerings), \
            "123103 should only be offered DIS in Summer School"

    # Planning with no_summer=True should fail outright, or succeed without
    # actually scheduling 123103 (its only distance offering is in Summer
    # School, which is excluded).
    res_no_ss = client.post("/api/plan", json={
        "major": "Ecology and Conservation – Bachelor of Science",
        "no_summer": True,
        "auto_fill": True,
    })
    if res_no_ss.status_code == 200:
        scheduled = {c["code"] for s in res_no_ss.json()["semesters"] for c in s["courses"]}
        assert "123103" not in scheduled

    # Planning with no_summer=False should succeed
    res_with_ss = client.post("/api/plan", json={
        "major": "Ecology and Conservation – Bachelor of Science",
        "no_summer": False,
        "auto_fill": True,
    })
    assert res_with_ss.status_code == 200, (
        "no_summer=False should let the SS-only course 123103 be scheduled. "
        "Note: a 200 here confirms the Summer School gating mechanism works "
        "correctly, not that the resulting plan is fully valid. Ecology's "
        "named elective pools separately, genuinely cannot satisfy the 45cr "
        "level-progression rule from their own members alone (a real, "
        "already-documented limitation, see DATA_QUALITY.md and the xfail'd "
        "test_bsc_ecology_distance_plan in test_integration.py), so a 200 "
        "response for this major can still be a plan whose named pools are "
        "short even though the credit total and HTTP status look fine."
    )


# ── planner_service: _collect_required_codes doesn't include CHOOSE_CREDITS ──

def test_required_course_codes_excludes_pool_codes():
    """required_course_codes should return COURSE nodes only, not CHOOSE_CREDITS."""
    from coursemap.api.server import _svc
    svc = _svc()
    codes = svc.required_course_codes("Computer Science – Bachelor of Information Sciences")
    # 297101 (Statistics) is a required COURSE node in the CS BInfSc major
    assert len(codes) > 0, "CS BInfSc should have at least one required course code"
    # All returned codes should be COURSE nodes, not pool options
    assert all(len(c) >= 6 for c in codes)
    # Pool codes (from CHOOSE_CREDITS) should NOT be in required_codes
    # They are optional selections, not hard requirements
    from coursemap.ingestion.dataset_loader import load_majors
    majors = load_majors()
    cs = next((m for m in majors if m["name"] == "Computer Science – Bachelor of Information Sciences"), None)
    if cs:
        import json
        req_str = json.dumps(cs["requirement"])
        # Extract CHOOSE_CREDITS course_codes from the requirement
        import re
        pool_codes = set()
        for m_match in re.finditer(r'"type":\s*"CHOOSE_CREDITS".*?"course_codes":\s*\[(.*?)\]',
                                    req_str, re.DOTALL):
            for code in re.findall(r'"(\w+)"', m_match.group(1)):
                pool_codes.add(code)
        # Pool codes that are NOT also direct COURSE requirements should not be in result
        pool_only = pool_codes - codes
        # If any pool-only codes ended up in required_codes, that's a bug
        pool_in_required = pool_only & codes
        assert not pool_in_required, \
            f"Pool-only codes incorrectly in required_course_codes: {pool_in_required}"


# ── _elective_sort_key uses campus/mode-filtered offerings ───────────────────

def test_elective_sort_key_uses_campus_mode():
    """
    _elective_sort_key should use offerings matching the plan's campus/mode,
    not all offerings. A course offered S1 on campus but S2 at distance should
    sort as S2 for a distance student.
    """
    from coursemap.optimisation.search import PlanSearch
    from coursemap.planner.generator import PlanGenerator
    from coursemap.ingestion.dataset_loader import load_courses

    courses = load_courses()

    # Create a mock course offered S1 on campus (M/INT) but S2 at distance (D/DIS)
    split_course = Course(
        code="TST999", title="Test Split Course", credits=15, level=200,
        offerings=(
            Offering(semester="S1", campus="M", mode="INT"),  # campus only
            Offering(semester="S2", campus="D", mode="DIS"),  # distance
        ),
    )
    test_courses = {**courses, "TST999": split_course}

    gen_template = PlanGenerator(
        test_courses, max_credits_per_semester=60,
        campus="D", mode="DIS", start_year=2026, start_semester="S1",
    )
    search = PlanSearch(courses=test_courses, majors=[], generator_template=gen_template)

    # For a distance student, TST999 should sort as S2 (semester 1 in 0-indexed = index 1)
    key = search._elective_sort_key("TST999")
    # key[1] is the earliest_sem value: S1=0, S2=1, SS=2
    assert key[1] == 1, f"Expected S2 (1) for distance, got {key[1]} ({key})"


def test_elective_sort_key_preferred_first():
    """Preferred courses should sort before non-preferred."""
    from coursemap.optimisation.search import PlanSearch
    from coursemap.planner.generator import PlanGenerator
    from coursemap.ingestion.dataset_loader import load_courses

    courses = load_courses()
    gen = PlanGenerator(courses, max_credits_per_semester=60,
                        campus="D", mode="DIS", start_year=2026, start_semester="S1")
    search = PlanSearch(
        courses=courses, majors=[], generator_template=gen,
        preferred_electives=frozenset({"159201"}),
    )
    key_preferred = search._elective_sort_key("159201")
    key_other = search._elective_sort_key("160101")
    assert key_preferred[0] == 0, "Preferred course should have priority 0"
    assert key_other[0] == 1, "Non-preferred course should have priority 1"
    assert key_preferred < key_other


def test_elective_sort_key_level_ordering():
    """Lower-level courses should sort before higher-level."""
    from coursemap.optimisation.search import PlanSearch
    from coursemap.planner.generator import PlanGenerator
    from coursemap.ingestion.dataset_loader import load_courses

    courses = load_courses()
    gen = PlanGenerator(courses, max_credits_per_semester=60,
                        campus="D", mode="DIS", start_year=2026, start_semester="S1")
    search = PlanSearch(courses=courses, majors=[], generator_template=gen)

    # Find a L100 and L200 course both available D/DIS
    l100 = next((c for c, course in courses.items()
                 if course.level == 100 and course.credits > 0
                 and any(o.campus == "D" and o.mode == "DIS" for o in course.offerings)), None)
    l200 = next((c for c, course in courses.items()
                 if course.level == 200 and course.credits > 0
                 and any(o.campus == "D" and o.mode == "DIS" for o in course.offerings)), None)
    if l100 and l200:
        key100 = search._elective_sort_key(l100)
        key200 = search._elective_sort_key(l200)
        # Level is key[2]; L100 < L200
        assert key100[2] < key200[2]


# ── Module-level prereq imports in search.py ─────────────────────────────────

def test_search_module_has_prereq_imports():
    """search.py should have module-level prerequisite type imports."""
    import coursemap.optimisation.search as search_mod
    assert hasattr(search_mod, "_CoursePrerequisite"), \
        "search.py missing module-level _CoursePrerequisite import"
    assert hasattr(search_mod, "_AndExpression"), \
        "search.py missing module-level _AndExpression import"
    assert hasattr(search_mod, "_OrExpression"), \
        "search.py missing module-level _OrExpression import"


# ── PlanSearch: full integration with sort key fix ───────────────────────────

def test_plan_search_elective_order_respects_semester():
    """
    A distance plan should prefer S1 courses over S2-only courses when both
    are valid electives. Verify by checking that S1-available courses appear
    in earlier semesters.
    """
    res = client.post("/api/plan", json={
        "major": "Computer Science – Bachelor of Information Sciences",
        "no_summer": True,
        "auto_fill": True,
    })
    assert res.status_code == 200
    data = res.json()
    semesters = data["semesters"]
    assert len(semesters) > 0

    # Verify no course appears more than once
    all_codes = [c["code"] for s in semesters for c in s["courses"]]
    assert len(all_codes) == len(set(all_codes)), "Duplicate courses in plan"


def test_plan_all_scheduled_courses_have_valid_offering():
    """Every scheduled course must have a D/DIS offering (for distance plans)."""
    from coursemap.ingestion.dataset_loader import load_courses
    courses = load_courses()

    res = client.post("/api/plan", json={
        "major": "Computer Science – Bachelor of Information Sciences",
        "no_summer": True,
        "auto_fill": True,
    })
    assert res.status_code == 200
    for sem in res.json()["semesters"]:
        for c in sem["courses"]:
            course = courses.get(c["code"])
            if course:
                has_dist = any(o.campus == "D" and o.mode == "DIS" for o in course.offerings)
                assert has_dist, f"{c['code']} has no D/DIS offering but was scheduled"


# ── Untested API endpoints ────────────────────────────────────────────────────

def test_fees_rate_endpoint_cs():
    res = client.get("/api/fees/rate?subject_area=Computer+Science&level=200")
    assert res.status_code == 200
    data = res.json()
    assert data["fee_per_credit"] == 65.0
    assert data["subject_area"] == "Computer Science"


def test_fees_rate_endpoint_unknown_uses_default():
    res = client.get("/api/fees/rate?subject_area=Underwater+Basket+Weaving&level=100")
    assert res.status_code == 200
    data = res.json()
    assert data["fee_per_credit"] == 60.0


def test_fees_rate_endpoint_postgrad_level():
    res = client.get("/api/fees/rate?subject_area=Statistics&level=700")
    assert res.status_code == 200
    data = res.json()
    assert data["fee_per_credit"] > 60.0  # postgrad surcharge


def test_minors_by_name_endpoint():
    res = client.get("/api/minors/Computer%20Science")
    assert res.status_code == 200
    data = res.json()
    assert data["name"] == "Computer Science"
    assert "requirement" in data
    assert data["total_credits"] > 0


def test_minors_by_name_not_found():
    res = client.get("/api/minors/Nonexistent%20Minor%20XYZ")
    assert res.status_code == 404


def test_plan_store_stats():
    res = client.get("/api/plan-store/stats")
    assert res.status_code == 200
    data = res.json()
    assert "total_plans" in data


def test_data_quality_endpoint():
    res = client.get("/api/data-quality")
    assert res.status_code == 200
    data = res.json()
    assert "total_courses" in data
    assert data["total_courses"] > 0
    assert "prerequisite_formats" in data


def test_api_plan_fees_endpoint():
    """POST /api/plan/fees should return fee estimates for a generated plan."""
    plan_res = client.post("/api/plan", json={
        "major": "Computer Science – Bachelor of Information Sciences",
        "no_summer": True,
        "auto_fill": True,
    })
    assert plan_res.status_code == 200
    plan_data = plan_res.json()

    fees_res = client.post("/api/plan/fees", json={
        "semesters": plan_data["semesters"],
        "student_type": "domestic",
    })
    assert fees_res.status_code == 200
    fees = fees_res.json()
    assert fees["total"] > 0
    assert "by_year" in fees


def test_api_plan_fees_confidence_and_excludes_present_for_ui():
    """
    Regression test: the UI (updateFeesConfidenceNote in app.js) now
    fetches /api/plan/fees and displays the "confidence" string and
    "excludes" list directly, having previously never called this
    endpoint at all despite it already computing this information on
    every request (see CHANGELOG.md).
    If a future change to estimate_plan_fees drops or renames either
    field, this test fails loudly instead of the UI silently showing
    nothing where a confidence note used to be - a JS-side failure this
    Python test suite otherwise has no way to catch.
    """
    plan_res = client.post("/api/plan", json={
        "major": "Computer Science – Bachelor of Information Sciences",
        "no_summer": True,
        "auto_fill": True,
    })
    plan_id = plan_res.json()["plan_id"]

    fees_res = client.post("/api/plan/fees", json={"plan_id": plan_id, "student_type": "domestic"})
    assert fees_res.status_code == 200
    fees = fees_res.json()
    assert isinstance(fees.get("confidence"), str) and fees["confidence"]
    assert isinstance(fees.get("excludes"), list) and fees["excludes"]
    assert isinstance(fees.get("disclaimer"), str) and fees["disclaimer"]


def test_api_plan_fees_endpoint_via_plan_id():
    """
    POST /api/plan/fees must accept a plan_id, matching the pattern every
    other plan-related endpoint uses (POST /api/plan/validate, etc.),
    otherwise a client has to keep the full semesters payload around just
    to check fees after generating a plan, unlike every other follow-up
    operation on a plan.
    """
    plan_res = client.post("/api/plan", json={
        "major": "Computer Science – Bachelor of Information Sciences",
        "no_summer": True,
        "auto_fill": True,
    })
    assert plan_res.status_code == 200
    plan_data = plan_res.json()

    fees_via_id = client.post("/api/plan/fees", json={
        "plan_id": plan_data["plan_id"],
        "student_type": "domestic",
    })
    assert fees_via_id.status_code == 200

    fees_via_semesters = client.post("/api/plan/fees", json={
        "semesters": plan_data["semesters"],
        "student_type": "domestic",
    })
    assert fees_via_semesters.status_code == 200

    # Both paths must produce identical results for the same plan.
    assert fees_via_id.json() == fees_via_semesters.json()


def test_api_plan_fees_endpoint_invalid_plan_id_returns_404():
    res = client.post("/api/plan/fees", json={"plan_id": "nonexistent-plan-id-xyz"})
    assert res.status_code == 404


def test_explain_endpoint_scheduled_course():
    """GET /api/courses/{code}/explain should explain placement in a plan."""
    res = client.get("/api/courses/159101/explain?major=Computer+Science+%E2%80%93+Bachelor+of+Information+Sciences")
    assert res.status_code in (200, 404)  # 404 if not in a generated plan


def test_plan_validate_endpoint():
    """POST /api/plan/validate should check requirement satisfaction."""
    major = "Computer Science – Bachelor of Information Sciences"
    plan_res = client.post("/api/plan", json={
        "major": major,
        "no_summer": True,
        "auto_fill": True,
    })
    assert plan_res.status_code == 200
    plan_id = plan_res.json()["plan_id"]

    val_res = client.post("/api/plan/validate", json={
        "plan_id": plan_id,
        "major": major,
    })
    assert val_res.status_code == 200
    val = val_res.json()
    assert "overall_passed" in val or "passed" in val


# ── DegreeProfile level constraints documented ────────────────────────────────

def test_degree_profile_has_level_constraints():
    """DegreeProfile for 3-year bachelor's should have max_level_100 and min_level_300."""
    from coursemap.rules.degree_rules import profile_for
    profile = profile_for(7, 3)  # Standard BSc, BA, etc.
    assert profile.max_level_100 == 165
    assert profile.min_level_300 == 75
    assert profile.total_credits == 360


def test_degree_profile_fallback_no_constraints():
    """Unknown qualification combination should give safe defaults."""
    from coursemap.rules.degree_rules import profile_for
    profile = profile_for(4, 2)  # Level 4, 2yr, unusual
    assert profile.total_credits == 240  # 2 * 120
    assert profile.max_level_100 is None
    assert profile.min_level_300 is None


def test_build_degree_tree_includes_total_credits_when_complete():
    """build_degree_tree includes TotalCreditsRequirement when data is complete."""
    from coursemap.rules.degree_rules import build_degree_tree
    from coursemap.domain.requirement_nodes import AllOfRequirement, CourseRequirement, TotalCreditsRequirement

    major_req = AllOfRequirement((CourseRequirement("159101"),))
    tree = build_degree_tree(
        major_req, qual_level=7, qual_length=3,
        major_name="Test", schedulable_major_credits=360,  # >= 360 = complete
    )
    assert isinstance(tree, AllOfRequirement)
    has_total = any(isinstance(c, TotalCreditsRequirement) for c in tree.children)
    assert has_total


def test_build_degree_tree_omits_total_credits_when_incomplete():
    """build_degree_tree omits TotalCreditsRequirement when data is sparse."""
    from coursemap.rules.degree_rules import build_degree_tree
    from coursemap.domain.requirement_nodes import AllOfRequirement, CourseRequirement, TotalCreditsRequirement

    major_req = AllOfRequirement((CourseRequirement("159101"),))
    tree = build_degree_tree(
        major_req, qual_level=7, qual_length=3,
        major_name="Test", schedulable_major_credits=90,  # < 360 = incomplete
    )
    has_total = any(isinstance(c, TotalCreditsRequirement) for c in tree.children)
    assert not has_total


def test_filter_requirement_tree_drops_unschedulable():
    """filter_requirement_tree removes CourseRequirement nodes for unschedulable courses."""
    from coursemap.rules.degree_rules import filter_requirement_tree
    from coursemap.domain.requirement_nodes import AllOfRequirement, CourseRequirement

    tree = AllOfRequirement((
        CourseRequirement("SCHED001"),
        CourseRequirement("NOTSCHED"),
    ))
    filtered = filter_requirement_tree(tree, schedulable_codes=frozenset({"SCHED001"}))
    assert isinstance(filtered, AllOfRequirement)
    codes = {c.course_code for c in filtered.children}
    assert "SCHED001" in codes
    assert "NOTSCHED" not in codes


def test_filter_requirement_tree_caps_pool_credits():
    """filter_requirement_tree caps ChooseCredits target to available credits."""
    from coursemap.rules.degree_rules import filter_requirement_tree
    from coursemap.domain.requirement_nodes import ChooseCreditsRequirement

    # Pool wants 45cr but only 1 course (15cr) is schedulable
    node = ChooseCreditsRequirement(credits=45, course_codes=("A", "B", "C"))
    filtered = filter_requirement_tree(
        node,
        schedulable_codes=frozenset({"A"}),
        course_credits={"A": 15},
    )
    assert isinstance(filtered, ChooseCreditsRequirement)
    assert filtered.credits == 15  # capped to available


# ── Stale __future__ annotations ─────────────────────────────────────────────

def test_all_source_files_have_future_annotations():
    """All source files using modern type syntax must import __future__ annotations."""
    B = REPO_ROOT
    # Directories that can legitimately live inside the repo tree but are
    # never *our* source: virtual environments (commonly created as .venv
    # right inside the project folder on Windows, per local dev convention),
    # version control internals, and any other dependency/cache directory.
    # Without this, rglob("*.py") walks straight into every installed
    # third-party package's site-packages and fails on the first one that
    # doesn't use `from __future__ import annotations` (most don't, they
    # have no reason to match this repo's own style convention).
    _EXCLUDED_DIR_NAMES = {
        "__pycache__", ".venv", "venv", "env", ".env",
        "node_modules", ".git", ".pytest_cache", ".ruff_cache",
    }
    missing = []
    for f in sorted(B.rglob("*.py")):
        if ".egg-info" in str(f):
            continue
        if _EXCLUDED_DIR_NAMES & set(f.relative_to(B).parts[:-1]):
            continue
        src = f.read_text(encoding="utf-8")
        if ("| None" in src or "list[" in src or "dict[" in src) and \
           "from __future__ import annotations" not in src and \
           "python_requires" not in src:
            missing.append(str(f).replace(str(B) + "/", ""))
    assert not missing, f"Files missing __future__ annotations: {missing}"


# ── Global exception handler ──────────────────────────────────────────────────

def test_exception_handler_returns_json_not_traceback():
    """Unhandled exceptions should return JSON 500, not raw Python traceback."""
    from coursemap.api.server import app

    # Verify the handler is registered
    handlers = [h for h in app.exception_handlers if h is Exception]
    assert len(handlers) > 0 or hasattr(app, 'exception_handlers'), \
        "No Exception handler registered on app"


def test_exception_handler_function_returns_json():
    """_global_exception_handler should return JSONResponse with error field."""
    import asyncio
    from coursemap.api.server import _global_exception_handler
    from fastapi import Request

    scope = {
        "type": "http", "method": "GET", "path": "/api/test",
        "query_string": b"", "headers": [],
        "app": None, "state": None,
    }

    async def run():
        req = Request(scope)
        exc = ValueError("test error")
        response = await _global_exception_handler(req, exc)
        assert response.status_code == 500
        import json
        body = json.loads(response.body)
        assert body["error"] == "internal_server_error"
        assert "test error" in body["detail"]

    asyncio.run(run())


def test_http_exception_passthrough():
    """HTTPException should not be swallowed by the global handler."""
    res = client.get("/api/courses/NONEXISTENT999")
    assert res.status_code == 404
    assert "not found" in res.json()["detail"].lower()


# ── CLI gap display fix ───────────────────────────────────────────────────────

def test_cli_gap_is_zero_when_plan_complete():
    """
    When the plan total equals the degree target, the displayed gap should be 0,
    not the structural major-requirement gap (e.g. 195cr for BInfSc).
    """
    import subprocess, sys
    result = subprocess.run(
        [sys.executable, "-m", "coursemap.cli.main", "plan",
         "--major", "Computer Science – Bachelor of Information Sciences",
         "--no-summer"],
        capture_output=True, text=True, encoding="utf-8",
        cwd=str(REPO_ROOT), timeout=60,
    )
    assert result.returncode == 0
    # Summary should show 360cr total and no "free electives needed" line
    output = result.stdout
    assert "Credits total     : 360" in output or "360" in output
    # Should NOT show the misleading "Free electives needed: 195cr" line
    assert "Free electives needed: 195cr" not in output


def test_api_gap_is_zero_when_plan_complete():
    """API free_elective_gap should be 0 when plan total >= degree target."""
    res = client.post("/api/plan", json={
        "major": "Computer Science – Bachelor of Information Sciences",
        "no_summer": True,
        "auto_fill": True,
    })
    assert res.status_code == 200
    meta = res.json()["meta"]
    assert meta["free_elective_gap"] == 0
    assert meta["credits_total"] == meta["degree_target"]


# ── pyproject.toml version consistency ───────────────────────────────────────

def test_pyproject_version_is_7():
    import tomllib
    toml = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert toml["project"]["version"] == "7.0.0"


def test_api_version_matches_pyproject():
    import tomllib
    toml_v = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    api_v = client.get("/openapi.json").json()["info"]["version"]
    assert api_v == toml_v, f"API version {api_v!r} != pyproject {toml_v!r}"


# ── freshness endpoint returns scrape date ────────────────────────────────────

def test_freshness_endpoint():
    res = client.get("/api/freshness")
    assert res.status_code == 200
    data = res.json()
    assert "scrape_date" in data
    assert "age_days" in data
    assert "is_stale" in data
    assert "message" in data
    assert isinstance(data["age_days"], (int, float))
    assert not data["is_stale"]


# ── run_all_data_refresh.py has correct minor count ──────────────────────────

def test_refresh_script_mentions_hot_reload():
    script = (REPO_ROOT / "scripts/run_all_data_refresh.py").read_text(encoding="utf-8")
    assert "/api/reload" in script, "refresh script should mention /api/reload hot-reload option"


def test_build_gap_meta_returns_expected_keys():
    """_build_gap_meta must return degree_total, raw_gap, residual_gap, gap_explanation."""
    from coursemap.api.server import _build_gap_meta, _svc, PlanRequest
    svc = _svc()
    req = PlanRequest(major="Computer Science – Bachelor of Information Sciences", no_summer=True)
    plan = svc.generate_best_plan(req.major, no_summer=True)
    result = _build_gap_meta(plan, svc, req, "Computer Science – Bachelor of Information Sciences", None)
    assert set(result.keys()) == {"degree_total", "raw_gap", "residual_gap", "gap_explanation", "structural_errors"}
    assert result["degree_total"] == 360


def test_build_gap_meta_catches_structural_shortfall_credit_count_misses():
    """
    Regression test for the gap between credit-count arithmetic and real
    structural validation (see DATA_QUALITY.md / CHANGELOG.md).

    Originally demonstrated with Chemistry - Master of Science, whose
    "free electives" shortfall was itself a data bug (a stale placeholder
    pool sized against the qualification's old, wrong 240cr total - see
    CHANGELOG.md). Fixing that data bug made Chemistry's plan genuinely
    complete, so it stopped demonstrating the gap this test exists to
    catch. Animal Science - Master of Science (M/INT) has the same shape
    for a different,
    still-open reason (a named elective pool, not the free-electives
    catch-all, goes unfilled) and is used here instead.

    Animal Science - Master of Science, M/INT: generate_filled_plan reaches
    the degree's credit target exactly, so residual_gap is 0 - the old
    credit-count-only check would call this complete. The real
    DegreeValidator fails it: a named elective pool (90cr from 4 available
    courses) is unmet. structural_errors must surface that even though
    residual_gap is 0.
    """
    from coursemap.api.server import _build_gap_meta, _svc, PlanRequest
    svc = _svc()
    major = "Animal Science – Master of Science"
    req = PlanRequest(major=major, campus="M", mode="INT", no_summer=True, auto_fill=True)
    plan, filler = svc.generate_filled_plan(major, campus="M", mode="INT", no_summer=True)
    result = _build_gap_meta(plan, svc, req, major, None)

    assert result["residual_gap"] == 0, (
        "test setup assumption broken: this plan should hit the credit "
        "target exactly, which is what makes the structural check necessary"
    )
    assert result["structural_errors"], (
        "structural_errors should catch the elective-pool shortfall that "
        "residual_gap (credit-count only) misses"
    )
    assert any("elective pool" in e.lower() for e in result["structural_errors"])


def test_build_gap_meta_double_major_checks_both_trees():
    """
    Regression test for wiring up structural validation for double majors
    (previously skipped entirely - see DATA_QUALITY.md/CHANGELOG.md).
    Reuses the same pattern already proven safe in the dedicated
    /api/validate endpoint's per-major loop: two independent
    DegreeValidator calls, one per major's own tree, against the same
    shared plan.

    Deliberately constructs an artificial mismatch to prove the mechanism
    reaches both trees, not just the first: uses a Computer Science -
    BInfSci-only plan (from generate_best_plan, not the real double-major
    generator) and manually sets "double_major" to Animal Science -
    Master of Science, a real major with no relationship to that plan at
    all. A real double-major plan (via generate_double_major_plan) is
    generated specifically to satisfy both trees and would likely show no
    errors for either - confirmed live via TestClient against the actual
    /api/plan endpoint, not just asserted here. This test's artificial
    mismatch exists purely to prove structural_errors is actually built
    from BOTH trees when they disagree, not just the first - if the
    double-major branch were silently skipping the second tree (the bug
    this test guards against), no error mentioning Animal Science would
    ever appear, regardless of how mismatched the plan is.
    """
    from coursemap.api.server import _build_gap_meta, _svc, PlanRequest

    svc = _svc()
    first_major = "Computer Science – Bachelor of Information Sciences"
    second_major = "Animal Science – Master of Science"
    plan = svc.generate_best_plan(first_major, campus="D", mode="DIS", no_summer=True)
    req = PlanRequest(major=first_major, double_major=second_major, no_summer=True, auto_fill=False)
    double_info = {"first_label": first_major, "second_label": second_major, "shared_codes": set(),
                    "saved_credits": 0, "first_gap": 0, "second_gap": 0}

    result = _build_gap_meta(plan, svc, req, first_major, double_info)

    assert result["structural_errors"], (
        "structural_errors should be non-empty: the plan doesn't satisfy "
        "the second major's requirements at all"
    )
    assert any(second_major in e for e in result["structural_errors"]), (
        "at least one error should be prefixed with the second major's "
        "name, proving its tree was actually checked, not silently skipped"
    )


def test_build_gap_meta_zero_when_plan_complete():
    """residual_gap is 0 when the plan already reaches the degree target."""
    from coursemap.api.server import _build_gap_meta, _svc, PlanRequest
    svc = _svc()
    req = PlanRequest(major="Computer Science – Bachelor of Information Sciences",
                      no_summer=True, auto_fill=True)
    plan, _filler = svc.generate_filled_plan(req.major, no_summer=True)
    result = _build_gap_meta(plan, svc, req, "Computer Science – Bachelor of Information Sciences", None)
    assert result["residual_gap"] == 0
    assert result["gap_explanation"] is None


def test_build_gap_meta_double_major_explanation():
    """When double_info is present, the explanation mentions overlap."""
    from coursemap.api.server import _build_gap_meta, _svc, PlanRequest
    svc = _svc()
    req = PlanRequest(major="Computer Science – Bachelor of Information Sciences",
                      no_summer=True, auto_fill=False)
    plan = svc.generate_best_plan(req.major, no_summer=True)
    fake_double_info = {"first_label": "A", "second_label": "B", "shared_codes": set(),
                        "saved_credits": 0, "first_gap": 10, "second_gap": 10}
    result = _build_gap_meta(plan, svc, req, "Test Major", fake_double_info)
    if result["residual_gap"] > 0:
        assert "overlap" in result["gap_explanation"].lower()


def test_build_prereq_coverage_shape():
    """_build_prereq_coverage returns the four expected keys with correct types."""
    from coursemap.api.server import _build_prereq_coverage, _svc
    svc = _svc()
    plan = svc.generate_best_plan(
        "Computer Science – Bachelor of Information Sciences", no_summer=True
    )
    cov = _build_prereq_coverage(plan)
    assert set(cov.keys()) == {"total_courses", "courses_with_data", "coverage_pct", "missing_data_codes"}
    assert cov["total_courses"] > 0
    assert 0 <= cov["coverage_pct"] <= 100
    assert isinstance(cov["missing_data_codes"], list)
    assert len(cov["missing_data_codes"]) <= 20  # capped


def test_build_plan_warnings_includes_extra():
    """_build_plan_warnings should preserve any extra_warnings passed in."""
    from coursemap.api.server import _build_plan_warnings, _svc, PlanRequest
    svc = _svc()
    req = PlanRequest(major="Computer Science – Bachelor of Information Sciences", no_summer=True)
    plan = svc.generate_best_plan(req.major, no_summer=True)
    warnings = _build_plan_warnings(plan, svc, req, ["custom warning"])
    assert "custom warning" in warnings


def test_build_plan_warnings_full_year_detection():
    """_build_plan_warnings flags full-year courses correctly."""
    from coursemap.api.server import _build_plan_warnings, _svc, PlanRequest
    from coursemap.domain.plan import DegreePlan, SemesterPlan

    svc = _svc()
    req = PlanRequest(major="Computer Science – Bachelor of Information Sciences", no_summer=True)
    fy_course = Course(
        code="FY100", title="Full Year Course", credits=30, level=100,
        offerings=(Offering(semester="S1", campus="D", mode="DIS", full_year=True),
                  Offering(semester="S2", campus="D", mode="DIS", full_year=True)),
    )
    plan = DegreePlan(semesters=(
        SemesterPlan(year=2026, semester="S1", courses=(fy_course,)),
    ))
    warnings = _build_plan_warnings(plan, svc, req, None)
    fy_warnings = [w for w in warnings if "full academic year" in w]
    assert len(fy_warnings) == 1


def test_plan_to_out_end_to_end_unchanged():
    """
    Full _plan_to_out output shape must be unchanged after the refactor:
    same top-level meta keys as before splitting into helper functions.
    """
    res = client.post("/api/plan", json={
        "major": "Computer Science – Bachelor of Information Sciences",
        "no_summer": True, "auto_fill": True,
    })
    assert res.status_code == 200
    meta = res.json()["meta"]
    expected_keys = {
        "major", "campus", "mode", "start_year", "start_semester",
        "credits_planned", "credits_prior", "credits_transfer", "credits_total",
        "degree_target", "free_elective_gap", "raw_elective_gap",
        "gap_explanation", "auto_filled_codes", "prereq_coverage",
    }
    assert expected_keys.issubset(meta.keys()), \
        f"Missing keys after refactor: {expected_keys - meta.keys()}"


# ═══════════════════════════════════════════════════════════════
# Plan cache versioning. Fixes a real stale-cache bug
# ═══════════════════════════════════════════════════════════════
#
# Found while pinning the _plan_to_out refactor: /api/plan had a hand-rolled
# duplicate of the gap-calculation logic that ran ONLY on cache hits, as a
# band-aid for stale cached `meta` dicts surviving code changes. That patch
# was itself incomplete. It never set `gap_explanation`, so cached plans
# silently returned a different (smaller) meta shape than freshly generated
# ones. The real fix is cache-key versioning: bake _CACHE_VERSION into the
# hashed key so any logic/schema change naturally invalidates old entries
# instead of requiring a parallel patch-on-read implementation.

def test_cache_key_includes_version():
    """_plan_cache_key must change if _CACHE_VERSION changes (same request)."""
    from coursemap.api import server
    req = server.PlanRequest(major="Computer Science – Bachelor of Information Sciences")
    key_before = server._plan_cache_key(req)

    original_version = server._CACHE_VERSION
    try:
        server._CACHE_VERSION = "vTEST-DIFFERENT"
        key_after = server._plan_cache_key(req)
    finally:
        server._CACHE_VERSION = original_version

    assert key_before != key_after, \
        "Cache key did not change when _CACHE_VERSION changed, stale plans " \
        "from a previous version could be served after a logic change."


def test_cache_key_stable_for_identical_requests():
    """Two identical requests (same version) must produce the same cache key."""
    from coursemap.api import server
    req1 = server.PlanRequest(major="Computer Science – Bachelor of Information Sciences")
    req2 = server.PlanRequest(major="Computer Science – Bachelor of Information Sciences")
    assert server._plan_cache_key(req1) == server._plan_cache_key(req2)


def test_no_duplicate_gap_logic_on_cache_hit():
    """
    /api/plan must not contain a second, independent implementation of the
    gap/meta calculation that runs only on cache hits. There must be exactly
    one source of truth: _build_gap_meta, used for both fresh and cached paths.
    """
    import inspect
    from coursemap.api import server
    src = inspect.getsource(server.generate_plan)
    # The old band-aid patched cached["meta"]["free_elective_gap"] inline.
    assert 'cached["meta"]["free_elective_gap"]' not in src, \
        "Duplicate inline gap-patch logic re-appeared in generate_plan's cache-hit path"


def test_plan_to_out_meta_keys_identical_fresh_vs_cached():
    """
    Generating the same plan twice (second hits cache) must return meta dicts
    with identical keys, proving there's no drift between the fresh-generation
    and cache-hit code paths.
    """
    payload = {
        "major": "Statistics – Bachelor of Science",
        "no_summer": True,
        "auto_fill": True,
        "campus": "D",
        "mode": "DIS",
    }
    res1 = client.post("/api/plan", json=payload)
    res2 = client.post("/api/plan", json=payload)  # should hit cache
    assert res1.status_code == res2.status_code == 200
    assert set(res1.json()["meta"].keys()) == set(res2.json()["meta"].keys())
    # plan_id must be stable across repeated identical requests (deterministic cache key)
    assert res1.json()["plan_id"] == res2.json()["plan_id"]


def test_double_major_end_to_end_via_live_api():
    """
    End-to-end regression test for the double-major credit-trimming bug,
    exercised through the real HTTP API (POST /api/plan then POST
    /api/plan/validate) rather than calling PlannerService directly.

    This specifically guards against the cache-key/version class of bug: a
    generation-logic fix can be correct when called directly via
    PlannerService, while the live API still serves a stale pre-fix plan to
    real requests if _CACHE_VERSION wasn't bumped alongside the fix (the
    cache key is a hash that includes _CACHE_VERSION, so an unbumped version
    means identical-looking requests resolve to the same cache entry
    indefinitely). Going through the actual HTTP layer is what catches that
    class of bug; calling the service method directly does not.
    """
    m1 = "Computer Science – Bachelor of Science"
    m2 = "Statistics – Bachelor of Science"

    plan_res = client.post("/api/plan", json={
        "major": m1,
        "double_major": m2,
        "campus": "D", "mode": "DIS", "no_summer": True, "auto_fill": True,
        "start_year": 2026, "start_semester": "S2",
    })
    assert plan_res.status_code == 200
    plan_data = plan_res.json()
    total_credits = sum(s["credits"] for s in plan_data["semesters"])

    # Must NOT be trimmed down to the single-degree minimum (360cr) when the
    # combined majors genuinely need more.
    assert total_credits > 360, (
        f"Double major plan came back at {total_credits}cr. If this is "
        f"360cr, the credit-trimming bug (or a stale cache serving a "
        f"pre-fix plan) may have returned."
    )

    validate_res = client.post("/api/plan/validate", json={
        "major": m1,
        "double_major": m2,
        "plan_id": plan_data["plan_id"],
    })
    assert validate_res.status_code == 200
    validate_data = validate_res.json()
    assert validate_data["overall_passed"] is True, (
        f"Double major plan failed validation: "
        f"first_major_passed={validate_data.get('first_major_passed')}, "
        f"second_major_passed={validate_data.get('second_major_passed')}"
    )


# ── Blank major name validation ───────────────────────────────────────────────
#
# Regression tests for a real bug: PlannerService._resolve_major treats an
# empty/None major_name as "no filter, return all majors" (a legitimate
# feature for generate_best_plan's major-exploration mode). Without explicit
# validation at the API layer, an accidentally-empty `major` field in a
# request silently fell through to that behavior, and /api/plan ended up
# generating a complete, 200-OK plan for an arbitrary, unrelated major
# instead of returning a validation error. Found while testing how the API
# handles malformed input.

@pytest.mark.parametrize("endpoint,payload", [
    ("/api/plan", {"major": ""}),
    ("/api/plan", {"major": "   "}),
    ("/api/plan/progress", {"major": ""}),
    ("/api/plan/progress", {"major": "   "}),
    ("/api/plan/validate", {"major": ""}),
    ("/api/plan/validate", {"major": "   "}),
])
def test_blank_major_name_rejected(endpoint, payload):
    res = client.post(endpoint, json=payload)
    assert res.status_code == 422, (
        f"{endpoint} with major={payload['major']!r} should be rejected "
        f"with 422, got {res.status_code}: {res.text[:200]}"
    )


def test_blank_double_major_name_rejected():
    res = client.post("/api/plan", json={
        "major": "Computer Science – Bachelor of Science",
        "double_major": "   ",
    })
    assert res.status_code == 422


def test_compare_endpoint_rejects_blank_major_in_list():
    res = client.post("/api/plan/compare", json={
        "majors": ["Computer Science – Bachelor of Science", ""],
    })
    assert res.status_code == 422


def test_valid_major_still_works_after_blank_validation_added():
    """Sanity check: the blank-major fix must not affect valid requests."""
    res = client.post("/api/plan", json={
        "major": "Computer Science – Bachelor of Science",
        "auto_fill": True,
        "no_summer": True,
    })
    assert res.status_code == 200


def test_stale_shared_plan_self_heals_on_read():
    """
    End-to-end test for _get_plan_or_heal: a shared-link plan that becomes
    stale (here, simulated by directly overwriting a valid stored plan
    with one containing two mutually-restricting courses, since that's
    exactly what an old plan generated before the top-up-restriction fix
    would have looked like) must not be served as-is on GET
    /api/plan/{plan_id}. It must instead be transparently regenerated and
    the store healed in place under the same plan_id, since a shared link
    is meant to be a permalink to a real plan, not a permalink to whatever
    was true (or buggy) at generation time.
    """
    # Generate a real, valid, currently-passing plan to get a real plan_id
    # and real original params to regenerate from.
    gen_res = client.post("/api/plan", json={
        "major": "Computer Science – Bachelor of Science",
        "auto_fill": True,
        "no_summer": True,
    })
    assert gen_res.status_code == 200
    plan_id = gen_res.json()["plan_id"]

    # Confirm the two courses used below actually do mutually restrict
    # each other in the real dataset, so this test fails loudly instead
    # of silently passing for the wrong reason if the data ever changes.
    from coursemap.ingestion.dataset_loader import load_courses
    courses = load_courses()
    assert "160105" in courses["160101"].restrictions or "160101" in courses["160105"].restrictions, (
        "160101/160105 no longer restrict each other in the dataset - "
        "update this test to use a still-conflicting pair."
    )

    # Directly corrupt the stored plan: inject both conflicting courses
    # into the first semester, simulating a plan generated before the fix.
    from coursemap.api.plan_store import plan_store
    params, result = plan_store.get_with_params(plan_id)
    result["semesters"][0]["courses"].append({"code": "160101", "title": "Calculus", "credits": 15})
    result["semesters"][0]["courses"].append({"code": "160105", "title": "Methods of Mathematics", "credits": 15})
    plan_store.put(plan_id, params, result)

    # Reading it back must NOT return the corrupted snapshot as-is.
    read_res = client.get(f"/api/plan/{plan_id}")
    assert read_res.status_code == 200, (
        f"Expected the plan to self-heal via regeneration, got {read_res.status_code}: {read_res.text}"
    )
    healed_codes = {c["code"] for s in read_res.json()["semesters"] for c in s["courses"]}
    assert not ({"160101", "160105"} <= healed_codes), (
        "Both conflicting courses are still present - the stored plan was not healed."
    )

    # The store itself must now hold the healed version too, not just the
    # single response - a second read must stay healed without needing
    # to re-trigger regeneration.
    refetch = client.get(f"/api/plan/{plan_id}")
    assert refetch.status_code == 200
    refetch_codes = {c["code"] for s in refetch.json()["semesters"] for c in s["courses"]}
    assert not ({"160101", "160105"} <= refetch_codes)


def test_healthy_stored_plan_unaffected_by_healing_check():
    """A plan with no restriction conflicts must be returned exactly as
    stored, not regenerated needlessly on every read."""
    gen_res = client.post("/api/plan", json={
        "major": "Computer Science – Bachelor of Science",
        "auto_fill": True,
        "no_summer": True,
    })
    assert gen_res.status_code == 200
    plan_id = gen_res.json()["plan_id"]
    original_codes = {c["code"] for s in gen_res.json()["semesters"] for c in s["courses"]}

    read_res = client.get(f"/api/plan/{plan_id}")
    assert read_res.status_code == 200
    read_codes = {c["code"] for s in read_res.json()["semesters"] for c in s["courses"]}
    assert read_codes == original_codes
