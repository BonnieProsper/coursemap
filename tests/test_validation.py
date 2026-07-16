from coursemap.domain.course import Course, Offering
from coursemap.domain.prerequisite import CoursePrerequisite
from coursemap.domain.requirement_serialization import requirement_from_dict
from coursemap.planner.generator import PlanGenerator
from coursemap.validation.engine import DegreeValidator


def _offering(semesters):
    return tuple(Offering(semester=s, campus="D", mode="DIS") for s in semesters)


def _fixture_courses():
    """Three levels of courses for validation tests.

    4 x 100-level (60 cr) + 5 x 200-level (75 cr) + 5 x 300-level (75 cr)
    = 14 courses, 210 credits total.
    Each 200/300-level course has a prerequisite to exercise the scheduler.
    """
    prereq = CoursePrerequisite
    off = _offering
    return {
        "STAT101": Course("STAT101", "Statistics I",     15, 100, off(["S1", "S2"])),
        "MATH101": Course("MATH101", "Calculus I",       15, 100, off(["S1", "S2"])),
        "COMP101": Course("COMP101", "Programming I",    15, 100, off(["S1", "S2"])),
        "PHYS101": Course("PHYS101", "Physics I",        15, 100, off(["S1", "S2"])),
        "STAT201": Course("STAT201", "Stat Modelling",   15, 200, off(["S1"]), prereq("STAT101")),
        "STAT202": Course("STAT202", "Probability",      15, 200, off(["S1"]), prereq("STAT101")),
        "COMP201": Course("COMP201", "Data Structures",  15, 200, off(["S1"]), prereq("COMP101")),
        "PHYS201": Course("PHYS201", "Mechanics II",     15, 200, off(["S1"]), prereq("PHYS101")),
        "MATH201": Course("MATH201", "Linear Algebra",   15, 200, off(["S1"]), prereq("MATH101")),
        "STAT301": Course("STAT301", "Adv Regression",   15, 300, off(["S2"]), prereq("STAT201")),
        "STAT302": Course("STAT302", "Bayesian Stats",   15, 300, off(["S2"]), prereq("STAT202")),
        "COMP301": Course("COMP301", "Algorithms",       15, 300, off(["S2"]), prereq("COMP201")),
        "PHYS301": Course("PHYS301", "Quantum Intro",    15, 300, off(["S2"]), prereq("PHYS201")),
        "MATH301": Course("MATH301", "Abstract Algebra", 15, 300, off(["S2"]), prereq("MATH201")),
    }


def test_degree_validation_passes():
    courses = _fixture_courses()

    generator = PlanGenerator(courses)
    plan = generator.generate()

    # ALL_OF: total credits >= 210, at least 60cr at 100-level,
    # at least 75cr at 200-level, at least 75cr at 300-level,
    # and every course in the fixture must appear.
    degree_requirement = requirement_from_dict({
        "type": "ALL_OF",
        "children": [
            {"type": "TOTAL_CREDITS", "required_credits": 210},
            {"type": "MIN_LEVEL_CREDITS", "level": 100, "min_credits": 60},
            {"type": "MIN_LEVEL_CREDITS", "level": 200, "min_credits": 75},
            {"type": "MIN_LEVEL_CREDITS", "level": 300, "min_credits": 75},
            *[{"type": "COURSE", "course_code": code} for code in courses],
        ],
    })

    validator = DegreeValidator(degree_requirement)
    result = validator.validate(plan)
    assert result.passed, f"Expected plan to pass; errors: {result.errors}"


def test_degree_validation_fails_on_wrong_total():
    courses = _fixture_courses()

    generator = PlanGenerator(courses)
    plan = generator.generate()

    # Require far more credits than the plan contains; must fail.
    degree_requirement = requirement_from_dict({
        "type": "ALL_OF",
        "children": [
            {"type": "TOTAL_CREDITS", "required_credits": 999},
        ],
    })

    validator = DegreeValidator(degree_requirement)
    result = validator.validate(plan)
    assert not result.passed
    assert any("below required" in e or "999" in e for e in result.errors)


