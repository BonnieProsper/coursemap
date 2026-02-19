import networkx as nx
from typing import Dict, List

from coursemap.domain.course import Course


class PrerequisiteGraph:
    def __init__(self, courses: Dict[str, Course]):
        """
        courses: dict of course_code -> Course
        """
        self.courses = courses
        self.graph = nx.DiGraph()
        self._build_graph()

    def _build_graph(self):
        for code in self.courses:
            self.graph.add_node(code)

        for code, course in self.courses.items():
            if course.prerequisites:
                for prereq_code in course.prerequisites.required_courses():
                    if prereq_code in self.courses:
                        self.graph.add_edge(prereq_code, code)

        if not nx.is_directed_acyclic_graph(self.graph):
            raise ValueError("Cycle detected in prerequisite graph")

    def topological_order(self) -> List[str]:
        return list(nx.topological_sort(self.graph))

    def prerequisites_of(self, course_code: str) -> List[str]:
        return list(self.graph.predecessors(course_code))
