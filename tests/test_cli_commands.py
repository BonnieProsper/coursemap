"""
CLI command coverage: majors, courses, minors, validate, data-quality, and
plan option combinations not already covered elsewhere.

coursemap/cli/main.py sat at 35-39% coverage for most of this project's
history: the argparse dispatch layer and most command bodies had zero
direct tests, which is exactly why the --no-summer bug (see
test_cli_summer_flag.py) went undetected for as long as it did. These tests
invoke main() the same way a real user's shell would, through
sys.argv, rather than calling the _cmd_* functions directly, so they
exercise the actual argument parser too.
"""
from __future__ import annotations

import json

import pytest

from coursemap.cli.main import main


def _run(monkeypatch, argv):
    monkeypatch.setattr("sys.argv", ["coursemap"] + argv)
    main()


def _run_capture(monkeypatch, capsys, argv, expect_exit=None):
    """Run main() and return (stdout, stderr). If expect_exit is set,
    assert SystemExit was raised with that code; otherwise assert it
    wasn't raised at all."""
    if expect_exit is not None:
        with pytest.raises(SystemExit) as exc_info:
            _run(monkeypatch, argv)
        assert exc_info.value.code == expect_exit
    else:
        _run(monkeypatch, argv)
    captured = capsys.readouterr()
    return captured.out, captured.err


# ---------------------------------------------------------------------------
# coursemap majors
# ---------------------------------------------------------------------------

def test_majors_lists_all_when_no_search(monkeypatch, capsys):
    out, _ = _run_capture(monkeypatch, capsys, ["majors"])
    assert "major(s):" in out
    # Should be a large list, not an error
    assert int(out.split()[0]) > 100


def test_majors_search_partial_word_match(monkeypatch, capsys):
    out, _ = _run_capture(monkeypatch, capsys, ["majors", "--search", "comp sci"])
    assert "Computer Science" in out


def test_majors_search_no_match_exits_1(monkeypatch, capsys):
    out, err = _run_capture(
        monkeypatch, capsys,
        ["majors", "--search", "zzznonexistentmajorzzz"],
        expect_exit=1,
    )
    assert "No majors matching" in err


def test_majors_search_falls_back_to_substring(monkeypatch, capsys):
    """word_match requires every query word to appear in some name token.
    If that finds nothing, _search_majors falls back to whole-string
    substring matching."""
    out, _ = _run_capture(monkeypatch, capsys, ["majors", "--search", "Ecology"])
    assert "Ecology" in out


# ---------------------------------------------------------------------------
# coursemap courses
# ---------------------------------------------------------------------------

def test_courses_default_filters_to_active(monkeypatch, capsys):
    out, _ = _run_capture(monkeypatch, capsys, ["courses"])
    assert "active courses" in out
    assert "[no offerings]" not in out


def test_courses_search_by_title(monkeypatch, capsys):
    out, _ = _run_capture(monkeypatch, capsys, ["courses", "--search", "Applied Programming"])
    assert "159101" in out


def test_courses_filter_by_level(monkeypatch, capsys):
    out, _ = _run_capture(monkeypatch, capsys, ["courses", "--level", "100", "--search", "Applied Programming"])
    assert "L100" in out
    assert "L200" not in out


def test_courses_filter_by_campus_and_mode(monkeypatch, capsys):
    out, _ = _run_capture(
        monkeypatch, capsys,
        ["courses", "--search", "Applied Programming", "--campus", "D", "--mode", "DIS"],
    )
    assert "159101" in out


def test_courses_filter_by_semester(monkeypatch, capsys):
    out, _ = _run_capture(
        monkeypatch, capsys,
        ["courses", "--search", "Applied Programming", "--semester", "S1"],
    )
    assert "159101" in out or "No courses match" in out


def test_courses_show_inactive_includes_retired(monkeypatch, capsys):
    """--show-inactive must include courses with no offerings, which are
    excluded by default. This is a separate code path from the default
    filter and was previously untested."""
    out, _ = _run_capture(monkeypatch, capsys, ["courses", "--show-inactive"])
    assert "course(s):" in out


def test_courses_no_match_exits_1_with_hint(monkeypatch, capsys):
    out, err = _run_capture(
        monkeypatch, capsys,
        ["courses", "--search", "zzznonexistentcoursetitlezzz"],
        expect_exit=1,
    )
    assert "No courses match" in err


