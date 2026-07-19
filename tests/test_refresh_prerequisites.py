"""
Tests for refresh_prerequisites.py's safety-abort logic.

All tests monkeypatch `_fetch_relations` directly, so nothing here touches
the network - these test the orchestration/safety logic in
refresh_prerequisites(), not the actual scraping.
"""
import json

from coursemap.ingestion import refresh_prerequisites as rp


def _make_courses_file(tmp_path, count):
    """Write a synthetic courses.json with `count` scrapable entries."""
    courses = [
        {
            "course_code": f"{100000 + i}",
            "url": f"https://example.invalid/course/{100000 + i}/",
            "prerequisites": None,
            "restrictions": [],
            "corequisites": [],
        }
        for i in range(count)
    ]
    path = tmp_path / "courses.json"
    path.write_text(json.dumps(courses), encoding="utf-8")
    return path


def test_aborts_when_prerequisites_collapse_to_zero_but_others_dont(tmp_path, monkeypatch):
    """
    The scenario the combined 'updated' check misses: prerequisite
    extraction breaks (e.g. a CSS class Massey uses changes) while
    restriction/corequisite extraction, which doesn't depend on the same
    HTML structure, keeps working. The combined check sees plenty of
    non-empty results and doesn't fire; only the prerequisites-specific
    check catches this and must refuse to write.
    """
    path = _make_courses_file(tmp_path, 150)
    original_content = path.read_text(encoding="utf-8")

    def fake_fetch(code, url, timeout, existing):
        # Every course "succeeds" for restrictions/corequisites, but
        # prerequisites always comes back None - the exact partial-
        # collapse pattern that used to slip past the safety check.
        return code, {
            "prerequisites": None,
            "restrictions": ["999999"],
            "corequisites": [],
        }, True, False

    monkeypatch.setattr(rp, "_fetch_relations", fake_fetch)

    rp.refresh_prerequisites(courses_path=path, concurrency=4)

    assert path.read_text(encoding="utf-8") == original_content, (
        "courses.json was modified despite prerequisites collapsing to 0 "
        "across every course - the abort check failed to catch it."
    )


def test_does_not_abort_on_healthy_run(tmp_path, monkeypatch):
    """Sanity check: a normal, healthy scrape must still write successfully."""
    path = _make_courses_file(tmp_path, 150)

    def fake_fetch(code, url, timeout, existing):
        return code, {
            "prerequisites": "100001",
            "restrictions": [],
            "corequisites": [],
        }, True, False

    monkeypatch.setattr(rp, "_fetch_relations", fake_fetch)

    rp.refresh_prerequisites(courses_path=path, concurrency=4)

    written = json.loads(path.read_text(encoding="utf-8"))
    assert all(c["prerequisites"] == "100001" for c in written)


def test_aborts_on_total_collapse(tmp_path, monkeypatch):
    """The original combined check: everything comes back empty."""
    path = _make_courses_file(tmp_path, 150)
    original_content = path.read_text(encoding="utf-8")

    def fake_fetch(code, url, timeout, existing):
        return code, {"prerequisites": None, "restrictions": [], "corequisites": []}, True, False

    monkeypatch.setattr(rp, "_fetch_relations", fake_fetch)

    rp.refresh_prerequisites(courses_path=path, concurrency=4)

    assert path.read_text(encoding="utf-8") == original_content


def test_dry_run_never_writes_even_on_healthy_scrape(tmp_path, monkeypatch):
    path = _make_courses_file(tmp_path, 150)
    original_content = path.read_text(encoding="utf-8")

    def fake_fetch(code, url, timeout, existing):
        return code, {"prerequisites": "100001", "restrictions": [], "corequisites": []}, True, False

    monkeypatch.setattr(rp, "_fetch_relations", fake_fetch)

    rp.refresh_prerequisites(courses_path=path, concurrency=4, dry_run=True)

    assert path.read_text(encoding="utf-8") == original_content


