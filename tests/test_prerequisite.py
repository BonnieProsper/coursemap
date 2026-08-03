from coursemap.domain.prerequisite import (
    CoursePrerequisite,
    AndExpression,
    OrExpression,
)


def test_single_course_requirement():
    expr = CoursePrerequisite("STAT101")

    assert expr.is_satisfied({"STAT101"})
    assert not expr.is_satisfied({"MATH101"})


def test_and_expression():
    expr = AndExpression((
        CoursePrerequisite("STAT101"),
        CoursePrerequisite("MATH101"),
    ))

    assert expr.is_satisfied({"STAT101", "MATH101"})
    assert not expr.is_satisfied({"STAT101"})
    assert not expr.is_satisfied({"MATH101"})


def test_or_expression():
    expr = OrExpression((
        CoursePrerequisite("STAT101"),
        CoursePrerequisite("MATH101"),
    ))

    assert expr.is_satisfied({"STAT101"})
    assert expr.is_satisfied({"MATH101"})
    assert not expr.is_satisfied({"COMP101"})


def test_nested_expression():
    expr = AndExpression((
        CoursePrerequisite("STAT101"),
        OrExpression((
            CoursePrerequisite("MATH101"),
            CoursePrerequisite("MATH102"),
        )),
    ))

    assert expr.is_satisfied({"STAT101", "MATH101"})
    assert expr.is_satisfied({"STAT101", "MATH102"})
    assert not expr.is_satisfied({"STAT101"})
    assert not expr.is_satisfied({"MATH101"})


# ---------------------------------------------------------------------------
# Tests for the new structured-format parser and HTML extraction
#
# These need bs4 (part of the `ingestion` extra, not `dev`). A plain
# dev-only install (`pip install -e ".[dev]"`) is a reasonable, minimal
# thing to do if someone just wants to hack on the planner logic without
# the scraping tools, so this file skips gracefully instead of crashing
# the WHOLE test suite's collection (a bare top-level `from bs4 import ...`
# that fails aborts collection for every test file, not just this one).
# ---------------------------------------------------------------------------

import pytest
pytest.importorskip("bs4", reason="bs4 is part of the `ingestion` extra: pip install -e '.[ingestion]'")

from coursemap.domain.prerequisite_utils import prereqs_met
from coursemap.ingestion.dataset_loader import parse_prereqs as _parse_prereqs
from coursemap.ingestion.prerequisite_scraper import (
    parse_prerequisite_text,
    parse_code_list_text,
    tokenize as _tokenize,
    find_prereq_text as _find_prereq_text,
    find_restriction_text as _find_restriction_text,
    find_corequisite_text as _find_corequisite_text,
    scrape_course_relations,
)
from bs4 import BeautifulSoup


# --- tokenizer ---

def test_tokenize_single_code():
    assert _tokenize("115230") == ["115230"]


def test_tokenize_or():
    assert _tokenize("115230 or 115233") == ["115230", "or", "115233"]


def test_tokenize_and():
    assert _tokenize("115230 and 115231") == ["115230", "and", "115231"]


def test_tokenize_comma_as_and():
    assert _tokenize("115230, 115231") == ["115230", "and", "115231"]


def test_tokenize_one_of_flat_list_treats_commas_as_or():
    """
    Real Massey phrasing: "One of A, B, C or D" is a single enumerated
    choice, not "A and B and C, plus one of C or D". Without this, the
    default comma-as-AND rule made the requirement artificially strict.
    Reproduces 161324 (Data Mining)'s real prerequisite, which was
    incorrectly parsed as AND(161122, 297101, 161220, 161221, OR(161250,
    161251)) before this fix.
    """
    assert _tokenize("One of 161122, 297101, 161220, 161221, 161250 or 161251") == [
        "161122", "or", "297101", "or", "161220", "or", "161221", "or", "161250", "or", "161251",
    ]


def test_tokenize_one_of_flat_list_no_trailing_or():
    # Massey doesn't always bother with a final "or" before the last code.
    assert _tokenize("One of 158222, 125340, 125342") == [
        "158222", "or", "125340", "or", "125342",
    ]


