from coursemap.domain.degree_requirements import DegreeRequirements
from coursemap.domain.major import Major


def build_statistics_major():
    return Major(
        name="Statistics",
        required_courses={
            "STAT201",
            "STAT202",
            "STAT203",
            "STAT301",
        },
        total_credits=120,
        min_200_level=60,
        min_300_level=60,
    )


def build_massey_bsc_requirements():
    return DegreeRequirements(
        total_credits=360,
        max_100_level=165,
        min_300_level=75,
        level_requirements={},
        core_courses=set(),
        min_schedule_credits=240,
        required_majors=1,
        available_majors=[build_statistics_major()],
        elective_pools=[],
    )