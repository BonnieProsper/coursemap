from dataclasses import dataclass
from typing import Dict, List, Optional, Set

from coursemap.domain.electives import ElectivePool
from coursemap.domain.major import Major


@dataclass(frozen=True)
class LevelCreditRequirement:
    level: int
    min_credits: Optional[int] = None
    max_credits: Optional[int] = None


@dataclass(frozen=True)
class DegreeRequirements:
    # Global structure
    total_credits: int
    max_100_level: Optional[int]
    min_300_level: Optional[int]

    # Per-level minimums
    level_requirements: Dict[int, LevelCreditRequirement]

    # Core & schedule rules
    core_courses: Set[str]
    min_schedule_credits: Optional[int]

    # Majors
    required_majors: int
    available_majors: List[Major]

    # Electives
    elective_pools: List[ElectivePool]
