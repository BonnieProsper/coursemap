"""
Regression tests for the --no-summer / --allow-summer CLI flag.

Bug history: --no-summer was originally declared as
``action="store_true", default=True``, which meant there was no way to
pass --no-summer=False from the command line. The flag was always on,
and the only documented escape ("remove --no-summer") did nothing because
the default was already True. A student whose required course is only
offered in Summer School had no way to plan around it via the CLI (the
API/UI path was unaffected, since it used a plain bool field there).

First fix attempt used argparse.BooleanOptionalAction, which seemed like
the idiomatic choice, but BooleanOptionalAction unconditionally treats
any option string starting with "--no-" as the negative form (it checks
``option_string.startswith("--no-")`` to decide True/False). Since the
flag's own name is "--no-summer", that check misfires on the flag's own
positive form: passing --no-summer was silently read as False. This is
incompatible with any flag whose own name already starts with "no-",
not something fixable by registration order or aliasing.

Final fix: a plain --no-summer (store_true, default True, kept for
backwards compatibility, explicitly passing it is a no-op) paired with
a separate --allow-summer (store_false) on the same dest. This mirrors
the wording already used in the web UI's "Allow Summer School" checkbox.
"""
from __future__ import annotations

import json

import pytest

from coursemap.cli.main import main


# A major known to require a Summer-School-only course to reach its credit
# target (see DATA_QUALITY.md, "Without Specialisation – Postgraduate
# Diploma in Science and Technology" has no specific required courses other
# than this flattened list, and 119791 is SS-only at D/DIS).
_SS_ONLY_MAJOR = "Without Specialisation – Postgraduate Diploma in Science and Technology"


def _run(monkeypatch, argv):
    monkeypatch.setattr("sys.argv", ["coursemap"] + argv)
    main()


def test_default_still_skips_summer_school(tmp_path, monkeypatch, capsys):
    """Default behaviour (no flag passed) must be unchanged: SS is skipped,
    so a degree that needs an SS-only course fails with a clear error
    rather than silently scheduling it."""
    out = tmp_path / "plan.json"
    with pytest.raises(SystemExit):
        _run(monkeypatch, [
            "plan", "--major", _SS_ONLY_MAJOR,
            "--campus", "D", "--mode", "DIS",
            "--output", str(out),
        ])
    captured = capsys.readouterr()
    assert "Summer School" in captured.out or "Summer School" in captured.err
    assert not out.exists()


def test_allow_summer_flag_enables_ss_scheduling(tmp_path, monkeypatch):
    """--allow-summer must actually flip no_summer to False end-to-end.
    this is the exact flag the error message recommends, so it must work."""
    out = tmp_path / "plan.json"
    _run(monkeypatch, [
        "plan", "--major", _SS_ONLY_MAJOR,
        "--campus", "D", "--mode", "DIS",
        "--allow-summer",
        "--output", str(out),
    ])
    assert out.exists()
    data = json.loads(out.read_text(encoding="utf-8"))
    semesters = {s["semester"] for s in data["semesters"]}
    assert "SS" in semesters


def test_explicit_no_summer_flag_matches_default(tmp_path, monkeypatch, capsys):
    """Explicitly passing --no-summer must behave the same as the default
    (it's a no-op kept for backwards compatibility, the actual override
    is --allow-summer, on a separate store_false action)."""
    out = tmp_path / "plan.json"
    with pytest.raises(SystemExit):
        _run(monkeypatch, [
            "plan", "--major", _SS_ONLY_MAJOR,
            "--campus", "D", "--mode", "DIS",
            "--no-summer",
            "--output", str(out),
        ])
    assert not out.exists()