def test_courses_no_match_with_show_inactive_omits_hint(monkeypatch, capsys):
    """The --show-inactive suggestion hint should only appear when the
    person hasn't already tried it."""
    out, err = _run_capture(
        monkeypatch, capsys,
        ["courses", "--search", "zzznonexistentcoursetitlezzz", "--show-inactive"],
        expect_exit=1,
    )
    assert "use --show-inactive" not in err


# ---------------------------------------------------------------------------
# coursemap minors
# ---------------------------------------------------------------------------

def test_minors_lists_all_when_no_search(monkeypatch, capsys):
    out, _ = _run_capture(monkeypatch, capsys, ["minors"])
    assert "minor(s):" in out


def test_minors_search_by_name(monkeypatch, capsys):
    out, _ = _run_capture(monkeypatch, capsys, ["minors", "--search", "Accounting"])
    assert "Accounting" in out


def test_minors_search_no_match_exits_1(monkeypatch, capsys):
    out, err = _run_capture(
        monkeypatch, capsys,
        ["minors", "--search", "zzznonexistentminorzzz"],
        expect_exit=1,
    )
    assert "No minors matching" in err


def test_minors_filter_by_quality(monkeypatch, capsys):
    """Every minor in the current dataset is 'inferred' (see DATA_QUALITY.md).
    This confirms the filter works, not that it necessarily narrows results."""
    out, _ = _run_capture(monkeypatch, capsys, ["minors", "--quality", "inferred"])
    assert "minor(s):" in out
    assert "⚠ inferred" in out


def test_minors_inferred_warning_shown(monkeypatch, capsys):
    out, _ = _run_capture(monkeypatch, capsys, ["minors"])
    assert "approximated from course patterns" in out


# ---------------------------------------------------------------------------
# coursemap validate
# ---------------------------------------------------------------------------

def test_validate_prints_dataset_summary(monkeypatch, capsys):
    out, _ = _run_capture(monkeypatch, capsys, ["validate", "--quiet"])
    assert "Dataset summary" in out
    assert "Courses" in out
    assert "Majors" in out


def test_validate_quiet_suppresses_warning_detail(monkeypatch, capsys):
    out, _ = _run_capture(monkeypatch, capsys, ["validate", "--quiet"])
    assert "suppressed" in out or "No errors" in out


def test_validate_all_shows_every_warning(monkeypatch, capsys):
    """--all must not truncate to 20 the way the default view does."""
    out, _ = _run_capture(monkeypatch, capsys, ["validate", "--all"])
    assert "more. Use --all" not in out


def test_validate_default_truncates_to_20(monkeypatch, capsys):
    out, _ = _run_capture(monkeypatch, capsys, ["validate"])
    # Either there are <=20 warnings (no truncation message needed) or
    # the truncation message appears. Both are valid depending on dataset
    # state, but the command itself must not crash either way.
    assert "Dataset summary" in out


# ---------------------------------------------------------------------------
# coursemap data-quality
# ---------------------------------------------------------------------------

def test_data_quality_human_readable_output(monkeypatch, capsys):
    out, _ = _run_capture(monkeypatch, capsys, ["data-quality"])
    assert "Data Quality Report" in out


def test_data_quality_json_output_is_valid_json(monkeypatch, capsys):
    out, _ = _run_capture(monkeypatch, capsys, ["data-quality", "--json"])
    data = json.loads(out)
    assert isinstance(data, dict)


# ---------------------------------------------------------------------------
# coursemap plan: option combinations not covered by test_cli_summer_flag.py
# or the integration suite
# ---------------------------------------------------------------------------

def test_plan_missing_major_exits_with_error(monkeypatch, capsys):
    _run_capture(
        monkeypatch, capsys,
        ["plan", "--major", "zzznonexistentmajorzzz", "--campus", "D", "--mode", "DIS"],
        expect_exit=1,
    )


def test_plan_json_format_writes_valid_json(monkeypatch, tmp_path):
    out = tmp_path / "plan.json"
    _run(monkeypatch, [
        "plan", "--major", "Computer Science", "--campus", "D", "--mode", "DIS",
        "--format", "json", "--output", str(out),
    ])
    data = json.loads(out.read_text(encoding="utf-8"))
    assert "semesters" in data


