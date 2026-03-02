from coursemap.domain.plan import DegreePlan
from coursemap.planner.generator import PlanGenerator
from coursemap.optimisation.search import ExhaustivePlanSearch
from coursemap.optimisation.scorer import PlanScorer


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
    ):

        generator_template = PlanGenerator(
            self.courses,
            max_credits_per_semester=max_credits_per_semester,
            campus=campus,
            mode=mode,
            start_year=start_year,
        )

        search = ExhaustivePlanSearch(
            courses=self.courses,
            requirements=self.requirements,
            generator_template=generator_template,
        )

        return search.search()