def test_tokenize_one_of_parenthesised_clauses_unaffected():
    # Already unambiguous (explicit "or" inside each group, "and" between
    # groups), so this shouldn't be touched by the flat-list rewrite.
    text = "(One of (161122 or 161220 or 233214) and one of (160101 or 160102 or 160105))"
    tokens = _tokenize(text)
    assert tokens.count("and") == 1
    assert tokens.count("or") == 4


def test_tokenize_plain_comma_list_without_one_of_marker_is_still_and():
    # No "one of"/"any of" marker at all: the existing comma-as-AND
    # behaviour must be unchanged.
    assert _tokenize("159102, 160101") == ["159102", "and", "160101"]


def test_parse_one_of_flat_list_produces_or_expression():
    assert parse_prerequisite_text(
        "One of 161122, 297101, 161220, 161221, 161250 or 161251"
    ) == {
        "op": "OR",
        "args": ["161122", "297101", "161220", "161221", "161250", "161251"],
    }


def test_tokenize_parens():
    assert _tokenize("(115230 or 115231) and 115100") == [
        "(", "115230", "or", "115231", ")", "and", "115100"
    ]


def test_tokenize_dotted_codes():
    # Massey sometimes writes "115.230" in prerequisite text
    assert _tokenize("115.230 or 115.231") == ["115230", "or", "115231"]


def test_tokenize_strips_header():
    assert _tokenize("Prerequisite(s): 115230") == ["115230"]
    assert _tokenize("Prerequisites: 115230 or 115233") == ["115230", "or", "115233"]


# --- parse_prerequisite_text ---

def test_parse_none_and_empty():
    assert parse_prerequisite_text("") is None
    assert parse_prerequisite_text("   ") is None
    assert parse_prerequisite_text("no numbers here") is None


def test_parse_single_code():
    assert parse_prerequisite_text("115230") == "115230"


def test_parse_a_or_b():
    result = parse_prerequisite_text("115230 or 115233")
    assert result == {"op": "OR", "args": ["115230", "115233"]}


def test_parse_a_and_b():
    result = parse_prerequisite_text("115230 and 115231")
    assert result == {"op": "AND", "args": ["115230", "115231"]}


def test_parse_comma_and():
    result = parse_prerequisite_text("115230, 115231")
    assert result == {"op": "AND", "args": ["115230", "115231"]}


def test_parse_a_or_b_or_c():
    result = parse_prerequisite_text("115230 or 115231 or 115232")
    assert result == {"op": "OR", "args": ["115230", "115231", "115232"]}


def test_parse_grouped_or_and():
    # (A or B) and C
    result = parse_prerequisite_text("(115230 or 115231) and 115100")
    assert result == {
        "op": "AND",
        "args": [
            {"op": "OR", "args": ["115230", "115231"]},
            "115100",
        ],
    }


def test_parse_with_header():
    result = parse_prerequisite_text("Prerequisite(s): 115230 or 115233")
    assert result == {"op": "OR", "args": ["115230", "115233"]}


def test_parse_dotted_codes():
    result = parse_prerequisite_text("115.230 or 115.231")
    assert result == {"op": "OR", "args": ["115230", "115231"]}


# --- HTML extraction (_find_prereq_text) ---

def test_find_prereq_dt_dd():
    html = """<dl>
        <dt>Prerequisite(s)</dt><dd>115230 or 115233</dd>
        <dt>Other</dt><dd>something</dd>
    </dl>"""
    soup = BeautifulSoup(html, "html.parser")
    assert _find_prereq_text(soup) == "115230 or 115233"


def test_find_prereq_inline_label():
    html = "<p>Prerequisite(s): 115230 and 115231</p>"
    soup = BeautifulSoup(html, "html.parser")
    text = _find_prereq_text(soup)
    assert text is not None
    assert "115230" in text


def test_find_prereq_heading_sibling():
    html = "<h3>Prerequisites</h3><p>115230 or 115233</p>"
    soup = BeautifulSoup(html, "html.parser")
    text = _find_prereq_text(soup)
    assert text is not None
    assert "115230" in text


