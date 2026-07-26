"""
Tests for scripts/audit_pool_overlap.py's detection logic.

Uses synthetic requirement trees throughout, not the live dataset, so
these stay correct regardless of what majors.json currently contains.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from audit_pool_overlap import _find_overlapping_siblings, find_overlapping_pools


def _choose_credits(credits, codes):
    return {"type": "CHOOSE_CREDITS", "credits": credits, "course_codes": codes}


def _all_of(*children):
    return {"type": "ALL_OF", "children": list(children)}


def test_detects_fully_overlapping_sibling_pools():
    """The Animal Science MSc shape: two CHOOSE_CREDITS pools under the
    same ALL_OF, same course codes, different credit targets - the
    signature of a mis-encoded Either/Or."""
    tree = _all_of(
        _choose_credits(120, ["A", "B", "C"]),
        _choose_credits(60, ["A", "B", "C"]),
    )
    hits = _find_overlapping_siblings(tree, threshold=0.7)
    assert hits == [(120, 60, 3, 3)]


def test_no_hit_when_pools_are_disjoint():
    """Two genuinely separate pools with no shared courses must not be
    flagged - this is the normal, correct case (e.g. two different named
    elective requirements within the same major)."""
    tree = _all_of(
        _choose_credits(30, ["A", "B"]),
        _choose_credits(30, ["C", "D"]),
    )
    assert _find_overlapping_siblings(tree, threshold=0.7) == []


def test_no_hit_below_threshold():
    """Partial overlap below the threshold must not be flagged - some
    legitimate overlap (a course counting toward two different pools) is
    expected and not itself a bug signal."""
    tree = _all_of(
        _choose_credits(30, ["A", "B", "C", "D", "E"]),
        _choose_credits(30, ["A", "F", "G", "H", "I"]),
    )
    assert _find_overlapping_siblings(tree, threshold=0.7) == []


def test_hit_at_exactly_the_threshold():
    """3 of 4 codes overlapping (0.75) must pass a 0.7 threshold."""
    tree = _all_of(
        _choose_credits(60, ["A", "B", "C", "D"]),
        _choose_credits(90, ["A", "B", "C", "E"]),
    )
    hits = _find_overlapping_siblings(tree, threshold=0.7)
    assert hits == [(60, 90, 3, 4)]


def test_recurses_into_nested_children():
    """The overlap doesn't have to be at the top level of the tree - must
    be found however deeply nested."""
    tree = _all_of(
        _choose_credits(15, ["Z"]),
        _all_of(
            _choose_credits(120, ["A", "B"]),
            _choose_credits(60, ["A", "B"]),
        ),
    )
    hits = _find_overlapping_siblings(tree, threshold=0.7)
    assert hits == [(120, 60, 2, 2)]


def test_ignores_non_choose_credits_siblings():
    """A CHOOSE_CREDITS pool sharing codes with a plain COURSE sibling
    isn't the pattern this script looks for - only CHOOSE_CREDITS-vs-
    CHOOSE_CREDITS pairs count."""
    tree = _all_of(
        {"type": "COURSE", "course_code": "A"},
        _choose_credits(30, ["A", "B", "C"]),
    )
    assert _find_overlapping_siblings(tree, threshold=0.7) == []


def test_empty_pools_never_flagged():
    """An open (empty course_codes) pool paired with anything must not be
    flagged - there's nothing to compare overlap against."""
    tree = _all_of(
        _choose_credits(30, []),
        _choose_credits(30, ["A", "B", "C"]),
    )
    assert _find_overlapping_siblings(tree, threshold=0.7) == []


def test_find_overlapping_pools_only_returns_majors_with_hits():
    majors = [
        {"name": "Clean Major", "requirement": _all_of(
            _choose_credits(30, ["A"]), _choose_credits(30, ["B"]),
        )},
        {"name": "Suspicious Major", "requirement": _all_of(
            _choose_credits(120, ["A", "B"]), _choose_credits(60, ["A", "B"]),
        )},
    ]
    results = find_overlapping_pools(majors)
    names = [name for name, _ in results]
    assert names == ["Suspicious Major"]
