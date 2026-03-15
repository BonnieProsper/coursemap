from itertools import combinations
from typing import Dict, List, Optional
from collections import defaultdict

from coursemap.domain.course import Course
from coursemap.domain.degree_requirements import DegreeRequirements
from coursemap.domain.plan import DegreePlan
from coursemap.planner.generator import PlanGenerator
from coursemap.validation.engine import DegreeValidator
from coursemap.validation.tree_builder import build_requirement_tree
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
        self.prerequisite_pruned = 0
        self.failure_breakdown = defaultdict(int)

    def search(self) -> DegreePlan:
        self.total_attempts = 0
        self.generation_failures = 0
        self.validation_failures = 0
        self.prerequisite_pruned = 0
        self.failure_breakdown.clear()

        best_plan: Optional[DegreePlan] = None
        best_score: Optional[float] = None

        elective_combinations = self._generate_elective_combinations()

        print(f"Total elective combinations to evaluate: {len(elective_combinations)}")

        for major in self.requirements.available_majors:
            for elective_set in elective_combinations:
                self.total_attempts += 1

                selected_courses = self._build_course_subset(elective_set, major)

                if not self._quick_credit_check(selected_courses):
                    continue

                if not self._is_prerequisite_schedulable(selected_courses):
                    self.prerequisite_pruned += 1
                    continue

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

    def _build_course_subset(self, electives: List[str], major) -> Dict[str, Course]:
        selected: Dict[str, Course] = {}

        # Core
        for code in self.requirements.core_courses:
            selected[code] = self.courses[code]

        # Selected major
        for code in major.required_courses:
            selected[code] = self.courses[code]

        # Electives
        for code in electives:
            selected[code] = self.courses[code]

        return selected

    def _validate(self, plan: DegreePlan):
        degree_requirement = build_requirement_tree(self.requirements)
        validator = DegreeValidator(degree_requirement)
        return validator.validate(plan)

    def _score(self, plan: DegreePlan) -> float:
        scorer = PlanScorer()
        return scorer.score(plan)

    def _print_diagnostics(self):
        print("\n===== SEARCH DIAGNOSTICS =====")
        print(f"Total Attempts: {self.total_attempts}")
        print(f"Prerequisite-Pruned Branches: {self.prerequisite_pruned}")
        print(f"Generation Failures: {self.generation_failures}")
        print(f"Validation Failures: {self.validation_failures}")
        valid = (
            self.total_attempts
            - self.prerequisite_pruned
            - self.generation_failures
            - self.validation_failures
        )
        print(f"Valid Plans Found: {valid}")

        if self.failure_breakdown:
            print("\nTop Validation Failures:")
            for error, count in sorted(
                self.failure_breakdown.items(),
                key=lambda x: x[1],
                reverse=True,
            ):
                print(f"  {count}x - {error}")

        success = valid
        rate = success / self.total_attempts if self.total_attempts else 0
        print(f"Success Rate: {rate:.2%}")


    def _quick_credit_check(self, selected_courses: Dict[str, Course]) -> bool:
        total = sum(c.credits for c in selected_courses.values())
        return total == self.requirements.total_credits

    def _is_prerequisite_schedulable(
        self,
        selected_courses: Dict[str, Course],
    ) -> bool:
        """
        Feasibility check independent of semester offerings:
        iteratively "complete" courses only when prerequisites are satisfied.
        If progress stalls before all courses are completed, prune branch early.
        """
        remaining = set(selected_courses.keys())
        completed = set()

        while remaining:
            unlocked = []

            for code in sorted(remaining):
                prereq = selected_courses[code].prerequisites
                if prereq is None or prereq.is_satisfied(completed):
                    unlocked.append(code)

            if not unlocked:
                return False

            for code in unlocked:
                remaining.remove(code)
                completed.add(code)

        return True