def test_find_prereq_none_when_absent():
    html = "<html><body><h1>Course</h1><p>Description only.</p></body></html>"
    soup = BeautifulSoup(html, "html.parser")
    assert _find_prereq_text(soup) is None


# --- _parse_prereqs (dataset_loader) ---

def test_parse_prereqs_old_list_single():
    """Old flat-list format with one code → CoursePrerequisite."""
    result = _parse_prereqs(["115230"], own_code="999999")
    assert result == CoursePrerequisite("115230")


def test_parse_prereqs_old_list_multiple_is_and():
    """Old flat-list format with multiple codes → AndExpression."""
    result = _parse_prereqs(["115230", "115231"], own_code="999999")
    assert isinstance(result, AndExpression)
    assert result == AndExpression((
        CoursePrerequisite("115230"),
        CoursePrerequisite("115231"),
    ))


def test_parse_prereqs_old_list_strips_self_ref():
    """Old format strips the course's own code."""
    result = _parse_prereqs(["115230", "115230_self"], own_code="115230_self")
    assert result == CoursePrerequisite("115230")


def test_parse_prereqs_new_single_str():
    """New format: bare string → CoursePrerequisite."""
    result = _parse_prereqs("115230", own_code="")
    assert result == CoursePrerequisite("115230")


def test_parse_prereqs_new_or():
    """New format: OR dict → OrExpression."""
    struct = {"op": "OR", "args": ["115230", "115233"]}
    result = _parse_prereqs(struct, own_code="")
    assert isinstance(result, OrExpression)
    assert result == OrExpression((
        CoursePrerequisite("115230"),
        CoursePrerequisite("115233"),
    ))


def test_parse_prereqs_new_and():
    """New format: AND dict → AndExpression."""
    struct = {"op": "AND", "args": ["115230", "115231"]}
    result = _parse_prereqs(struct, own_code="")
    assert isinstance(result, AndExpression)


def test_parse_prereqs_new_nested():
    """New format: (A OR B) AND C → nested expression."""
    struct = {
        "op": "AND",
        "args": [
            {"op": "OR", "args": ["115230", "115231"]},
            "115100",
        ],
    }
    result = _parse_prereqs(struct, own_code="")
    expected = AndExpression((
        OrExpression((CoursePrerequisite("115230"), CoursePrerequisite("115231"))),
        CoursePrerequisite("115100"),
    ))
    assert result == expected


def test_parse_prereqs_strips_self_ref_in_struct():
    """New format: self-reference in struct is stripped."""
    struct = {"op": "OR", "args": ["115230", "115230"]}
    result = _parse_prereqs(struct, own_code="115230")
    # Both args are self-refs → stripped → result is None
    assert result is None


def test_parse_prereqs_none_and_empty():
    assert _parse_prereqs(None) is None
    assert _parse_prereqs([]) is None
    assert _parse_prereqs("") is None


# --- prereqs_met with OR expressions ---

def test_prereqs_met_a_or_b_satisfied_by_a():
    expr = OrExpression((CoursePrerequisite("115230"), CoursePrerequisite("115233")))
    known = {"115230", "115233"}
    assert prereqs_met(expr, {"115230"}, known) is True
    assert prereqs_met(expr, {"115233"}, known) is True


def test_prereqs_met_a_or_b_not_satisfied():
    expr = OrExpression((CoursePrerequisite("115230"), CoursePrerequisite("115233")))
    known = {"115230", "115233"}
    assert prereqs_met(expr, set(), known) is False


def test_prereqs_met_a_and_b():
    expr = AndExpression((CoursePrerequisite("115230"), CoursePrerequisite("115231")))
    known = {"115230", "115231"}
    assert prereqs_met(expr, {"115230", "115231"}, known) is True
    assert prereqs_met(expr, {"115230"}, known) is False
    assert prereqs_met(expr, set(), known) is False


def test_prereqs_met_a_or_b_and_c():
    # (A or B) and C
    expr = AndExpression((
        OrExpression((CoursePrerequisite("115230"), CoursePrerequisite("115231"))),
        CoursePrerequisite("115100"),
    ))
    known = {"115230", "115231", "115100"}
    # A + C → True
    assert prereqs_met(expr, {"115230", "115100"}, known) is True
    # B + C → True
    assert prereqs_met(expr, {"115231", "115100"}, known) is True
    # A only (missing C) → False
    assert prereqs_met(expr, {"115230"}, known) is False
    # C only (missing A or B) → False
    assert prereqs_met(expr, {"115100"}, known) is False


