from coursemap.domain.course import Course, Offering


def test_course_offering_match():
    offering = Offering(
        semester="S1",
        campus="M",
        mode="INT",
    )

    course = Course(
        code="STAT101",
        title="Intro Stats",
        credits=15,
        level=100,
        offerings=(offering,),
    )

    assert course.is_offered("S1", "M", "INT")
    assert not course.is_offered("S2", "M", "INT")


def test_sort_semesters_calendar_order():
    """sort_semesters must order S1, S2, SS chronologically."""
    from coursemap.domain.course import sort_semesters
    assert sort_semesters(["SS", "S2", "S1"]) == ["S1", "S2", "SS"]
    assert sort_semesters(["S2", "S1"]) == ["S1", "S2"]
    assert sort_semesters(["S1"]) == ["S1"]
    assert sort_semesters([]) == []


def test_sort_semesters_deduplicates():
    """sort_semesters should deduplicate repeated semester codes."""
    from coursemap.domain.course import sort_semesters
    assert sort_semesters(["S1", "S1", "S2"]) == ["S1", "S2"]


def test_sort_semesters_unknown_code_sorts_last():
    """
    An unrecognized semester code must sort after all known ones, not
    crash and not silently land in an arbitrary position. This is the
    actual robustness this helper provides over plain alphabetical sort:
    a real alphabetical sort places an unrecognized code wherever its
    characters happen to fall, e.g. a hypothetical 'B2' code (for some
    future block-course offering occurring mid-year) would sort BEFORE
    'S1' and 'S2' alphabetically (since 'B' < 'S'), even though nothing
    about that code's letters says anything about when it actually falls
    in the calendar. An explicit ordering map doesn't have that problem;
    it puts genuinely unknown codes last rather than guessing from spelling.
    """
    from coursemap.domain.course import sort_semesters
    result = sort_semesters(["S2", "B2", "S1"])
    assert result == ["S1", "S2", "B2"], (
        f"Unknown code 'B2' should sort after the known S1/S2 codes, got {result}"
    )
