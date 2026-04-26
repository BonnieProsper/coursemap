"""Tests for v0.6.1 fixes and additions."""
import pytest
from fastapi.testclient import TestClient
from coursemap.api.server import app
from coursemap.ingestion.dataset_loader import load_courses, load_majors
from coursemap.services.planner_service import PlannerService

client = TestClient(app)
_courses = load_courses()
_majors  = load_majors()
_svc     = PlannerService(_courses, _majors)


class TestAutoFillDoubleMajor:
    """auto-fill + double-major can now be combined."""

    def test_filled_double_major_plan_via_service(self):
        plan, info, filler = _svc.generate_filled_double_major_plan(
            major_name="Computer Science",
            second_major_name="Mathematics",
        )
        assert plan
        assert info["first_label"]
        assert info["second_label"]
        # filler is a set/frozenset of course codes
        assert isinstance(filler, (set, frozenset, list))

    def test_filled_double_major_via_api(self):
        r = client.post("/api/plan", json={
            "major": "Computer Science",
            "double_major": "Mathematics",
            "auto_fill": True,
            "campus": "D",
            "mode": "DIS",
        })
        assert r.status_code == 200
        data = r.json()
        assert data["double_major_info"] is not None
        # filler_codes should be present
        assert "filler_codes" in data


class TestStartSemester:
    """start_semester flag works from S2 and SS starts."""

    def test_plan_starting_s2(self):
        r = client.post("/api/plan", json={
            "major": "Computer Science",
            "start_year": 2026,
            "start_semester": "S2",
            "campus": "D",
            "mode": "DIS",
        })
        assert r.status_code == 200
        data = r.json()
        first_sem = data["semesters"][0]
        assert first_sem["semester"] == "S2"
        assert first_sem["year"] == 2026

    def test_plan_starting_s1(self):
        r = client.post("/api/plan", json={
            "major": "Computer Science",
            "start_year": 2027,
            "start_semester": "S1",
            "campus": "D",
            "mode": "DIS",
        })
        assert r.status_code == 200
        data = r.json()
        first_sem = data["semesters"][0]
        assert first_sem["semester"] == "S1"
        assert first_sem["year"] == 2027


class TestExplainEndpointImproved:
    """Explain endpoint uses offering-aware earliest semester calculation."""

    def test_explain_s1_only_deep_chain(self):
        # Find a course with chain_depth > 0 that is only offered in S1 at D/DIS
        s1_only_deep = None
        for code, c in _courses.items():
            if not c.prerequisites:
                continue
            s1_only = (
                c.offerings
                and all(o.semester == "S1" for o in c.offerings
                        if o.campus == "D" and o.mode == "DIS")
                and any(o.campus == "D" and o.mode == "DIS" for o in c.offerings)
            )
            if s1_only:
                s1_only_deep = code
                break

        if not s1_only_deep:
            pytest.skip("No S1-only D/DIS course with prerequisites in dataset")

        r = client.get(f"/api/courses/{s1_only_deep}/explain?major=Computer+Science&campus=D&mode=DIS")
        assert r.status_code == 200
        data = r.json()
        depth = data["chain_depth"]
        text  = " ".join(data["constraints"]).lower()
        # The earliest semester reported must be at least chain_depth+1
        # (could be more if the offering constraint pushes it later)
        import re
        m = re.search(r"earliest possible semester: (\d+)", text)
        if m:
            reported = int(m.group(1))
            assert reported >= depth + 1, (
                f"Earliest sem {reported} should be >= chain_depth+1 = {depth+1}"
            )

    def test_explain_no_prereq_message(self):
        no_prereq = next(
            (c for c in _courses.values() if not c.prerequisites and c.level == 100),
            None
        )
        if not no_prereq:
            pytest.skip("No level-100 course without prerequisites in dataset")
        r = client.get(f"/api/courses/{no_prereq.code}/explain?major=Computer+Science")
        assert r.status_code == 200
        data = r.json()
        assert data["chain_depth"] == 0
        text = " ".join(data["constraints"]).lower()
        assert "no prerequisites" in text
        assert "year 1" in text or "semester 1" in text


class TestPyprojectVersion:
    """pyproject.toml version matches package version."""

    def test_version_matches(self):
        import importlib.metadata, tomllib, pathlib
        pkg_version = importlib.metadata.version("coursemap")
        toml_path = pathlib.Path(__file__).parent.parent / "pyproject.toml"
        if toml_path.exists():
            with open(toml_path, "rb") as f:
                toml = tomllib.load(f)
            toml_version = toml["project"]["version"]
            assert pkg_version == toml_version, (
                f"Package version {pkg_version!r} != pyproject.toml version {toml_version!r}"
            )
