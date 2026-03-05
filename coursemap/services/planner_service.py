from dataclasses import replace

from coursemap.planner.generator import PlanGenerator
from coursemap.optimisation.search import ExhaustivePlanSearch


class PlannerService:

    def __init__(self, courses, requirements):
        self.courses = courses
        self.requirements = requirements

    def generate_best_plan(
        self,
        max_credits_per_semester: int = 60,
        campus: str = "PN",
        mode: str = "internal",
        start_year: int = 2026,
        major_name: str | None = None,
    ):
        requirements = self._requirements_for_major(major_name)
        self.requirements = requirements

        generator_template = PlanGenerator(
            self.courses,
            max_credits_per_semester=max_credits_per_semester,
            campus=campus,
            mode=mode,
            start_year=start_year,
        )

        search = ExhaustivePlanSearch(
            courses=self.courses,
            requirements=requirements,
            generator_template=generator_template,
        )

        return search.search()

    def _requirements_for_major(self, major_name: str | None):
        if not major_name:
            return self.requirements

        selected = [
            major
            for major in self.requirements.available_majors
            if major.name.lower() == major_name.lower()
        ]

        if not selected:
            available = ", ".join(m.name for m in self.requirements.available_majors)
            raise ValueError(
                f"Unknown major '{major_name}'. Available majors: {available}"
            )

        return replace(
            self.requirements,
            available_majors=selected,
        )
