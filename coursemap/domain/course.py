from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional

from .prerequisite import PrerequisiteExpression


@dataclass(frozen=True)
class Offering:
    year: int
    semester: str  # "S1", "S2", "SS"
    campus: str
    mode: str  # "internal" or "distance"


@dataclass(frozen=True)
class Course:
    code: str
    title: str
    credits: int
    level: int
    offerings: List[Offering]
    prerequisites: Optional[PrerequisiteExpression] = None

    def is_offered(
        self,
        year: int,
        semester: str,
        campus: str,
        mode: str,
    ) -> bool:
        return any(
            o.year == year
            and o.semester == semester
            and o.campus == campus
            and o.mode == mode
            for o in self.offerings
        )
