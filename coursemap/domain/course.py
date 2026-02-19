@dataclass(frozen=True)
class Course:
    code: str
    title: str
    credits: int
    level: int
    prerequisites: PrerequisiteExpression | None
    offerings: list[Offering]

@dataclass(frozen=True)
class Offering:
    year: int
    semester: str  # "S1", "S2", "SS"
    campus: str
    mode: str  # "internal", "distance"
