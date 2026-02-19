from dataclasses import dataclass, field
from typing import Dict, List, Set

from coursemap.domain.electives import ElectivePool


@dataclass(frozen=True)
class LevelCreditRequirement:
    level: int
    min_credits: int


@dataclass(frozen=True)
class DegreeRequirements:
    total_credits: int
    level_requirements: Dict[int, LevelCreditRequirement]

    core_courses: Set[str] = field(default_factory=set)
    elective_pools: List[ElectivePool] = field(default_factory=list)
