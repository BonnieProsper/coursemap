from coursemap.domain.requirement_nodes import RequirementNode
from coursemap.planner.generator import PlanGenerator
from coursemap.optimisation.search import ExhaustivePlanSearch


class PlannerService:
    """Orchestrates plan generation. Uses degree requirement tree and majors from datasets."""

    def __init__(self, courses, degree_requirement: RequirementNode, majors: list):
        self.courses = courses
        self.degree_requirement = degree_requirement
        self.majors = majors

    def generate_best_plan(
        self,
        max_credits_per_semester: int = 60,
        campus: str = "D",
        mode: str = "internal",
        start_year: int = 2026,
        major_name: str | None = None,
    ):
        majors_to_use = self._majors_for_name(major_name)

        generator_template = PlanGenerator(
            self.courses,
            max_credits_per_semester=max_credits_per_semester,
            campus=campus,
            mode=mode,
            start_year=start_year,
        )

        search = ExhaustivePlanSearch(
            courses=self.courses,
            degree_requirement=self.degree_requirement,
            majors=majors_to_use,
            generator_template=generator_template,
        )

        return search.search()

    def _majors_for_name(self, major_name: str | None) -> list:
        if not major_name:
            return self.majors

        selected = [
            m for m in self.majors
            if m["name"].lower() == major_name.lower()
        ]

        if not selected:
            available = ", ".join(m["name"] for m in self.majors)
            raise ValueError(
                f"Unknown major '{major_name}'. Available majors: {available}"
            )

        return selected