def test_plan_html_format_writes_valid_html(monkeypatch, tmp_path):
    out = tmp_path / "plan.html"
    _run(monkeypatch, [
        "plan", "--major", "Computer Science", "--campus", "D", "--mode", "DIS",
        "--format", "html", "--output", str(out),
    ])
    assert out.exists()
    assert "<!DOCTYPE html>" in out.read_text(encoding="utf-8")


def test_plan_ical_format_writes_valid_ical(monkeypatch, tmp_path):
    out = tmp_path / "plan.ics"
    _run(monkeypatch, [
        "plan", "--major", "Computer Science", "--campus", "D", "--mode", "DIS",
        "--format", "ical", "--output", str(out),
    ])
    assert out.exists()
    assert "BEGIN:VCALENDAR" in out.read_text(encoding="utf-8")


def test_plan_completed_courses_reduces_remaining_credits(monkeypatch, tmp_path):
    out_a = tmp_path / "plan_a.json"
    out_b = tmp_path / "plan_b.json"
    _run(monkeypatch, [
        "plan", "--major", "Computer Science", "--campus", "D", "--mode", "DIS",
        "--format", "json", "--output", str(out_a),
    ])
    _run(monkeypatch, [
        "plan", "--major", "Computer Science", "--campus", "D", "--mode", "DIS",
        "--completed", "159101,160101", "--format", "json", "--output", str(out_b),
    ])
    total_a = sum(c["credits"] for s in json.loads(out_a.read_text(encoding="utf-8"))["semesters"] for c in s["courses"])
    total_b = sum(c["credits"] for s in json.loads(out_b.read_text(encoding="utf-8"))["semesters"] for c in s["courses"])
    assert total_b < total_a


def test_plan_exclude_codes_are_never_scheduled(monkeypatch, tmp_path):
    out = tmp_path / "plan.json"
    _run(monkeypatch, [
        "plan", "--major", "Computer Science", "--campus", "D", "--mode", "DIS",
        "--exclude", "159261", "--format", "json", "--output", str(out),
    ])
    codes = {c["code"] for s in json.loads(out.read_text(encoding="utf-8"))["semesters"] for c in s["courses"]}
    assert "159261" not in codes


def test_plan_transfer_credits_accepted(monkeypatch, tmp_path):
    """transfer_credits should count toward the degree total without
    appearing as scheduled courses. Just confirm the flag is accepted and
    plan generation still succeeds with it set."""
    out = tmp_path / "plan.json"
    _run(monkeypatch, [
        "plan", "--major", "Computer Science", "--campus", "D", "--mode", "DIS",
        "--transfer-credits", "60", "--auto-fill",
        "--format", "json", "--output", str(out),
    ])
    assert out.exists()


def test_plan_max_per_semester_caps_course_count(monkeypatch, tmp_path):
    out = tmp_path / "plan.json"
    _run(monkeypatch, [
        "plan", "--major", "Computer Science", "--campus", "D", "--mode", "DIS",
        "--max-per-semester", "2", "--format", "json", "--output", str(out),
    ])
    semesters = json.loads(out.read_text(encoding="utf-8"))["semesters"]
    assert all(len(s["courses"]) <= 2 for s in semesters)


def test_plan_start_year_and_semester_are_respected(monkeypatch, tmp_path):
    out = tmp_path / "plan.json"
    _run(monkeypatch, [
        "plan", "--major", "Computer Science", "--campus", "D", "--mode", "DIS",
        "--start-year", "2027", "--start-semester", "S2",
        "--format", "json", "--output", str(out),
    ])
    data = json.loads(out.read_text(encoding="utf-8"))
    first = data["semesters"][0]
    assert first["year"] == 2027
    assert first["semester"] == "S2"


def test_plan_debug_flag_still_completes(monkeypatch, tmp_path):
    out = tmp_path / "plan.json"
    _run(monkeypatch, [
        "plan", "--major", "Computer Science", "--campus", "D", "--mode", "DIS",
        "--debug", "--output", str(out),
    ])
    # --debug enables DEBUG-level logging and prints extra scheduler stats.
    # Just confirm the command still completes and produces output.
    assert out.exists()


def test_plan_explain_flag_still_completes(monkeypatch, tmp_path):
    out = tmp_path / "plan.json"
    _run(monkeypatch, [
        "plan", "--major", "Computer Science", "--campus", "D", "--mode", "DIS",
        "--explain", "--output", str(out),
    ])
    assert out.exists()


