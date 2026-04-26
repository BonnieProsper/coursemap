from coursemap.domain.course import Course, Offering
from coursemap.domain.prerequisite import CoursePrerequisite
from coursemap.planner.generator import PlanGenerator


def _offering(semesters):
    return tuple(Offering(semester=s, campus="D", mode="DIS") for s in semesters)


def _fixture_courses():
    """Minimal course catalog for scheduler tests.

    Three prerequisite chains across two levels:
      STAT101 -> STAT102 -> STAT201 -> STAT301
      MATH101 -> MATH201
      COMP101 -> COMP201
    All 100-level offered S1+S2; 200-level S1; 300-level S2.
    Total: 8 courses x 15 credits = 120 credits.
    """
    prereq = CoursePrerequisite
    off    = _offering
    return {
        "STAT101": Course("STAT101", "Statistics I",        15, 100, off(["S1", "S2"])),
        "STAT102": Course("STAT102", "Statistics II",       15, 100, off(["S1", "S2"]),
                          prereq("STAT101")),
        "MATH101": Course("MATH101", "Calculus I",          15, 100, off(["S1", "S2"])),
        "COMP101": Course("COMP101", "Programming I",       15, 100, off(["S1", "S2"])),
        "STAT201": Course("STAT201", "Stat Modelling",      15, 200, off(["S1"]),
                          prereq("STAT102")),
        "MATH201": Course("MATH201", "Linear Algebra",      15, 200, off(["S1"]),
                          prereq("MATH101")),
        "COMP201": Course("COMP201", "Data Structures",     15, 200, off(["S1"]),
                          prereq("COMP101")),
        "STAT301": Course("STAT301", "Advanced Regression", 15, 300, off(["S2"]),
                          prereq("STAT201")),
    }


def test_plan_generation():
    courses = _fixture_courses()

    generator = PlanGenerator(
        courses,
        max_credits_per_semester=60,
        start_year=2026,
    )

    plan = generator.generate()

    total_courses = sum(len(s.courses) for s in plan.semesters)

    assert total_courses == len(courses)

    # STAT101 must come before STAT102
    semester_lookup = {}
    for i, sem in enumerate(plan.semesters):
        for c in sem.courses:
            semester_lookup[c.code] = i

    assert semester_lookup["STAT101"] < semester_lookup["STAT102"]
    assert semester_lookup["STAT201"] < semester_lookup["STAT301"]
