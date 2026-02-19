@dataclass
class SemesterPlan:
    year: int
    semester: str
    courses: list[Course]

@dataclass
class DegreePlan:
    semesters: list[SemesterPlan]

    def total_credits(self) -> int:
        ...