def test_prereqs_met_unknown_code_treated_as_satisfied():
    """A prerequisite code not in 'known' is treated as pre-satisfied (gatekeeper)."""
    expr = OrExpression((
        CoursePrerequisite("627739"),   # admission gatekeeper (not in known)
        CoursePrerequisite("115230"),
    ))
    known = {"115230"}  # 627739 not in known
    # 627739 is unknown → treated as satisfied → OR is True even with empty completed
    assert prereqs_met(expr, set(), known) is True


def test_prereqs_met_from_parsed_html():
    """End-to-end: HTML → text → struct → expression → prereqs_met."""
    html = "<dt>Prerequisite(s)</dt><dd>115230 or 115233</dd>"
    soup = BeautifulSoup(html, "html.parser")
    text = _find_prereq_text(soup)
    assert text is not None

    struct = parse_prerequisite_text(text)
    expr = _parse_prereqs(struct, own_code="")
    assert isinstance(expr, OrExpression)

    known = {"115230", "115233"}
    assert prereqs_met(expr, {"115230"}, known) is True
    assert prereqs_met(expr, {"115233"}, known) is True
    assert prereqs_met(expr, set(), known) is False


# ---------------------------------------------------------------------------
# HTML extraction: restrictions and corequisites
#
# Mirrors the find_prereq_text tests above, since _find_labelled_text is the
# same five-strategy search generalised over "prerequisite" / "restriction" /
# "corequisite". The one behavioural difference worth covering explicitly is
# strategy 5 (heading with no colon), since Massey's live "Restrictions"
# section heading has no trailing ":" the way "Prerequisite(s):" does.
# ---------------------------------------------------------------------------

def test_find_prereq_and_restriction_real_massey_structure():
    """
    Regression test using the VERBATIM real HTML structure from Massey's live
    159201 (Algorithms and Data Structures) page, fetched and confirmed via a
    raw-HTML diagnostic in July 2026. This is the actual current site layout,
    not a guess: each section is a <div> containing a
    <div class="course-intro__col-header"> (holding the <h3
    class="course-intro__col-heading"> label plus a
    <div class="course-intro__col-subheading"> sub-label like "Complete
    first"), followed by a SIBLING <div class="rich-text"> holding the real
    course code(s).

    Before Strategy 1 was added for this exact structure, both prerequisites
    and restrictions came back None/[] for this course on the live site, even
    though it has a real prerequisite (159102) and a real restriction
    (159271): the old "heading -> next sibling" strategy landed on the
    sub-heading div ("Complete first"), which has no course code in it, and
    silently returned nothing instead of erroring. This test locks in the fix
    with the real markup, not a simplified approximation of it.
    """
    html = """
    <div class="course-intro course-page-space--std">
      <h2 id="Courseplanninginformation">Course planning information</h2>
      <div class="course-intro__cols">
        <div>
          <div class="course-intro__col-header">
            <h3 class="course-intro__col-heading">Prerequisite courses</h3>
            <div class="course-intro__col-subheading">Complete first</div>
          </div>
          <div class="rich-text">
            <a aria-label="Computer Science and Programming"
               href="/study/courses/computer-science-and-programming-159102/">159102</a>
          </div>
          <p class="course-intro__details">
            You need to complete the above course or courses before moving onto this one.
          </p>
        </div>
        <div>
          <div class="course-intro__col-header">
            <h3 class="course-intro__col-heading">Restrictions</h3>
            <div class="course-intro__col-subheading">Similar content</div>
          </div>
          <div class="rich-text">159271</div>
          <p class="course-intro__details">
            You cannot enrol in this course if you have passed (or are enrolled in)
            any of the course(s) above as these courses have similar content or
            content at a higher level.
          </p>
        </div>
      </div>
      <div>
        <h3>General progression requirements</h3>
        You must complete at least 45 credits from 100-level before enrolling in 200-level courses.
      </div>
    </div>
    """
    soup = BeautifulSoup(html, "html.parser")

    prereq_text = _find_prereq_text(soup)
    assert prereq_text is not None
    assert "159102" in prereq_text

    restriction_text = _find_restriction_text(soup)
    assert restriction_text is not None
    assert "159271" in restriction_text

    # No corequisite section on this page: must return None, not accidentally
    # match "General progression requirements" or anything else on the page.
    assert _find_corequisite_text(soup) is None

    # Full pipeline: parsed prerequisite tree and flat restriction list.
    assert parse_prerequisite_text(prereq_text) == "159102"
    assert parse_code_list_text(restriction_text, header="restriction") == ["159271"]


