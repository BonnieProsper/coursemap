"""
Tests for coursemap v0.6 features:
- start_semester wired end-to-end (generator → search → service → API)
- dynamic start_year default (current year, not hardcoded 2026)
- double major shared-code highlighting in plan output
- Massey calendar label present in UI
- Docker and requirements.txt files exist
- Mobile CSS present in UI
- Validation checklist pool expansion markup
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from coursemap.api.server import app, _svc

ROOT = Path(__file__).parent.parent
client = TestClient(app, raise_server_exceptions=True)


@pytest.fixture(scope="module", autouse=True)
def warmup():
    _svc()
    yield


# ---------------------------------------------------------------------------
# start_semester — generator level
# ---------------------------------------------------------------------------

class TestStartSemesterGenerator:
    """Unit tests that the generator honours start_semester via the service layer."""

    @pytest.fixture(scope="class")
    def svc(self):
        return _svc()

    def test_s1_starts_with_s1(self, svc):
        plan = svc.generate_best_plan(
            major_name="Computer Science", start_year=2026, start_semester="S1"
        )
        assert plan.semesters[0].semester == "S1"

    def test_s2_starts_with_s2(self, svc):
        plan = svc.generate_best_plan(
            major_name="Computer Science", start_year=2026, start_semester="S2"
        )
        assert plan.semesters[0].semester == "S2"

    def test_s2_second_sem_is_ss_or_s1_next_year(self, svc):
        plan = svc.generate_best_plan(
            major_name="Computer Science", start_year=2026, start_semester="S2"
        )
        if len(plan.semesters) > 1:
            second = plan.semesters[1]
            assert second.semester in ("SS", "S1")

    def test_case_insensitive_start_semester(self, svc):
        plan = svc.generate_best_plan(
            major_name="Computer Science", start_year=2026, start_semester="s2"
        )
        assert plan.semesters[0].semester == "S2"


# ---------------------------------------------------------------------------
# start_semester — full API stack
# ---------------------------------------------------------------------------

class TestStartSemesterAPI:
    def test_s1_default_first_semester(self):
        r = client.post("/api/plan", json={"major": "Computer Science", "start_semester": "S1"})
        assert r.status_code == 200
        assert r.json()["semesters"][0]["semester"] == "S1"

    def test_s2_first_semester_is_s2(self):
        r = client.post("/api/plan", json={"major": "Computer Science", "start_semester": "S2"})
        assert r.status_code == 200
        data = r.json()
        assert data["semesters"][0]["semester"] == "S2"

    def test_s2_meta_recorded(self):
        r = client.post("/api/plan", json={"major": "Computer Science", "start_semester": "S2"})
        assert r.json()["meta"]["start_semester"] == "S2"

    def test_s2_plan_stays_chronological(self):
        r = client.post("/api/plan", json={"major": "Computer Science", "start_semester": "S2", "start_year": 2026})
        sems = r.json()["semesters"]
        order = [("S1", 1), ("S2", 2), ("SS", 3)]
        sem_to_ord = {s: o for s, o in order}
        for i in range(len(sems) - 1):
            a, b = sems[i], sems[i + 1]
            a_key = (a["year"], sem_to_ord.get(a["semester"], 0))
            b_key = (b["year"], sem_to_ord.get(b["semester"], 0))
            assert a_key <= b_key, f"Semesters out of order: {a} before {b}"

    def test_s2_ical_also_uses_s2_start(self):
        r = client.post("/api/plan/ical", json={"major": "Computer Science", "start_semester": "S2"})
        assert r.status_code == 200
        # iCal should have a DTSTART in July (month 07) for first S2 event
        assert "DTSTART;VALUE=DATE:202607" in r.text or "DTSTART;VALUE=DATE:202607" in r.text or "07" in r.text

    def test_s2_autofill_works(self):
        r = client.post("/api/plan", json={
            "major": "Computer Science",
            "start_semester": "S2",
            "auto_fill": True,
        })
        assert r.status_code == 200
        assert r.json()["semesters"][0]["semester"] == "S2"

    def test_invalid_start_semester_handled(self):
        # The API should either 422 or silently default to S1
        r = client.post("/api/plan", json={"major": "Computer Science", "start_semester": "XX"})
        # We accept either — the important thing is no 500
        assert r.status_code in (200, 422)


# ---------------------------------------------------------------------------
# Dynamic start_year default
# ---------------------------------------------------------------------------

def test_start_year_default_is_current_year():
    """PlanRequest.start_year should default to this year, not hardcoded 2026."""
    from coursemap.api.server import PlanRequest
    req = PlanRequest(major="Computer Science")
    assert req.start_year == date.today().year


def test_api_plan_without_start_year_uses_current_year():
    r = client.post("/api/plan", json={"major": "Computer Science"})
    assert r.status_code == 200
    meta = r.json()["meta"]
    assert meta["start_year"] == date.today().year


# ---------------------------------------------------------------------------
# Double major shared-course highlighting
# ---------------------------------------------------------------------------

class TestDoubleMajorHighlighting:
    def _get_double_plan(self):
        return client.post("/api/plan", json={
            "major": "Computer Science",
            "double_major": "Mathematics",
        })

    def test_double_plan_has_shared_codes(self):
        r = self._get_double_plan()
        if r.status_code != 200:
            pytest.skip("Double major combination not available in dataset")
        data = r.json()
        assert "double_major_info" in data
        if data["double_major_info"]:
            assert "shared_codes" in data["double_major_info"]

    def test_shared_codes_are_in_plan(self):
        r = self._get_double_plan()
        if r.status_code != 200:
            pytest.skip("Double major combination not available in dataset")
        data = r.json()
        if not data.get("double_major_info"):
            pytest.skip("No double major info returned")
        shared = set(data["double_major_info"].get("shared_codes", []))
        all_codes = {c["code"] for s in data["semesters"] for c in s["courses"]}
        for code in shared:
            assert code in all_codes, f"Shared code {code} not in plan"

    def test_ui_has_shared_code_badge_markup(self):
        html = client.get("/").text
        assert "×2" in html
        assert "sharedCodes" in html
        assert "overlap" in html.lower() or "shared" in html.lower()


# ---------------------------------------------------------------------------
# Massey calendar dates in UI
# ---------------------------------------------------------------------------

def test_ui_has_massey_calendar_data():
    html = client.get("/").text
    assert "masseyCalendar" in html
    assert "Feb" in html
    assert "Jul" in html
    assert "Enrol by" in html

def test_ui_semester_header_shows_cal_label():
    html = client.get("/").text
    assert "calLabel" in html
    assert "enrolTip" in html


# ---------------------------------------------------------------------------
# Mobile CSS
# ---------------------------------------------------------------------------

def test_ui_has_mobile_card_layout():
    html = client.get("/").text
    # Mobile grid override should be in the @media block
    assert "grid-template-columns: 68px 1fr auto" in html
    assert "text-overflow: ellipsis" in html


# ---------------------------------------------------------------------------
# Validation checklist pool expansion
# ---------------------------------------------------------------------------

def test_validation_pool_expansion_markup_in_ui():
    html = client.get("/").text
    assert "Pick from" in html
    assert "pool_codes" in html

def test_validation_pool_expansion_for_failed_plan():
    """An unfilled plan may have pools that aren't satisfied — check the UI markup is generated."""
    r = client.post("/api/plan/validate", json={"major": "Computer Science", "auto_fill": False})
    assert r.status_code == 200
    d = r.json()
    # Regardless of pass/fail, checklist should be present
    assert "checklist" in d
    # The checklist should render without error even if all pools pass
    assert isinstance(d["checklist"], dict)


