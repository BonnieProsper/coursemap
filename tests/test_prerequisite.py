from coursemap.domain.prerequisite import (
    CourseRequirement,
    AndExpression,
    OrExpression,
)


def test_single_course_requirement():
    expr = CourseRequirement("STAT101")

    assert expr.is_satisfied({"STAT101"})
    assert not expr.is_satisfied({"MATH101"})


def test_and_expression():
    expr = AndExpression([
        CourseRequirement("STAT101"),
        CourseRequirement("MATH101"),
    ])

    assert expr.is_satisfied({"STAT101", "MATH101"})
    assert not expr.is_satisfied({"STAT101"})
    assert not expr.is_satisfied({"MATH101"})


def test_or_expression():
    expr = OrExpression([
        CourseRequirement("STAT101"),
        CourseRequirement("MATH101"),
    ])

    assert expr.is_satisfied({"STAT101"})
    assert expr.is_satisfied({"MATH101"})
    assert not expr.is_satisfied({"COMP101"})


def test_nested_expression():
    expr = AndExpression([
        CourseRequirement("STAT101"),
        OrExpression([
            CourseRequirement("MATH101"),
            CourseRequirement("MATH102"),
        ])
    ])

    assert expr.is_satisfied({"STAT101", "MATH101"})
    assert expr.is_satisfied({"STAT101", "MATH102"})
    assert not expr.is_satisfied({"STAT101"})
    assert not expr.is_satisfied({"MATH101"})
