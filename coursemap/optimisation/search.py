from itertools import combinations
from typing import Dict, List, Optional

from coursemap.domain.course import Course
from coursemap.domain.degree_requirements import DegreeRequirements
from coursemap.domain.plan import DegreePlan
from coursemap.planner.generator import PlanGenerator
from coursemap.validation.engine import DegreeValidator
from coursemap.validation.rules import (
    TotalCreditRule,
    LevelCreditRule,
    CoreCourseRule,
    ElectivePoolRule,
    Max100LevelRule,
    Min300LevelRule,
    MajorCompletionRule,
)
from coursemap.optimisation.scorer import PlanScorer

class ExhaustivePlanSearch:
    """
    Exhaustively evaluates all valid elective combinations.
    Deterministic and exact.
    """

    def __init__(
        self,
        courses: Dict[str, Course],
        requirements: DegreeRequirements,
        generator_template: PlanGenerator,
    ):
        self.courses = courses
        self.requirements = requirements
        self.generator_template = generator_template

    def search(self) -> DegreePlan:
        best_plan: Optional[DegreePlan] = None
        best_score: Optional[float] = None

        elective_combinations = self._generate_elective_combinations()

        for elective_set in elective_combinations:
            selected_courses = self._build_course_subset(elective_set)

            generator = PlanGenerator(
                selected_courses,
                max_credits_per_semester=self.generator_template.max_credits,
                campus=self.generator_template.campus,
                mode=self.generator_template.mode,
                start_year=self.generator_template.start_year,
            )

            try:
                plan = generator.generate()
                self._validate(plan)
            except Exception:
                continue

            score = self._score(plan)

            if best_score is None or score < best_score:
                best_plan = plan
                best_score = score

        if best_plan is None:
            raise ValueError("No valid plan found.")

        return best_plan

    def _generate_elective_combinations(self) -> List[List[str]]:
        """
        For each elective pool, generate combinations that satisfy minimum credits.
        """

        if not self.requirements.elective_pools:
            return [[]]

        all_pool_selections: List[List[List[str]]] = []

        for pool in self.requirements.elective_pools:
            pool_courses = list(pool.course_codes)
            valid_combos: List[List[str]] = []

            for r in range(1, len(pool_courses) + 1):
                for combo in combinations(pool_courses, r):
                    credits = sum(self.courses[c].credits for c in combo)
                    if credits >= pool.min_credits:
                        valid_combos.append(list(combo))

            all_pool_selections.append(valid_combos)

        # Cartesian product across pools
        results: List[List[str]] = [[]]

        for pool_combos in all_pool_selections:
            new_results: List[List[str]] = []
            for partial in results:
                for combo in pool_combos:
                    new_results.append(partial + combo)
            results = new_results

        return results

    def _build_course_subset(self, electives: List[str]) -> Dict[str, Course]:
        selected: Dict[str, Course] = {}

        # Core courses
        for code in self.requirements.core_courses:
            selected[code] = self.courses[code]

        # Major required courses (we assume first major for now)
        if self.requirements.available_majors:
            major = self.requirements.available_majors[0]
            for code in major.required_courses:
                selected[code] = self.courses[code]

        # Electives
        for code in electives:
            selected[code] = self.courses[code]

        return selected


    def _validate(self, plan: DegreePlan) -> None:
        rules = [
            TotalCreditRule(self.requirements),
            LevelCreditRule(self.requirements),
            CoreCourseRule(self.requirements.core_courses),
            Max100LevelRule(self.requirements),
            Min300LevelRule(self.requirements),
            MajorCompletionRule(self.requirements),
        ]

        for pool in self.requirements.elective_pools:
            rules.append(ElectivePoolRule(pool))

        validator = DegreeValidator(rules)
        validator.validate(plan)

    def _score(self, plan: DegreePlan) -> float:
        scorer = PlanScorer()
        return scorer.score(plan)