def test_degree_validation_fails_on_restriction_conflict():
    """
    DegreeValidator must catch two plan courses that mutually restrict
    each other, even when every requirement node in the tree is
    individually satisfied. A plan requiring two courses a student could
    never actually both be enrolled in isn't a valid plan, regardless of
    whether the credit/course-presence bookkeeping looks complete.

    Found via a real bug: _select_electives' top-up pass (optimisation/
    search.py) could add a restriction-conflicting alternative of an
    already-satisfied pool to spend leftover budget, and nothing in the
    validation pipeline caught it - the plan "passed" by every check that
    existed at the time. Extending this test's fixture with a genuine
    mutual restriction and confirming DegreeValidator now catches it
    directly (independent of the scheduler bug that originally exposed
    the gap) is what makes this a real regression test rather than one
    that only happens to pass because the originating bug got fixed
    elsewhere.
    """
    from coursemap.domain.plan import DegreePlan, SemesterPlan

    courses = _fixture_courses()
    # Two courses that mutually restrict each other, unrelated to any
    # prerequisite chain, so this isolates the restriction check itself.
    courses["MATH101"] = Course(
        "MATH101", "Calculus I", 15, 100, _offering(["S1", "S2"]),
        restrictions=frozenset({"MATH102"}),
    )
    courses["MATH102"] = Course(
        "MATH102", "Algebra I", 15, 100, _offering(["S1", "S2"]),
        restrictions=frozenset({"MATH101"}),
    )

    plan = DegreePlan(
        semesters=(
            SemesterPlan(year=2026, semester="S1", courses=(courses["MATH101"], courses["MATH102"])),
        ),
    )

    degree_requirement = requirement_from_dict({
        "type": "ALL_OF",
        "children": [{"type": "TOTAL_CREDITS", "required_credits": 30}],
    })

    validator = DegreeValidator(degree_requirement)
    result = validator.validate(plan)

    assert not result.passed
    assert any("MATH101" in e and "MATH102" in e and "restrict" in e for e in result.errors)


def test_degree_validation_restriction_conflict_reported_once_per_pair():
    """A-restricts-B and B-restricts-A (the normal symmetric case) must
    produce one error, not two, for the same pair."""
    from coursemap.domain.plan import DegreePlan, SemesterPlan

    courses = _fixture_courses()
    courses["MATH101"] = Course(
        "MATH101", "Calculus I", 15, 100, _offering(["S1", "S2"]),
        restrictions=frozenset({"MATH102"}),
    )
    courses["MATH102"] = Course(
        "MATH102", "Algebra I", 15, 100, _offering(["S1", "S2"]),
        restrictions=frozenset({"MATH101"}),
    )

    plan = DegreePlan(
        semesters=(
            SemesterPlan(year=2026, semester="S1", courses=(courses["MATH101"], courses["MATH102"])),
        ),
    )

    degree_requirement = requirement_from_dict({
        "type": "ALL_OF",
        "children": [{"type": "TOTAL_CREDITS", "required_credits": 30}],
    })

    validator = DegreeValidator(degree_requirement)
    result = validator.validate(plan)

    conflict_errors = [e for e in result.errors if "restrict" in e]
    assert len(conflict_errors) == 1, f"Expected exactly 1 conflict error, got {len(conflict_errors)}: {conflict_errors}"


def test_degree_validation_no_false_positive_on_unrelated_restrictions():
    """A course restricting something NOT in the plan must not trigger a
    false-positive conflict error."""
    from coursemap.domain.plan import DegreePlan, SemesterPlan

    courses = _fixture_courses()
    courses["MATH101"] = Course(
        "MATH101", "Calculus I", 15, 100, _offering(["S1", "S2"]),
        restrictions=frozenset({"SOME_COURSE_NOT_IN_PLAN"}),
    )

    plan = DegreePlan(
        semesters=(
            SemesterPlan(year=2026, semester="S1", courses=(courses["MATH101"], courses["STAT101"])),
        ),
    )

    degree_requirement = requirement_from_dict({
        "type": "ALL_OF",
        "children": [{"type": "TOTAL_CREDITS", "required_credits": 30}],
    })

    validator = DegreeValidator(degree_requirement)
    result = validator.validate(plan)

    assert result.passed
    assert not result.errors