def test_unreliable_fetch_leaves_existing_data_untouched(tmp_path, monkeypatch):
    """
    A course that already has good, hand-verified data (like the manually-corrected
    courses documented in DATA_QUALITY.md) must NOT get overwritten by a
    fetch that never actually succeeded, even if _fetch_relations
    "succeeded" in the sense of not raising - here it's simulated as
    reliable=False, the exact signal a real caller gets after exhausting
    retries on a suspiciously short response body.
    """
    path = tmp_path / "courses.json"
    good_prereqs = {"op": "AND", "args": [{"op": "OR", "args": ["A", "B"]}, "C"]}
    courses = [{
        "course_code": "999999",
        "url": "https://example.invalid/course/999999/",
        "prerequisites": good_prereqs,
        "restrictions": [],
        "corequisites": [],
    }]
    path.write_text(json.dumps(courses), encoding="utf-8")

    def fake_fetch(code, url, timeout, existing):
        # Simulates a course that never got a confirmed-good fetch after
        # retries - the caller must not touch its existing data at all,
        # not even overwrite it with this (plausible-looking but
        # unconfirmed) empty result.
        return code, {"prerequisites": None, "restrictions": [], "corequisites": []}, False, False

    monkeypatch.setattr(rp, "_fetch_relations", fake_fetch)

    rp.refresh_prerequisites(courses_path=path, concurrency=1)

    written = json.loads(path.read_text(encoding="utf-8"))
    assert written[0]["prerequisites"] == good_prereqs, (
        "Existing good data was overwritten by an unreliable fetch result - "
        "this is exactly what corrupted courses.json in the real run."
    )


def test_reliable_fetch_does_overwrite(tmp_path, monkeypatch):
    """Sanity check: a genuinely reliable fetch must still update the course
    normally - the untouched-on-unreliable behavior must not become a
    blanket no-op."""
    path = tmp_path / "courses.json"
    courses = [{
        "course_code": "999999",
        "url": "https://example.invalid/course/999999/",
        "prerequisites": None,
        "restrictions": [],
        "corequisites": [],
    }]
    path.write_text(json.dumps(courses), encoding="utf-8")

    def fake_fetch(code, url, timeout, existing):
        return code, {"prerequisites": "111111", "restrictions": [], "corequisites": []}, True, False

    monkeypatch.setattr(rp, "_fetch_relations", fake_fetch)

    rp.refresh_prerequisites(courses_path=path, concurrency=1)

    written = json.loads(path.read_text(encoding="utf-8"))
    assert written[0]["prerequisites"] == "111111"


