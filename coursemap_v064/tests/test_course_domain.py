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
