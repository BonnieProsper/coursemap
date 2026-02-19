from dataclasses import dataclass
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
    core_courses: Set[str]
    elective_pools: List[ElectivePool]