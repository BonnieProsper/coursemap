from dataclasses import dataclass
from typing import Set


@dataclass(frozen=True)
class Major:
    name: str
    required_courses: Set[str]
    total_credits: int
    min_200_level: int
    min_300_level: int