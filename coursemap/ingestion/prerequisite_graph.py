from collections import defaultdict


class CourseGraph:

    def __init__(self):

        self.graph = defaultdict(list)

    def add_prereq(self, course, prereq):

        self.graph[prereq].append(course)

    def build(self, courses):

        for c in courses:

            code = c["course_code"]

            for p in c.get("prerequisites", []):

                self.add_prereq(code, p)

    def successors(self, course):

        return self.graph.get(course, [])