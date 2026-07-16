"""
Tests for build_majors_dataset.py's safety mechanisms.

Everything here monkeypatches _fetch_one directly, so nothing touches
the network - these test the orchestration/safety logic, not scraping.
"""
import json

from coursemap.ingestion import build_majors_dataset as bmd


def _fake_specialisations(count):
    return [
        {"title": f"Fake Major {i}", "url": f"https://example.invalid/major/{i}/"}
        for i in range(count)
    ]


def test_aborts_when_almost_nothing_succeeds(tmp_path, monkeypatch):
    """
    If (almost) every fetch fails - Massey's structure changed, the
    network is down, specialisations.json is stale - refuse to
    overwrite majors.json with a near-empty result.
    """
    majors_path = tmp_path / "majors.json"
    original_content = json.dumps([{"name": "Existing Major", "url": "x", "requirement": {}}])
    majors_path.write_text(original_content, encoding="utf-8")

    monkeypatch.setattr(bmd, "_load_specialisations", lambda: _fake_specialisations(30))

    def fake_fetch(index, title, url, timeout):
        return index, None  # every fetch fails

    monkeypatch.setattr(bmd, "_fetch_one", fake_fetch)

    bmd.build_majors_dataset(concurrency=4, majors_path=majors_path)

    assert majors_path.read_text(encoding="utf-8") == original_content, (
        "majors.json was modified despite (almost) every fetch failing - "
        "the abort check failed to catch it."
    )


def test_does_not_abort_on_healthy_run(tmp_path, monkeypatch):
    """A normal, healthy run must still write successfully."""
    majors_path = tmp_path / "majors.json"
    majors_path.write_text("[]", encoding="utf-8")

    monkeypatch.setattr(bmd, "_load_specialisations", lambda: _fake_specialisations(30))

    def fake_fetch(index, title, url, timeout):
        return index, {"name": title, "url": url, "requirement": {"type": "ALL_OF", "children": []}}

    monkeypatch.setattr(bmd, "_fetch_one", fake_fetch)

    bmd.build_majors_dataset(concurrency=4, majors_path=majors_path)

    written = json.loads(majors_path.read_text(encoding="utf-8"))
    assert len(written) == 30
    assert all(m["name"].startswith("Fake Major") for m in written)


def test_dry_run_never_writes_even_on_healthy_run(tmp_path, monkeypatch):
    majors_path = tmp_path / "majors.json"
    original_content = "[]"
    majors_path.write_text(original_content, encoding="utf-8")

    monkeypatch.setattr(bmd, "_load_specialisations", lambda: _fake_specialisations(30))

    def fake_fetch(index, title, url, timeout):
        return index, {"name": title, "url": url, "requirement": {"type": "ALL_OF", "children": []}}

    monkeypatch.setattr(bmd, "_fetch_one", fake_fetch)

    bmd.build_majors_dataset(concurrency=4, dry_run=True, majors_path=majors_path)

    assert majors_path.read_text(encoding="utf-8") == original_content


def test_limit_only_processes_first_n(tmp_path, monkeypatch):
    majors_path = tmp_path / "majors.json"
    majors_path.write_text("[]", encoding="utf-8")

    monkeypatch.setattr(bmd, "_load_specialisations", lambda: _fake_specialisations(30))

    calls = []

    def fake_fetch(index, title, url, timeout):
        calls.append(title)
        return index, {"name": title, "url": url, "requirement": {"type": "ALL_OF", "children": []}}

    monkeypatch.setattr(bmd, "_fetch_one", fake_fetch)

    bmd.build_majors_dataset(concurrency=4, limit=5, majors_path=majors_path)

    assert len(calls) == 5


def test_output_order_matches_input_order_despite_concurrency(tmp_path, monkeypatch):
    """
    Fetches complete out of order under concurrency; the written list
    must still match the original specialisations.json order, not
    completion order, since nothing downstream should have to care about
    ordering, and stable output makes diffs against a previous run
    actually readable.
    """
    majors_path = tmp_path / "majors.json"
    majors_path.write_text("[]", encoding="utf-8")

    specs = _fake_specialisations(10)
    monkeypatch.setattr(bmd, "_load_specialisations", lambda: specs)

    def fake_fetch(index, title, url, timeout):
        # Deliberately make later-indexed items "complete" first, to
        # prove ordering doesn't leak from completion order.
        return index, {"name": title, "url": url, "requirement": {}}

    monkeypatch.setattr(bmd, "_fetch_one", fake_fetch)

    bmd.build_majors_dataset(concurrency=4, majors_path=majors_path)

    written = json.loads(majors_path.read_text(encoding="utf-8"))
    assert [m["name"] for m in written] == [s["title"] for s in specs]


def test_specialisation_with_no_url_is_skipped_not_crashed(tmp_path, monkeypatch):
    majors_path = tmp_path / "majors.json"
    majors_path.write_text("[]", encoding="utf-8")

    specs = _fake_specialisations(25) + [{"title": "No URL Major"}]
    monkeypatch.setattr(bmd, "_load_specialisations", lambda: specs)

    def fake_fetch(index, title, url, timeout):
        return index, {"name": title, "url": url, "requirement": {}}

    monkeypatch.setattr(bmd, "_fetch_one", fake_fetch)

    bmd.build_majors_dataset(concurrency=4, majors_path=majors_path)

    written = json.loads(majors_path.read_text(encoding="utf-8"))
    assert len(written) == 25
    assert "No URL Major" not in [m["name"] for m in written]