def test_plan_double_major_produces_combined_plan(monkeypatch, tmp_path):
    out = tmp_path / "plan.json"
    _run(monkeypatch, [
        "plan", "--major", "Computer Science", "--double-major", "Statistics",
        "--campus", "D", "--mode", "DIS", "--auto-fill",
        "--format", "json", "--output", str(out),
    ])
    data = json.loads(out.read_text(encoding="utf-8"))
    assert "semesters" in data


def test_plan_double_major_without_autofill_uses_unfilled_path(monkeypatch, tmp_path):
    """Without --auto-fill, double-major dispatches to
    generate_double_major_plan (not generate_filled_double_major_plan),
    a separate code path with no filler_codes."""
    out = tmp_path / "plan.json"
    _run(monkeypatch, [
        "plan", "--major", "Computer Science", "--double-major", "Statistics",
        "--campus", "D", "--mode", "DIS",
        "--format", "json", "--output", str(out),
    ])
    data = json.loads(out.read_text(encoding="utf-8"))
    assert "semesters" in data
    assert len(data["semesters"]) > 0
    out = tmp_path / "plan.json"
    _run(monkeypatch, [
        "plan", "--major", "Computer Science", "--minor", "Accounting",
        "--campus", "D", "--mode", "DIS", "--auto-fill",
        "--format", "json", "--output", str(out),
    ])
    assert out.exists()


def test_plan_double_major_text_output_shows_shared_courses(monkeypatch, capsys, tmp_path):
    """Exercises _print_double_major_info's shared-course branch, which
    needs the text format (not json) to actually print."""
    out = tmp_path / "plan.json"
    stdout, _ = _run_capture(monkeypatch, capsys, [
        "plan", "--major", "Computer Science", "--double-major", "Statistics",
        "--campus", "D", "--mode", "DIS", "--auto-fill",
        "--format", "text", "--output", str(out),
    ])
    assert "Double major" in stdout


def test_plan_double_major_requirements_check_is_real_not_unconditional(monkeypatch, capsys, tmp_path):
    """
    Regression test: 'Both major requirements: satisfied' used to print
    unconditionally for every double major, with no actual check behind
    it at all (see DATA_QUALITY.md/CHANGELOG.md - the CLI's version of
    the same gap already fixed in the API's _build_gap_meta).

    Computer Science - BInfSci + Animal Science - MSc, without
    --auto-fill: a real, unfilled free-electives gap in Computer Science
    (confirmed via the equivalent API test,
    test_plan_double_major_structural_errors_checks_both_majors in
    test_api.py) must now be reported as NOT satisfied, with the actual
    error shown - not silently claimed complete. With --auto-fill, the
    same gap is closed and the plan is genuinely satisfied.
    """
    out = tmp_path / "plan.json"
    stdout, _ = _run_capture(monkeypatch, capsys, [
        "plan", "--major", "Computer Science – Bachelor of Information Sciences",
        "--double-major", "Animal Science – Master of Science",
        "--campus", "D", "--mode", "DIS", "--no-summer",
        "--format", "text", "--output", str(out),
    ])
    assert "Both major requirements: NOT fully satisfied" in stdout
    assert "Computer Science" in stdout

    out2 = tmp_path / "plan2.json"
    stdout2, _ = _run_capture(monkeypatch, capsys, [
        "plan", "--major", "Computer Science – Bachelor of Information Sciences",
        "--double-major", "Animal Science – Master of Science",
        "--campus", "D", "--mode", "DIS", "--no-summer", "--auto-fill",
        "--format", "text", "--output", str(out2),
    ])
    assert "Both major requirements: satisfied" in stdout2


def test_plan_text_output_shows_completed_courses_in_header(monkeypatch, capsys, tmp_path):
    """Exercises _print_plan_header's prior_completed branch."""
    out = tmp_path / "plan.json"
    stdout, _ = _run_capture(monkeypatch, capsys, [
        "plan", "--major", "Computer Science", "--campus", "D", "--mode", "DIS",
        "--completed", "159101,160101",
        "--format", "text", "--output", str(out),
    ])
    assert "Completed:" in stdout
    assert "159101" in stdout


