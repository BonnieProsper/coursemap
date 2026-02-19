from coursemap.domain.course import Course, Offering


def test_course_offering_match():
    offering = Offering(
        year=2026,
        semester="S1",
        campus="PN",
        mode="internal",
    )

    course = Course(
        code="STAT101",
        title="Intro Stats",
        credits=15,
        level=100,
        offerings=[offering],
    )

    assert course.is_offered(2026, "S1", "PN", "internal")
    assert not course.is_offered(2026, "S2", "PN", "internal")