def test_find_restriction_dt_dd():
    html = """<dl>
        <dt>Restriction(s)</dt><dd>159271</dd>
        <dt>Other</dt><dd>something</dd>

    </dl>"""
    soup = BeautifulSoup(html, "html.parser")
    assert _find_restriction_text(soup) == "159271"


def test_find_restriction_plain_heading_no_colon():
    # Real Massey course pages (post-2024) use a bare "Restrictions" heading
    # with no colon, unlike "Prerequisite(s):". Strategy 4 must catch this.
    html = "<h3>Restrictions</h3><p>Similar content 159271</p>"
    soup = BeautifulSoup(html, "html.parser")
    text = _find_restriction_text(soup)
    assert text is not None
    assert "159271" in text


def test_find_restriction_inline_label():
    html = "<p>Restriction(s): 159271, 159272</p>"
    soup = BeautifulSoup(html, "html.parser")
    text = _find_restriction_text(soup)
    assert text is not None
    assert "159271" in text and "159272" in text


def test_find_restriction_none_when_absent():
    html = "<html><body><h1>Course</h1><p>Description only.</p></body></html>"
    soup = BeautifulSoup(html, "html.parser")
    assert _find_restriction_text(soup) is None


def test_find_restriction_does_not_match_prerequisite_section():
    # A page with only a prerequisite section should not accidentally
    # return that text for a restriction lookup.
    html = "<dt>Prerequisite(s)</dt><dd>159102</dd>"
    soup = BeautifulSoup(html, "html.parser")
    assert _find_restriction_text(soup) is None


def test_find_corequisite_dt_dd():
    html = "<dt>Corequisite(s)</dt><dd>125702</dd>"
    soup = BeautifulSoup(html, "html.parser")
    assert _find_corequisite_text(soup) == "125702"


def test_find_corequisite_none_when_absent():
    html = "<h3>Restrictions</h3><p>159271</p>"
    soup = BeautifulSoup(html, "html.parser")
    assert _find_corequisite_text(soup) is None


# --- parse_code_list_text (restrictions / corequisites) ---

def test_parse_code_list_single():
    assert parse_code_list_text("159271", header="restriction") == ["159271"]


def test_parse_code_list_comma_separated():
    assert parse_code_list_text("159271, 159272", header="restriction") == ["159271", "159272"]


def test_parse_code_list_and_joined():
    assert parse_code_list_text("159271 and 159272", header="restriction") == ["159271", "159272"]


def test_parse_code_list_strips_header():
    assert parse_code_list_text("Restriction(s): 159271", header="restriction") == ["159271"]
    assert parse_code_list_text("Corequisite(s): 125702", header="corequisite") == ["125702"]


def test_parse_code_list_dotted_codes():
    assert parse_code_list_text("159.271, 159.272", header="restriction") == ["159271", "159272"]


def test_parse_code_list_one_of_phrasing():
    # Real Massey wording for a choose-one corequisite. The "One of" prose
    # has no representation in this flat-list schema, so it's dropped and
    # only the codes remain (see parse_code_list_text's docstring).
    result = parse_code_list_text("One of 110380, 125340, 125342", header="corequisite")
    assert result == ["110380", "125340", "125342"]


def test_parse_code_list_dedupes_preserving_order():
    result = parse_code_list_text("159271, 159272, 159271", header="restriction")
    assert result == ["159271", "159272"]


def test_parse_code_list_empty_and_none():
    assert parse_code_list_text("") == []
    assert parse_code_list_text(None) == []