def test_fetch_relations_retries_on_suspiciously_short_response(monkeypatch):
    """
    _fetch_relations itself: a suspiciously short HTTP-200 response (the
    exact real pattern that corrupted 234338 - a truncated page, no
    error raised) must trigger a retry, not be trusted on the first
    attempt.
    """
    from coursemap.ingestion import prerequisite_scraper as ps

    call_count = [0]

    def fake_scrape(url, timeout=10, include_diagnostics=False):
        call_count[0] += 1
        if call_count[0] == 1:
            # First attempt: HTTP 200 but a suspiciously truncated body.
            return {
                "prerequisites": None, "restrictions": [], "corequisites": [],
                "_status_code": 200, "_content_length": 500,
            }
        # Second attempt: a genuinely healthy-sized response.
        return {
            "prerequisites": "123456", "restrictions": [], "corequisites": [],
            "_status_code": 200, "_content_length": 10000,
        }

    monkeypatch.setattr(ps, "scrape_course_relations", fake_scrape)
    monkeypatch.setattr(rp, "scrape_course_relations", fake_scrape)
    monkeypatch.setattr(rp.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(rp, "scrape_course_relations", fake_scrape)

    code, relations, reliable, permanent_failure = rp._fetch_relations("999999", "https://example.invalid/", 10, {"prerequisites": None, "restrictions": [], "corequisites": []})

    assert call_count[0] == 2, "Expected a retry after the suspiciously short first response"
    assert reliable is True
    assert relations["prerequisites"] == "123456"


def test_fetch_relations_marks_unreliable_after_exhausting_retries(monkeypatch):
    """If every attempt is suspicious, give up and report unreliable=False
    rather than returning the last (still-suspicious) attempt as if it
    were trustworthy."""
    from coursemap.ingestion import prerequisite_scraper as ps

    def fake_scrape(url, timeout=10, include_diagnostics=False):
        return {
            "prerequisites": None, "restrictions": [], "corequisites": [],
            "_status_code": 200, "_content_length": 100,
        }

    monkeypatch.setattr(ps, "scrape_course_relations", fake_scrape)
    monkeypatch.setattr(rp, "scrape_course_relations", fake_scrape)
    monkeypatch.setattr(rp.time, "sleep", lambda seconds: None)

    code, relations, reliable, permanent_failure = rp._fetch_relations("999999", "https://example.invalid/", 10, {"prerequisites": None, "restrictions": [], "corequisites": []})

    assert reliable is False


def test_fetch_relations_backoff_grows_across_attempts(monkeypatch):
    """
    The actual point of this round's fix: later attempts must sleep
    meaningfully longer than the first, not just a token amount. Asserts
    the real requested durations (mocking time.sleep itself, not the
    outcome) against _BACKOFF_RANGES_BY_ATTEMPT, so this stays correct if
    the schedule is ever tuned rather than silently drifting from it.
    """
    def fake_scrape(url, timeout=10, include_diagnostics=False):
        # Suspicious every time, so all 3 attempts (and all 3 backoff
        # sleeps) actually happen.
        return {
            "prerequisites": None, "restrictions": [], "corequisites": [],
            "_status_code": 200, "_content_length": 100,
        }

    monkeypatch.setattr(rp, "scrape_course_relations", fake_scrape)

    sleep_calls = []
    monkeypatch.setattr(rp.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    rp._fetch_relations("999999", "https://example.invalid/", 10, {"prerequisites": None, "restrictions": [], "corequisites": []})

    assert len(sleep_calls) == 3
    for attempt, duration in enumerate(sleep_calls, start=1):
        low, high = rp._BACKOFF_RANGES_BY_ATTEMPT[attempt]
        assert low <= duration <= high, (
            f"Attempt {attempt} slept {duration}s, expected within [{low}, {high}]"
        )
    assert sleep_calls[0] < sleep_calls[1] < sleep_calls[2], (
        "Backoff must grow across attempts, not stay flat or shrink"
    )


def test_final_summary_warns_when_untouched_rate_exceeds_threshold(tmp_path, monkeypatch, caplog):
    """
    A run where a large share of courses end up untouched must produce a
    loud WARNING in the final summary, not just a quiet count buried in
    an INFO line.
    """
    import logging
    path = _make_courses_file(tmp_path, 150)

    def fake_fetch(code, url, timeout, existing):
        # 30% untouched - comfortably over the 10% threshold.
        if int(code) % 10 < 3:
            return code, {"prerequisites": None, "restrictions": [], "corequisites": []}, False, False
        return code, {"prerequisites": "111111", "restrictions": [], "corequisites": []}, True, False

    monkeypatch.setattr(rp, "_fetch_relations", fake_fetch)

    with caplog.at_level(logging.WARNING, logger="coursemap.ingestion.refresh_prerequisites"):
        rp.refresh_prerequisites(courses_path=path, concurrency=4)

    warnings = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert any("were left untouched this run" in w for w in warnings), (
        f"Expected a loud untouched-rate warning in the final summary, got: {warnings}"
    )
    assert any("processed so far" in w for w in warnings), (
        f"Expected the mid-run warning to also fire (150 courses crosses one "
        f"100-done checkpoint) - got: {warnings}"
    )


def test_final_summary_does_not_warn_on_healthy_untouched_rate(tmp_path, monkeypatch, caplog):
    """A run with only a small, expected number of untouched courses must
    not trigger the threshold warning - it shouldn't cry wolf on normal,
    isolated blips."""
    import logging
    path = _make_courses_file(tmp_path, 150)

    def fake_fetch(code, url, timeout, existing):
        # ~2% untouched - comfortably under the 10% threshold.
        if code == "100000":
            return code, {"prerequisites": None, "restrictions": [], "corequisites": []}, False, False
        return code, {"prerequisites": "111111", "restrictions": [], "corequisites": []}, True, False

    monkeypatch.setattr(rp, "_fetch_relations", fake_fetch)

    with caplog.at_level(logging.WARNING, logger="coursemap.ingestion.refresh_prerequisites"):
        rp.refresh_prerequisites(courses_path=path, concurrency=4)

    warnings = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert not any("were left untouched this run" in w for w in warnings), (
        f"Did not expect an untouched-rate warning on a healthy run, got: {warnings}"
    )


def test_fetch_relations_short_circuits_on_404_no_retry(monkeypatch):
    """
    A 404 must not go through the retry schedule at all - retrying can't
    fix a resource that doesn't exist, and doing so anyway wastes up to
    ~19s per course, every run, forever, for a condition that will never
    change. Confirmed via call count, not just the final result.
    """
    call_count = [0]

    def fake_scrape(url, timeout=10, include_diagnostics=False):
        call_count[0] += 1
        return {
            "prerequisites": None, "restrictions": [], "corequisites": [],
            "_status_code": 404, "_content_length": 300,
        }

    monkeypatch.setattr(rp, "scrape_course_relations", fake_scrape)
    sleep_calls = []
    monkeypatch.setattr(rp.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    code, relations, reliable, permanent_failure = rp._fetch_relations(
        "999999", "https://example.invalid/", 10,
        {"prerequisites": None, "restrictions": [], "corequisites": []},
    )

    assert call_count[0] == 1, "404 must not be retried"
    assert len(sleep_calls) == 1, "Only the first attempt's backoff should occur, no retry backoff"
    assert reliable is False
    assert permanent_failure is True


def test_fetch_relations_short_circuits_on_410(monkeypatch):
    """410 Gone gets the same short-circuit treatment as 404."""
    call_count = [0]

    def fake_scrape(url, timeout=10, include_diagnostics=False):
        call_count[0] += 1
        return {
            "prerequisites": None, "restrictions": [], "corequisites": [],
            "_status_code": 410, "_content_length": 300,
        }

    monkeypatch.setattr(rp, "scrape_course_relations", fake_scrape)
    monkeypatch.setattr(rp.time, "sleep", lambda seconds: None)

    code, relations, reliable, permanent_failure = rp._fetch_relations(
        "999999", "https://example.invalid/", 10,
        {"prerequisites": None, "restrictions": [], "corequisites": []},
    )

    assert call_count[0] == 1
    assert permanent_failure is True


def test_permanent_failure_does_not_overwrite_existing_data(tmp_path, monkeypatch):
    """A permanently-missing course must be left untouched, exactly like
    a transient-failure course - it's a different category, but the
    write-safety guarantee is the same."""
    path = tmp_path / "courses.json"
    good_prereqs = {"op": "OR", "args": ["A", "B"]}
    courses = [{
        "course_code": "999999",
        "url": "https://example.invalid/course/999999/",
        "prerequisites": good_prereqs,
        "restrictions": [],
        "corequisites": [],
    }]
    path.write_text(json.dumps(courses), encoding="utf-8")

    def fake_fetch(code, url, timeout, existing):
        return code, {"prerequisites": None, "restrictions": [], "corequisites": []}, False, True

    monkeypatch.setattr(rp, "_fetch_relations", fake_fetch)
    rp.refresh_prerequisites(courses_path=path, concurrency=1)

    written = json.loads(path.read_text(encoding="utf-8"))
    assert written[0]["prerequisites"] == good_prereqs


def test_permanent_failures_do_not_count_toward_untouched_threshold(tmp_path, monkeypatch, caplog):
    """
    The actual point of separating these two categories: a catalogue
    where 30% of courses are permanently 404 (e.g. stale
    specialisations.json) must NOT trip the systemic-throttling warning,
    since that's not what's happening - only genuinely transient,
    retry-exhausted failures should count toward that signal.
    """
    import logging
    path = _make_courses_file(tmp_path, 150)

    def fake_fetch(code, url, timeout, existing):
        # 30% permanently missing, 0% transiently untouched.
        if int(code) % 10 < 3:
            return code, {"prerequisites": None, "restrictions": [], "corequisites": []}, False, True
        return code, {"prerequisites": "111111", "restrictions": [], "corequisites": []}, True, False

    monkeypatch.setattr(rp, "_fetch_relations", fake_fetch)

    with caplog.at_level(logging.WARNING, logger="coursemap.ingestion.refresh_prerequisites"):
        rp.refresh_prerequisites(courses_path=path, concurrency=4)

    warnings = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert not any("were left untouched this run" in w for w in warnings), (
        f"A 30% permanent-failure rate must not trigger the transient-failure "
        f"threshold warning - got: {warnings}"
    )
    assert not any("processed so far" in w for w in warnings), (
        f"Same for the mid-run warning - got: {warnings}"
    )


def test_final_summary_reports_permanently_missing_count(tmp_path, monkeypatch, caplog):
    """The final summary must mention the permanently-missing count as its
    own figure, separate from left_untouched, so it's visible without
    being confused for a systemic problem."""
    import logging
    path = _make_courses_file(tmp_path, 150)

    def fake_fetch(code, url, timeout, existing):
        if code == "100000":
            return code, {"prerequisites": None, "restrictions": [], "corequisites": []}, False, True
        return code, {"prerequisites": "111111", "restrictions": [], "corequisites": []}, True, False

    monkeypatch.setattr(rp, "_fetch_relations", fake_fetch)

    with caplog.at_level(logging.INFO, logger="coursemap.ingestion.refresh_prerequisites"):
        rp.refresh_prerequisites(courses_path=path, concurrency=4)

    info_messages = [r.message for r in caplog.records if r.levelno == logging.INFO]
    assert any("1 course(s) returned a permanent failure" in m for m in info_messages), (
        f"Expected the permanently-missing count in the final summary, got: {info_messages}"
    )


def test_unexpected_exception_counts_toward_untouched_and_is_visible_to_warning(tmp_path, monkeypatch, caplog):
    """
    An unexpected exception (a bug, not a handled network/HTTP failure -
    those are already caught inside _fetch_relations itself) must not be
    an invisible blind spot.
    It's safe already (nothing gets written), but it must also count
    toward left_untouched so a batch of such failures is visible to the
    systemic-problem warning, not silently absorbed by a bare 'continue'.
    """
    import logging
    path = _make_courses_file(tmp_path, 150)

    def fake_fetch(code, url, timeout, existing):
        if int(code) % 10 < 3:
            raise RuntimeError("simulated bug, not a network failure")
        return code, {"prerequisites": "111111", "restrictions": [], "corequisites": []}, True, False

    monkeypatch.setattr(rp, "_fetch_relations", fake_fetch)

    with caplog.at_level(logging.WARNING, logger="coursemap.ingestion.refresh_prerequisites"):
        rp.refresh_prerequisites(courses_path=path, concurrency=4)

    warnings = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert any("were left untouched this run" in w for w in warnings), (
        f"A 30% unexpected-exception rate must be visible to the same threshold "
        f"warning as a 30% suspicious-fetch rate - got: {warnings}"
    )


# --- _is_suspicious_regression: proven against the real incident data ---
# See DATA_QUALITY.md for the
# full account of what happened and how these exact values were confirmed
# live against Massey's actual pages.

def test_is_suspicious_regression_catches_real_123305_incident():
    """
    Course 123305's real prerequisite tree, live-verified correct earlier,
    versus what a real production scrape run actually
    returned for it (twice, identically, at two very different speeds).
    HTTP 200, a normal-sized response, no error - only this check catches it.
    """
    from coursemap.ingestion.refresh_prerequisites import _is_suspicious_regression

    correct = {
        "prerequisites": {"op": "AND", "args": [
            {"op": "OR", "args": ["123101", "123102", "123104", "123105", "123171", "123172"]},
            {"op": "OR", "args": ["247111", "247112", "247113", "247114"]},
        ]},
        "restrictions": [], "corequisites": [],
    }
    actually_returned = {
        "prerequisites": {"op": "AND", "args": [
            {"op": "OR", "args": ["123104", "123105"]},
            {"op": "OR", "args": ["247111", "247112", "247113", "247114"]},
        ]},
        "restrictions": [], "corequisites": [],
    }

    is_suspicious, reason = _is_suspicious_regression(correct, actually_returned)
    assert is_suspicious
    assert "123101" in reason and "123102" in reason and "123171" in reason and "123172" in reason


def test_is_suspicious_regression_catches_real_234338_incident():
    """
    Course 234338: the corrupted version was missing both one course from
    an OR-group (234233) AND a whole separate required course (234315)
    entirely. Confirms the flat code-set approach catches a missing
    *sibling* AND-clause, not just a missing OR-alternative.
    """
    from coursemap.ingestion.refresh_prerequisites import _is_suspicious_regression

    correct = {
        "prerequisites": {"op": "AND", "args": [
            {"op": "OR", "args": ["234214", "234215", "234236", "234243", "152237", "234233"]},
            "152238",
            "234315",
        ]},
        "restrictions": ["152371", "152372", "152376", "234316"], "corequisites": [],
    }
    actually_returned = {
        "prerequisites": {"op": "AND", "args": [
            {"op": "OR", "args": ["234214", "234215", "234236", "234243", "152237"]},
            "152238",
        ]},
        "restrictions": ["152371", "152372", "152376", "234316"], "corequisites": [],
    }

    is_suspicious, reason = _is_suspicious_regression(correct, actually_returned)
    assert is_suspicious
    assert "234233" in reason and "234315" in reason


def test_is_suspicious_regression_no_existing_data_never_suspicious():
    """A first-time scrape (nothing stored yet) finding something is
    progress, never a regression, no matter how little it finds."""
    from coursemap.ingestion.refresh_prerequisites import _is_suspicious_regression

    no_existing = {"prerequisites": None, "restrictions": [], "corequisites": []}
    fresh = {"prerequisites": "123101", "restrictions": [], "corequisites": []}

    is_suspicious, reason = _is_suspicious_regression(no_existing, fresh)
    assert not is_suspicious


def test_is_suspicious_regression_growing_set_not_suspicious():
    """Massey genuinely adding a new prerequisite option over time must
    never be flagged."""
    from coursemap.ingestion.refresh_prerequisites import _is_suspicious_regression

    existing = {"prerequisites": {"op": "OR", "args": ["A", "B"]}, "restrictions": [], "corequisites": []}
    fresh = {"prerequisites": {"op": "OR", "args": ["A", "B", "C"]}, "restrictions": [], "corequisites": []}

    is_suspicious, reason = _is_suspicious_regression(existing, fresh)
    assert not is_suspicious


def test_is_suspicious_regression_same_set_not_suspicious():
    existing = {"prerequisites": {"op": "OR", "args": ["A", "B"]}, "restrictions": [], "corequisites": []}
    fresh = {"prerequisites": {"op": "OR", "args": ["B", "A"]}, "restrictions": [], "corequisites": []}

    from coursemap.ingestion.refresh_prerequisites import _is_suspicious_regression
    is_suspicious, reason = _is_suspicious_regression(existing, fresh)
    assert not is_suspicious


def test_is_suspicious_regression_applies_to_restrictions_field_too():
    """The check is per-field - restrictions/corequisites can regress
    independently of prerequisites."""
    from coursemap.ingestion.refresh_prerequisites import _is_suspicious_regression

    existing = {"prerequisites": None, "restrictions": ["161223", "161777"], "corequisites": []}
    fresh = {"prerequisites": None, "restrictions": ["161223"], "corequisites": []}

    is_suspicious, reason = _is_suspicious_regression(existing, fresh)
    assert is_suspicious
    assert "restrictions" in reason and "161777" in reason


def test_is_suspicious_regression_disjoint_different_codes_not_flagged():
    """
    Documents the explicit, deliberate scope boundary: a fresh result
    with entirely different codes (neither a subset nor superset of the
    existing set) is NOT flagged. No real incident has shown this
    pattern - only ever a straightforward subset - so guessing at this
    failure mode would risk false-triggering on a genuine content change
    with zero evidence it's ever actually wrong.
    """
    from coursemap.ingestion.refresh_prerequisites import _is_suspicious_regression

    existing = {"prerequisites": "159102", "restrictions": [], "corequisites": []}
    fresh = {"prerequisites": "159103", "restrictions": [], "corequisites": []}

    is_suspicious, reason = _is_suspicious_regression(existing, fresh)
    assert not is_suspicious


def test_fetch_relations_detects_regression_despite_healthy_status_and_length(monkeypatch):
    """
    Integration proof at the _fetch_relations level (not just the
    standalone function): a response with HTTP 200 and a perfectly
    healthy content_length must still be caught if its codes are a
    regression from what's already stored - exactly the real incident,
    where the byte-length check alone saw nothing wrong.
    """
    correct = {"op": "AND", "args": [
        {"op": "OR", "args": ["123101", "123102", "123104", "123105", "123171", "123172"]},
        {"op": "OR", "args": ["247111", "247112", "247113", "247114"]},
    ]}
    corrupted = {"op": "AND", "args": [
        {"op": "OR", "args": ["123104", "123105"]},
        {"op": "OR", "args": ["247111", "247112", "247113", "247114"]},
    ]}
    existing = {"prerequisites": correct, "restrictions": [], "corequisites": []}

    def fake_scrape(url, timeout=10, include_diagnostics=False):
        return {
            "prerequisites": corrupted, "restrictions": [], "corequisites": [],
            "_status_code": 200, "_content_length": 10000,  # healthy by every existing measure
        }

    monkeypatch.setattr(rp, "scrape_course_relations", fake_scrape)
    monkeypatch.setattr(rp.time, "sleep", lambda seconds: None)

    code, relations, reliable, permanent_failure = rp._fetch_relations(
        "123305", "https://example.invalid/", 10, existing,
    )

    assert reliable is False, (
        "A healthy-looking response with regressed codes must still be "
        "caught - this is the exact real incident."
    )


def test_regression_check_prevents_overwrite_end_to_end(tmp_path, monkeypatch):
    """
    Full refresh_prerequisites() proof: a course with real, previously-
    good prerequisite data must not be overwritten when the fresh fetch
    is a regression, even though the fetch itself reports HTTP 200 at a
    healthy size.
    """
    path = tmp_path / "courses.json"
    correct = {"op": "AND", "args": [
        {"op": "OR", "args": ["123101", "123102", "123104", "123105", "123171", "123172"]},
        {"op": "OR", "args": ["247111", "247112", "247113", "247114"]},
    ]}
    courses = [{
        "course_code": "123305",
        "url": "https://example.invalid/course/123305/",
        "prerequisites": correct,
        "restrictions": [],
        "corequisites": [],
    }]
    path.write_text(json.dumps(courses), encoding="utf-8")

    corrupted = {"op": "AND", "args": [
        {"op": "OR", "args": ["123104", "123105"]},
        {"op": "OR", "args": ["247111", "247112", "247113", "247114"]},
    ]}

    def fake_scrape(url, timeout=10, include_diagnostics=False):
        return {
            "prerequisites": corrupted, "restrictions": [], "corequisites": [],
            "_status_code": 200, "_content_length": 10000,
        }

    monkeypatch.setattr(rp, "scrape_course_relations", fake_scrape)
    monkeypatch.setattr(rp.time, "sleep", lambda seconds: None)

    rp.refresh_prerequisites(courses_path=path, concurrency=1)

    written = json.loads(path.read_text(encoding="utf-8"))
    assert written[0]["prerequisites"] == correct, (
        "The regressed fetch must not have overwritten the real, correct, "
        "previously-stored value."
    )
