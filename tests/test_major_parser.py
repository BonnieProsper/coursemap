"""
Tests for major_parser.py.

Coverage here focuses on the prose-choice-detection fix: a "Planning information"
bullet can express a choice in plain English ("one or more of X, Y, Z",
"one of X or Y") rather than Massey's structured .course-schedules
"Choose N credits" widget, and the parser previously had no way to
recognise that - it extracted the bullet's first linked course code (or,
for a genuinely multi-code bullet, would have silently required every
linked code) regardless of the prose actually saying "pick one of
these". Found live, on course "Computer Science - Bachelor of
Information Sciences": see DATA_QUALITY.md for the confirmed page text
this was diagnosed against.
"""
from coursemap.ingestion.major_parser import parse_major_page


def _planning_page(li_items: str) -> str:
    return f"""
    <html><body>
    <details>
    <summary>Planning information</summary>
    <ul>
    {li_items}
    </ul>
    </details>
    </body></html>
    """


def test_plain_single_code_bullet_unaffected():
    """A bullet with no choice language must produce a flat required course as the overwhelmingly common case."""
    html = _planning_page(
        '<li><a href="/study/courses/159101/">159101</a> Applied Programming</li>'
    )
    tree = parse_major_page(html)
    assert tree == {
        "type": "ALL_OF",
        "children": [{"type": "COURSE", "course_code": "159101"}],
    }


def test_one_or_more_of_prose_choice_becomes_pool():
    """
    Live-verified text (Computer Science - Bachelor of Information
    Sciences): "At least one mathematics course - one or more of
    160105, 160101, 160102. Note: you can also take 160104 as an
    elective in your degree before you decide."

    Must become a single CHOOSE_CREDITS pool of exactly the three codes
    in the choice clause - critically, NOT the required-courses list
    (which would make the major impossible, since these three mutually
    restrict each other), and NOT including 160104, which the text
    explicitly frames as a separate optional aside, not part of the choice.
    """
    html = _planning_page("""
        <li>At least one mathematics course &ndash; one or more of
            <a href="/study/courses/160105/">160105</a> ,
            <a href="/study/courses/160101/">160101</a> ,
            <a href="/study/courses/160102/">160102</a> .
            Note: you can also take <a href="/study/courses/160104/">160104</a>
            as an elective in your degree before you decide.</li>
    """)
    tree = parse_major_page(html)
    assert tree == {
        "type": "ALL_OF",
        "children": [
            {"type": "CHOOSE_CREDITS", "credits": 15, "course_codes": ["160105", "160101", "160102"]},
        ],
    }


def test_one_of_or_prose_choice_becomes_pool():
    """
    Live-verified text (same course): "At least one statistics course -
    one of 161111 or 297101. Note: 297101 is more relevant to computing
    majors."
    """
    html = _planning_page("""
        <li>At least one statistics course &ndash; one of
            <a href="/study/courses/161111/">161111</a> or
            <a href="/study/courses/297101/">297101</a> .
            Note: 297101 is more relevant to computing majors</li>
    """)
    tree = parse_major_page(html)
    assert tree == {
        "type": "ALL_OF",
        "children": [
            {"type": "CHOOSE_CREDITS", "credits": 15, "course_codes": ["161111", "297101"]},
        ],
    }


def test_mixed_plain_and_choice_bullets_full_page():
    """
    The full confirmed live scenario: two plain required-course bullets
    followed by two prose-choice bullets in the same Planning information
    block. Plain bullets stay flat required courses; choice bullets
    become separate CHOOSE_CREDITS pools; codes that end up in a pool are
    correctly excluded from the required-courses list even though they
    were also linked directly.
    """
    html = _planning_page("""
        <li><a href="/study/courses/159101/">159101</a> Applied Programming</li>
        <li><a href="/study/courses/159102/">159102</a> Computer Science and Programming</li>
        <li>At least one mathematics course &ndash; one or more of
            <a href="/study/courses/160105/">160105</a> ,
            <a href="/study/courses/160101/">160101</a> ,
            <a href="/study/courses/160102/">160102</a> .
            Note: you can also take <a href="/study/courses/160104/">160104</a>
            as an elective in your degree before you decide.</li>
        <li>At least one statistics course &ndash; one of
            <a href="/study/courses/161111/">161111</a> or
            <a href="/study/courses/297101/">297101</a> .
            Note: 297101 is more relevant to computing majors</li>
    """)
    tree = parse_major_page(html)
    assert tree == {
        "type": "ALL_OF",
        "children": [
            {"type": "COURSE", "course_code": "159101"},
            {"type": "COURSE", "course_code": "159102"},
            {"type": "CHOOSE_CREDITS", "credits": 15, "course_codes": ["160105", "160101", "160102"]},
            {"type": "CHOOSE_CREDITS", "credits": 15, "course_codes": ["161111", "297101"]},
        ],
    }


def test_course_schedules_choose_block_still_takes_priority():
    """A .course-schedules 'Choose N credits' widget (Step 2) must keep
    working exactly as before - this fix only touches Planning information
    prose bullets (Step 1), a completely separate code path."""
    html = """
    <html><body>
    <div class="course-schedules">
      <div class="course-schedules__header-credit-summary">Choose 60 credits from</div>
      <span class="course-schedules__summary-code">Course code:159201</span>
      <span class="course-schedules__summary-code">Course code:159234</span>
    </div>
    </body></html>
    """
    tree = parse_major_page(html)
    assert tree == {
        "type": "ALL_OF",
        "children": [
            {"type": "CHOOSE_CREDITS", "credits": 60, "course_codes": ["Course code:159201", "Course code:159234"]},
        ],
    }
