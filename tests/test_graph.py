from coursemap.domain.course import Course
from coursemap.domain.prerequisite import CourseRequirement
from coursemap.planner.graph import PrerequisiteGraph


def test_simple_graph_order():
    c1 = Course("A", "A", 15, 100, [], None)
    c2 = Course("B", "B", 15, 200, [], CourseRequirement("A"))

    courses = {
        "A": c1,
        "B": c2,
    }

    graph = PrerequisiteGraph(courses)
    order = graph.topological_order()

    assert order.index("A") < order.index("B")


def test_cycle_detection():
    c1 = Course("A", "A", 15, 100, [], CourseRequirement("B"))
    c2 = Course("B", "B", 15, 200, [], CourseRequirement("A"))

    courses = {
        "A": c1,
        "B": c2,
    }

    try:
        PrerequisiteGraph(courses)
        assert False
    except ValueError:
        assert True
