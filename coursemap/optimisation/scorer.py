from coursemap.domain.plan import DegreePlan


class PlanScorer:
    """
    Lower score = better plan.
    """

    def score(self, plan: DegreePlan) -> float:
        semesters = plan.semesters

        if not semesters:
            return float("inf")

        total_semesters = len(semesters)

        credit_loads = [
            s.total_credits() for s in semesters
        ]

        max_load = max(credit_loads)
        min_load = min(credit_loads)

        imbalance_penalty = max_load - min_load

        final_semester_penalty = semesters[-1].total_credits()

        semester_penalty = total_semesters * 100
        spread_penalty = imbalance_penalty * 5
        final_penalty = final_semester_penalty * 2

        return semester_penalty + spread_penalty + final_penalty