from dataclasses import dataclass
from typing import Set


@dataclass(frozen=True)
class ElectivePool:
    name: str
    course_codes: Set[str]
    min_credits: int