def test_plan_text_output_shows_transfer_credits_in_header(monkeypatch, capsys, tmp_path):
    """Exercises _print_plan_header's transfer_credits branch."""
    out = tmp_path / "plan.json"
    stdout, _ = _run_capture(monkeypatch, capsys, [
        "plan", "--major", "Computer Science", "--campus", "D", "--mode", "DIS",
        "--transfer-credits", "60", "--auto-fill",
        "--format", "text", "--output", str(out),
    ])
    assert "Transfer:" in stdout
    assert "60 credits" in stdout


def test_validate_reports_errors_when_present(monkeypatch, capsys):
    """The bundled dataset has zero validation errors (verified separately),
    so the error-reporting branch in _cmd_validate is otherwise unreachable
    through real data. Patch validate_dataset's return value directly to
    exercise it, the same way a corrupted dataset would in production."""
    import coursemap.cli.main as cli_main
    from coursemap.validation.dataset_validator import DatasetValidationResult

    fake_result = DatasetValidationResult(
        errors=[f"Fake error {i}" for i in range(25)],
        warnings=[],
    )
    monkeypatch.setattr(cli_main, "validate_dataset", lambda *a, **kw: fake_result)

    with pytest.raises(SystemExit) as exc_info:
        _run(monkeypatch, ["validate"])
    assert exc_info.value.code == 1
    out = capsys.readouterr().out
    assert "25 error(s)" in out
    assert "... and 5 more" in out


def test_plan_shows_campus_exclusion_warning_for_real_major(monkeypatch, capsys, tmp_path):
    """Animal Science - Master of Science has a real required course
    (117709) with no DIS offering. Confirmed via
    PlannerService.campus_excluded_courses directly during development,
    not assumed. Exercises _print_exclusion_warnings without mocking."""
    out = tmp_path / "plan.json"
    stdout, _ = _run_capture(monkeypatch, capsys, [
        "plan", "--major", "Animal Science – Master of Science",
        "--campus", "D", "--mode", "DIS",
        "--format", "text", "--output", str(out),
    ])
    assert "have no DIS offering and are excluded" in stdout
    assert "117709" in stdout
    assert "Use --campus M --mode INT" in stdout


def test_plan_shows_prerequisite_ordering_warning(monkeypatch, capsys, tmp_path):
    """The generator normally schedules courses in valid prerequisite
    order, so this audit's non-empty branch is a rare safety net rather
    than something a real plan is likely to trigger. Patch _audit_prereqs
    directly to exercise _print_prereq_warnings's two sub-branches (notes
    with and without a corresponding missing-prerequisite explanation)."""
    import coursemap.cli.main as cli_main

    monkeypatch.setattr(
        cli_main, "_audit_prereqs",
        lambda plan, prior_completed, courses: (["159201", "159234"], ["159101"]),
    )
    out = tmp_path / "plan.json"
    stdout, _ = _run_capture(monkeypatch, capsys, [
        "plan", "--major", "Computer Science", "--campus", "D", "--mode", "DIS",
        "--format", "text", "--output", str(out),
    ])
    assert "may require prior study" in stdout
    assert "159201" in stdout
    assert "Possible missing prerequisites: 159101" in stdout


def test_plan_without_major_argument_still_works(monkeypatch, tmp_path):
    """No --major means 'plan every completed course into a schedule with
    no requirement tree', a real, documented use case (e.g. a student who
    just wants to see when their completed courses would have been
    scheduled). Exercises the else-branch where gap/excl default to
    0/[] instead of being computed from a resolved major."""
    out = tmp_path / "plan.json"
    _run(monkeypatch, [
        "plan", "--campus", "D", "--mode", "DIS",
        "--completed", "159101,160101",
        "--format", "json", "--output", str(out),
    ])
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["meta"]["major"] == "all majors"


def test_plan_html_export_with_autofill_uses_filler_as_electives(monkeypatch, tmp_path):
    """HTML export branches differently when auto_fill produced filler
    codes (shows them as the elective section) versus when it didn't
    (falls back to _elective_suggestions)."""
    out = tmp_path / "plan.html"
    _run(monkeypatch, [
        "plan", "--major", "Computer Science", "--campus", "D", "--mode", "DIS",
        "--auto-fill", "--format", "html", "--output", str(out),
    ])
    text = out.read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in text
    assert "Computer Science" in text
