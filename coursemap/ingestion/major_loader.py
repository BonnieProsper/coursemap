import json
from pathlib import Path

from coursemap.domain.major import Major
from coursemap.domain.electives import ElectivePool

DATASET = Path("datasets/majors.json")


def load_majors():

    if not DATASET.exists():
        return []

    with open(DATASET) as f:
        raw = json.load(f)

    majors = []

    for name, data in raw.items():

        pools = []

        for pool in data.get("elective_pools", []):

            pools.append(
                ElectivePool(
                    courses=pool["courses"],
                    min_courses=pool["min_courses"],
                )
            )

        majors.append(
            Major(
                name=name,
                core_courses=data.get("core_courses", []),
                elective_pools=pools,
            )
        )

    return majors