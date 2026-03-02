from dataclasses import dataclass
from typing import List
from coursemap.domain.degree_requirements import DegreeRequirements
from coursemap.domain.electives import ElectivePool
from coursemap.domain.major import Major


@dataclass
class DegreeConfig:
    name: str
    requirements: DegreeRequirements
    core_courses: List[str]
    elective_pools: List[ElectivePool]
    majors: List[Major]