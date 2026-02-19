import statistics


class PlanScorer:
    def score(self, plan) -> float:
        semester_credits = [
            sum(c.credits for c in s.courses)
            for s in plan.semesters
        ]

        if not semester_credits:
            return 0

        variance_penalty = statistics.pvariance(semester_credits)

        empty_semester_penalty = semester_credits.count(0) * 50

        total_score = variance_penalty + empty_semester_penalty

        return total_score
