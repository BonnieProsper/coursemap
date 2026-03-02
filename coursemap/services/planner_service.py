from coursemap.domain.plan import DegreePlan
from coursemap.planner.generator import PlanGenerator
from coursemap.optimisation.search import ExhaustivePlanSearch
from coursemap.optimisation.scorer import PlanScorer


class PlannerService:

    def __init__(self, courses, requirements):
        self.courses = courses
        self.requirements = requirements

    def generate_best_plan(self) -> DegreePlan:

        generator_template = PlanGenerator(
            self.courses,
            max_credits_per_semester=60,
            campus="PN",
            mode="internal",
            start_year=2026,
        )

        search = ExhaustivePlanSearch(
            courses=self.courses,
            requirements=self.requirements,
            generator_template=generator_template,
        )

        best_plan = search.search()

        return best_plan