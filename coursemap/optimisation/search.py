from itertools import combinations
from typing import Dict, List, Optional
from collections import defaultdict

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
    AllowedCourseRule,
)
from coursemap.optimisation.scorer import PlanScorer


class ExhaustivePlanSearch:
    """
    Exhaustively evaluates all valid elective combinations.
    Deterministic and exact.
    Now with diagnostics and search statistics.
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

        # Diagnostics
        self.total_attempts = 0
        self.generation_failures = 0
        self.validation_failures = 0
        self.failure_breakdown = defaultdict(int)

    def search(self) -> DegreePlan:
        best_plan: Optional[DegreePlan] = None
        best_score: Optional[float] = None

        elective_combinations = self._generate_elective_combinations()

        print(f"Total elective combinations to evaluate: {len(elective_combinations)}")

        for elective_set in elective_combinations:
            self.total_attempts += 1

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
            except Exception:
                self.generation_failures += 1
                continue

            validation_result = self._validate(plan)

            if not validation_result.passed:
                self.validation_failures += 1
                for error in validation_result.errors:
                    self.failure_breakdown[error] += 1
                continue

            score = self._score(plan)

            if best_score is None or score < best_score:
                best_plan = plan
                best_score = score

        self._print_diagnostics()

        if best_plan is None:
            raise ValueError("No valid plan found.")

        return best_plan

    def _generate_elective_combinations(self) -> List[List[str]]:
        if not self.requirements.elective_pools:
            return [[]]

        all_pool_selections: List[List[List[str]]] = []

        for pool in self.requirements.elective_pools:
            pool_courses = list(pool.course_codes)
            valid_combos: List[List[str]] = []

            for r in range(1, len(pool_courses) + 1):
                for combo in combinations(pool_courses, r):
                    credits = sum(self.courses[c].credits for c in combo)

                    if credits < pool.min_credits:
                        continue

                    if credits > pool.min_credits + 30:
                        continue  # soft upper bound

                    valid_combos.append(list(combo))

            all_pool_selections.append(valid_combos)

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

        # Major required courses (first major only for now)
        if self.requirements.available_majors:
            major = self.requirements.available_majors[0]
            for code in major.required_courses:
                selected[code] = self.courses[code]

        # Electives
        for code in electives:
            selected[code] = self.courses[code]

        return selected

    def _validate(self, plan: DegreePlan):
        rules = [
            TotalCreditRule(self.requirements),
            LevelCreditRule(self.requirements),
            CoreCourseRule(self.requirements.core_courses),
            Max100LevelRule(self.requirements),
            Min300LevelRule(self.requirements),
            MajorCompletionRule(self.requirements),
            AllowedCourseRule(self.requirements),
        ]

        for pool in self.requirements.elective_pools:
            rules.append(ElectivePoolRule(pool))

        validator = DegreeValidator(rules)
        return validator.validate(plan)

    def _score(self, plan: DegreePlan) -> float:
        scorer = PlanScorer()
        return scorer.score(plan)

    def _print_diagnostics(self):
        print("\n===== SEARCH DIAGNOSTICS =====")
        print(f"Total Attempts: {self.total_attempts}")
        print(f"Generation Failures: {self.generation_failures}")
        print(f"Validation Failures: {self.validation_failures}")
        print(f"Valid Plans Found: {self.total_attempts - self.generation_failures - self.validation_failures}")

        if self.failure_breakdown:
            print("\nTop Validation Failures:")
            for error, count in sorted(
                self.failure_breakdown.items(),
                key=lambda x: x[1],
                reverse=True,
            ):
                print(f"  {count}x - {error}")