# --- scrape_course_relations (single-fetch combined scraper) ---

_SAMPLE_COURSE_PAGE = """
<html><body>
<dt>Prerequisite(s)</dt><dd>159102</dd>
<dt>Restriction(s)</dt><dd>159271</dd>
</body></html>
"""


def test_scrape_course_relations_success(monkeypatch):
    class _FakeResponse:
        status_code = 200
        text = _SAMPLE_COURSE_PAGE

    def _fake_get(url, timeout=None, headers=None):
        return _FakeResponse()

    monkeypatch.setattr("requests.get", _fake_get)

    result = scrape_course_relations("https://example.invalid/course/159201/")
    assert result == {
        "prerequisites": "159102",
        "restrictions": ["159271"],
        "corequisites": [],
    }


def test_scrape_course_relations_non_200_returns_empty(monkeypatch):
    class _FakeResponse:
        status_code = 403
        text = ""

    monkeypatch.setattr("requests.get", lambda *a, **kw: _FakeResponse())

    result = scrape_course_relations("https://example.invalid/course/blocked/")
    assert result == {"prerequisites": None, "restrictions": [], "corequisites": []}


def test_scrape_course_relations_network_error_returns_empty(monkeypatch):
    def _raise(*a, **kw):
        raise ConnectionError("no network")

    monkeypatch.setattr("requests.get", _raise)

    result = scrape_course_relations("https://example.invalid/course/unreachable/")
    assert result == {"prerequisites": None, "restrictions": [], "corequisites": []}


def test_parse_prerequisite_oxford_comma_before_and_not_dropped():
    """
    Regression test for a silent data-loss bug in tokenize(): a comma
    immediately followed by a literal 'and' (the common Oxford-comma
    phrasing "A, B, C or D, and E") emitted two adjacent 'and' tokens.
    The grammar has no rule for two connectors in a row, so the second
    fell through _parse_factor's "skip unexpected token" fallback as a
    bare None operand, which dataset_loader._build_expr_from_struct then
    silently drops as a child -- deleting a real requirement (E here)
    from the tree instead of raising or warning about it. This made the
    parsed requirement look weaker than the real one, the opposite
    direction of the "one of A, B, C or D" AND-vs-OR bug documented in
    DATA_QUALITY.md, but equally wrong.
    """
    result = parse_prerequisite_text(
        "One of 161122, 297101, 161220 or 233214, and 160101"
    )
    assert result == {
        "op": "AND",
        "args": [
            {"op": "OR", "args": ["161122", "297101", "161220", "233214"]},
            "160101",
        ],
    }


def test_parse_prerequisite_comma_and_without_one_of_clause():
    """Same Oxford-comma bug, without a preceding 'one of' clause to obscure it."""
    result = parse_prerequisite_text("161230 and 161231, and 160101")
    assert result == {
        "op": "AND",
        "args": ["161230", "161231", "160101"],
    }


def test_parse_prerequisite_comma_or_still_works():
    """The same fix must not affect a comma immediately followed by 'or'."""
    result = parse_prerequisite_text("115230, 115231 or 115232")
    assert result == {
        "op": "AND",
        "args": ["115230", {"op": "OR", "args": ["115231", "115232"]}],
    }


def test_parse_prerequisite_plain_comma_list_unaffected():
    """A comma with no following connector word must still mean AND."""
    result = parse_prerequisite_text("115230, 115231")
    assert result == {"op": "AND", "args": ["115230", "115231"]}


def test_parse_prerequisite_one_of_with_parens_live_case():
    """
    Regression test for course 123305's actual live Massey text (verified
    against the real page, not synthesised): "One of (A, B, ...) and one
    of (C, D, ...)". The original _ONE_OF_FLAT_RE deliberately excluded
    any parenthesized list, on the documented assumption that Massey
    always spells out explicit "or"s inside parens - this course's real
    page falsified that assumption, so both parenthesized clauses fell
    through to comma-as-AND, producing AND(AND(...), AND(...)) where the
    second inner AND was four courses (247111-247114) that mutually
    restrict each other - a logical impossibility to satisfy as written.
    """
    result = parse_prerequisite_text(
        "One of (123101, 123102, 123104 , 123105 , 123171, 123172) "
        "and one of ( 247111 , 247112 , 247113 , 247114 )"
    )
    assert result == {
        "op": "AND",
        "args": [
            {"op": "OR", "args": ["123101", "123102", "123104", "123105", "123171", "123172"]},
            {"op": "OR", "args": ["247111", "247112", "247113", "247114"]},
        ],
    }


