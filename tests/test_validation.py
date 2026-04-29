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
