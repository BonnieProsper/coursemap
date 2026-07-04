"""
Tests for PlanSearch: elective selection and plan scoring.

Each major dict passed to PlanSearch must include a 'degree_tree' field
containing the full validation tree, in addition to the 'requirement' field
for the major-specific courses.
"""

from coursemap.domain.course import Course, Offering
from coursemap.domain.prerequisite import CoursePrerequisite
from coursemap.domain.requirement_nodes import AllOfRequirement, TotalCreditsRequirement
from coursemap.domain.requirement_serialization import requirement_from_dict
from coursemap.planner.generator import PlanGenerator
from coursemap.optimisation.search import PlanSearch


def _offering(semesters):
    return tuple(Offering(semester=s, campus="D", mode="DIS") for s in semesters)


def _fixture_courses():
    prereq = CoursePrerequisite
    off    = _offering
    return {
        "STAT101": Course("STAT101", "Statistics I",    15, 100, off(["S1", "S2"])),
        "MATH101": Course("MATH101", "Calculus I",      15, 100, off(["S1", "S2"])),
        "COMP101": Course("COMP101", "Programming I",   15, 100, off(["S1", "S2"])),
        "PHYS101": Course("PHYS101", "Physics I",       15, 100, off(["S1", "S2"])),
        "STAT201": Course("STAT201", "Stat Modelling",  15, 200, off(["S1"]), prereq("STAT101")),
        "STAT202": Course("STAT202", "Probability",     15, 200, off(["S1"]), prereq("STAT101")),
        "MATH201": Course("MATH201", "Linear Algebra",  15, 200, off(["S1"]), prereq("MATH101")),
        "COMP201": Course("COMP201", "Data Structures", 15, 200, off(["S1"]), prereq("COMP101")),
    }


def _make_major(name, requirement_dict, total_credits):
    """Build a major dict in the format PlanSearch expects."""
    req = requirement_from_dict(requirement_dict)
    degree_tree = AllOfRequirement((
        TotalCreditsRequirement(total_credits),
        req,
    ))
    return {
        "name":        name,
        "url":         "",
        "requirement": req,
        "degree_tree": degree_tree,
    }


def test_search_returns_valid_plan():
    courses = _fixture_courses()
    total   = sum(c.credits for c in courses.values())

    major = _make_major(
        "Default",
        {"type": "ALL_OF", "children": [
            {"type": "COURSE", "course_code": code}
            for code in sorted(courses.keys())
        ]},
        total,
    )

    search = PlanSearch(courses, [major], PlanGenerator(courses))
    plan   = search.search()

    assert plan is not None
    assert len(plan.semesters) > 0


def test_search_with_elective_pools():
    courses      = _fixture_courses()
    total_credits = 90  # 3 required + choose 45cr from pools

    major = _make_major(
        "Default",
        {"type": "ALL_OF", "children": [
            {"type": "COURSE", "course_code": "MATH101"},
            {"type": "COURSE", "course_code": "STAT101"},
            {"type": "COURSE", "course_code": "COMP101"},
            {
                "type": "CHOOSE_CREDITS",
                "credits": 30,
                "course_codes": ["STAT201", "STAT202", "PHYS101"],
            },
            {
                "type": "CHOOSE_CREDITS",
                "credits": 15,
                "course_codes": ["MATH201", "COMP201"],
            },
        ]},
        total_credits,
    )

    search = PlanSearch(courses, [major], PlanGenerator(courses))
    plan   = search.search()

    assert plan is not None
    planned = sum(c.credits for s in plan.semesters for c in s.courses)
    assert planned == total_credits


def test_cap_required_codes_never_drops_tree_required():
    """
    _cap_required_codes must never drop a code the degree tree checks as
    required, even when the major's required-course list over-captures
    (more required credits than the degree target allows).
    """
    from coursemap.domain.requirement_nodes import CourseRequirement

    courses = _fixture_courses()
    # 4 "required" courses (60cr) for a 30cr degree target. Clear over-capture.
    required_codes = {"STAT101", "MATH101", "COMP101", "PHYS101"}
    degree_tree = AllOfRequirement((
        TotalCreditsRequirement(30),
        AllOfRequirement((CourseRequirement("STAT101"), CourseRequirement("MATH101"))),
    ))
    search = PlanSearch(courses, [], PlanGenerator(courses))
    kept, was_capped = search._cap_required_codes(
        required_codes, elective_nodes=[], degree_tree=degree_tree,
        degree_total=30, campus="D", mode="DIS",
    )
    assert was_capped is True
    assert {"STAT101", "MATH101"} <= kept, (
        "Codes the degree tree checks as required must never be dropped"
    )


def test_cap_required_codes_accounts_for_prerequisite_chain_cost():
    """
    When a kept (tree_required) course's prerequisite isn't itself
    independently required, _cap_required_codes must reserve that chain
    cost in its budget accounting, otherwise the chain course gets added
    later by working-set construction without ever having been counted
    against the cap, silently eating into whatever budget was left for
    electives.

    STAT201 (15cr) requires STAT101 (15cr, not independently required).
    true cost of keeping STAT201 is 30cr. A degree_total of 20cr is enough
    for STAT201 alone but NOT enough once its chain cost is counted, so a
    droppable elective candidate must be cut to make room.
    """
    from coursemap.domain.requirement_nodes import CourseRequirement

    courses = _fixture_courses()
    required_codes = {"STAT201", "PHYS101"}  # PHYS101 is droppable (not tree_required)
    degree_tree = AllOfRequirement((
        TotalCreditsRequirement(20),
        CourseRequirement("STAT201"),
    ))
    search = PlanSearch(courses, [], PlanGenerator(courses))
    kept, was_capped = search._cap_required_codes(
        required_codes, elective_nodes=[], degree_tree=degree_tree,
        degree_total=20, campus="D", mode="DIS",
    )
    assert was_capped is True
    assert "STAT201" in kept, "tree_required course must be kept"
    assert "PHYS101" not in kept, (
        "Droppable candidate should be cut once STAT201's real cost "
        "(15cr course + 15cr chain = 30cr) is counted against the 20cr budget. "
        "if PHYS101 survives, the chain cost isn't being reserved correctly"
    )