def test_parse_prerequisite_explicit_or_in_parens_unaffected():
    """The already-correct nested explicit-'or' form must stay unaffected."""
    result = parse_prerequisite_text(
        "(One of (161122 or 161220 or 233214) and one of (160101 or 160102 or 160105))"
    )
    assert result == {
        "op": "AND",
        "args": [
            {"op": "OR", "args": ["161122", "161220", "233214"]},
            {"op": "OR", "args": ["160101", "160102", "160105"]},
        ],
    }


def test_parse_prerequisite_one_of_paren_never_mismatches_unrelated_parens():
    """
    Hardening test: the first version of the parenthesized "one of" fix
    used two independently-optional paren markers, which could in theory
    match an opening paren without its closing pair (or vice versa) if an
    unrelated paren happened to sit near the matched clause, leaving the
    tokenized output with unbalanced parentheses. Replaced with a proper
    alternation (fully-parenthesized clause, or fully-flat clause - never
    a mix) before this could actually manifest in real data, but locking
    it in here since a regex behaving correctly on the one example found
    so far doesn't prove it handles every arrangement.
    """
    result = parse_prerequisite_text("(considering one of 123101, 123102, 123103) other stuff")
    assert result == {"op": "OR", "args": ["123101", "123102", "123103"]}


def test_parse_prerequisite_one_of_paren_with_trailing_or():
    """A real 'or' appearing inside the parens, right before the close, must still work."""
    result = parse_prerequisite_text("One of (123101, 123102 or 123103)")
    assert result == {"op": "OR", "args": ["123101", "123102", "123103"]}


def test_scrape_course_relations_diagnostics_on_success(monkeypatch):
    """include_diagnostics=True must add _status_code/_content_length
    without changing the original three keys' values."""
    class _FakeResponse:
        status_code = 200
        text = _SAMPLE_COURSE_PAGE

    monkeypatch.setattr("requests.get", lambda *a, **kw: _FakeResponse())

    result = scrape_course_relations(
        "https://example.invalid/course/159201/", include_diagnostics=True,
    )
    assert result["prerequisites"] == "159102"
    assert result["restrictions"] == ["159271"]
    assert result["corequisites"] == []
    assert result["_status_code"] == 200
    assert result["_content_length"] == len(_SAMPLE_COURSE_PAGE)


def test_scrape_course_relations_diagnostics_on_non_200(monkeypatch):
    class _FakeResponse:
        status_code = 403
        text = "blocked"

    monkeypatch.setattr("requests.get", lambda *a, **kw: _FakeResponse())

    result = scrape_course_relations(
        "https://example.invalid/course/blocked/", include_diagnostics=True,
    )
    assert result["_status_code"] == 403
    assert result["_content_length"] == len("blocked")


def test_scrape_course_relations_diagnostics_on_exception(monkeypatch):
    def _raise(*a, **kw):
        raise ConnectionError("no network")

    monkeypatch.setattr("requests.get", _raise)

    result = scrape_course_relations(
        "https://example.invalid/course/unreachable/", include_diagnostics=True,
    )
    assert result["_status_code"] is None
    assert result["_content_length"] == 0


def test_scrape_course_relations_default_unaffected_by_diagnostics_feature(monkeypatch):
    """The default (include_diagnostics=False) call must have exactly the
    original three keys - no silent shape change for existing callers."""
    class _FakeResponse:
        status_code = 200
        text = _SAMPLE_COURSE_PAGE

    monkeypatch.setattr("requests.get", lambda *a, **kw: _FakeResponse())

    result = scrape_course_relations("https://example.invalid/course/159201/")
    assert set(result.keys()) == {"prerequisites", "restrictions", "corequisites"}
