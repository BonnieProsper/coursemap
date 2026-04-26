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
# ---------------------------------------------------------------------------

from coursemap.domain.prerequisite import CoursePrerequisite
from coursemap.domain.prerequisite_utils import prereqs_met
from coursemap.ingestion.dataset_loader import parse_prereqs as _parse_prereqs
from coursemap.ingestion.prerequisite_scraper import (
    parse_prerequisite_text,
    tokenize as _tokenize,
    find_prereq_text as _find_prereq_text,
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