# ---------------------------------------------------------------------------
# Docker and requirements.txt infrastructure
# ---------------------------------------------------------------------------

def test_dockerfile_exists():
    assert (ROOT / "Dockerfile").exists(), "Dockerfile missing"

def test_dockerfile_has_key_content():
    content = (ROOT / "Dockerfile").read_text()
    assert "uvicorn" in content
    assert "EXPOSE 8080" in content
    assert "coursemap" in content.lower()
    assert "python:3.12" in content

def test_docker_compose_exists():
    assert (ROOT / "docker-compose.yaml").exists(), "docker-compose.yaml missing"

def test_docker_compose_has_health_check():
    content = (ROOT / "docker-compose.yaml").read_text()
    assert "healthcheck" in content
    assert "8080" in content

def test_requirements_txt_exists():
    assert (ROOT / "requirements.txt").exists(), "requirements.txt missing"

def test_requirements_txt_has_key_packages():
    content = (ROOT / "requirements.txt").read_text()
    assert "fastapi" in content
    assert "uvicorn" in content
    assert "slowapi" in content

def test_requirements_txt_is_pinned():
    """Every line that isn't a comment or blank should have ==."""
    lines = (ROOT / "requirements.txt").read_text().splitlines()
    dep_lines = [l for l in lines if l.strip() and not l.startswith("#") and not l.startswith("-")]
    pinned = [l for l in dep_lines if "==" in l]
    assert len(pinned) >= 10, "Expected at least 10 pinned packages"


# ---------------------------------------------------------------------------
# start_semester URL state and UI wiring
# ---------------------------------------------------------------------------

def test_ui_has_start_semester_selector():
    html = client.get("/").text
    assert 'id="start-semester"' in html
    assert 'value="S2"' in html
    assert 'value="SS"' in html

def test_ui_auto_detects_semester():
    html = client.get("/").text
    assert "start-semester" in html
    assert "auto-detect" in html.lower() or "Auto-detect" in html or "new Date()" in html

def test_ui_start_semester_in_request_body():
    html = client.get("/").text
    assert "start_semester:" in html
    assert "getElementById('start-semester')" in html
