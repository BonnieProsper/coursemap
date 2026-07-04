"""
Fee estimation for Massey University courses.

Based on Massey's published 2026 fee schedules.
Fees are per-credit estimates derived from typical course fees.
All figures are approximate. Always check massey.ac.nz/fees for exact amounts.

Domestic fees source: https://www.massey.ac.nz/fees
International fees are approximately 2.5-3x domestic (varies by programme).

IMPORTANT: what these numbers are NOT.
Massey does not publish a flat per-credit tuition rate anywhere scrapable;
course pages list prerequisites, restrictions, and assessment breakdowns but
never a fee figure (the real fee calculator is an interactive tool, not part
of any static page this project's scraper can read). Every number below is
therefore a manually-maintained estimate, not data pulled from Massey, and
it will drift out of date as fees rise each year.

These estimates also cover TUITION ONLY. Massey additionally charges a
compulsory Student Services Levy (a separate per-credit non-tuition fee,
capped at 120 credits/year) plus other non-tuition fees (e.g. some papers
carry materials/field-trip costs) that are NOT included in any total this
module returns. A real invoice will be higher than this estimate.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Domestic fee-per-credit by subject area (NZD, 2026 approximate)
# ---------------------------------------------------------------------------
# Based on Massey's published per-course fees divided by typical credit value.
# Undergraduate (L100-400) and postgraduate (L700-900) use different rates.
#
# Tier 1 (arts, humanities, social sciences): ~$50-55/cr
# Tier 2 (science, IT, business, applied):    ~$58-65/cr
# Tier 3 (health, engineering, professional): ~$65-80/cr
# Tier 4 (veterinary, medicine, creative):    ~$75-95/cr
#
# "confidence" reflects how directly each rate is grounded:
#   "estimated"  : placed in a tier by subject-matter judgement, not pinned
#                  to a specific published figure. This is every entry below;
#                  there is currently no subject with a verified, sourced rate.
# The field exists so a future pass that *does* pin a real published rate for
# a specific subject (and can cite the page/date) has somewhere to upgrade
# the confidence to "published" without changing every caller.

_SUBJECT_FEE_PER_CREDIT: dict[str, float] = {
    # Arts & Humanities (Tier 1)
    "Art History":          52.0,
    "Classical Studies":    52.0,
    "Classics":             52.0,
    "Development Studies":  52.0,
    "Music":                58.0,
    "Philosophy":           52.0,
    "Politics":             52.0,
    "Sociology":            52.0,
    "International Relations": 52.0,
    "History":              52.0,
    "Geography":            55.0,

    # Social Science (Tier 1-2)
    "Criminology":          54.0,
    "Counselling":          58.0,
    "Psychology":           55.0,
    "Social Work":          58.0,

    # Business (Tier 2)
    "Accounting":           60.0,
    "Business":             60.0,
    "Business Administration": 62.0,
    "Business Law":         60.0,
    "Economics":            58.0,
    "Finance":              62.0,
    "Financial Planning":   60.0,
    "Human Resources":      60.0,
    "Management":           60.0,
    "Marketing":            60.0,
    "Strategic Studies":    60.0,

    # STEM (Tier 2)
    "Applied Statistics":   62.0,
    "Biomedical Science":   65.0,
    "Chemistry":            65.0,
    "Computer Science":     65.0,
    "Data Science":         65.0,
    "Environmental Science": 62.0,
    "Information Sciences": 63.0,
    "Information Systems":  62.0,
    "Information Technology": 62.0,
    "Mathematics":          62.0,
    "Physics":              65.0,
    "Software Engineering": 65.0,
    "Statistics":           62.0,

    # Agriculture & Environment (Tier 2-3)
    "Agriculture":          65.0,
    "Construction":         68.0,
    "Environmental Management": 62.0,

    # Health (Tier 3)
    "Defence Studies":      55.0,
    "Dietetics":            72.0,
    "Education":            58.0,
    "Health Science":       65.0,
    "Midwifery":            75.0,
    "Nursing":              72.0,
    "Paramedicine":         72.0,
    "Physiotherapy":        78.0,
    "Sport & Exercise Science": 65.0,
    "Sport Science":        65.0,

    # Design & Creative (Tier 3-4)
    "Design":               70.0,

    # Research/generic (fallback)
    "Research Methods":     58.0,
    "Foundation Studies":   50.0,
}

# Default fee per credit for unknown subject areas
_DEFAULT_FEE_PER_CREDIT_UG = 60.0   # undergraduate
_DEFAULT_FEE_PER_CREDIT_PG = 75.0   # postgraduate (L700+)

# International multiplier (applied on top of domestic)
# Massey international fees vary by programme but average ~2.8x domestic
_INTERNATIONAL_MULTIPLIER = 2.8


def fee_constants() -> dict:
    """
    Return the raw fee-rate constants as a JSON-friendly dict.

    This is the single source of truth for fee estimation. The web UI fetches
    this once at load time (GET /api/fees/constants) instead of keeping its
    own hardcoded copy of the rate table. Two independently-maintained
    copies of the same table WILL drift (this happened: the UI's copy was
    missing "Software Engineering" and "Information Sciences", silently
    understating their fee estimate to the flat default rate while the
    Python-side /api/plan/fees calculation was already correct).
    """
    return {
        "subject_fee_per_credit": dict(_SUBJECT_FEE_PER_CREDIT),
        "default_fee_per_credit_ug": _DEFAULT_FEE_PER_CREDIT_UG,
        "default_fee_per_credit_pg": _DEFAULT_FEE_PER_CREDIT_PG,
        "international_multiplier": _INTERNATIONAL_MULTIPLIER,
        "postgrad_min_rate": 70.0,  # mirrors the inline floor in fee_per_credit()
    }


def fee_per_credit(subject_area: str | None, level: int, student_type: str = "domestic") -> float:
    """
    Return the estimated fee per credit for a given subject area and level.

    Args:
        subject_area: Course subject area string (may be None).
        level:        Course level (100, 200, 300, 400, 700, 800, 900).
        student_type: "domestic" or "international".

    Returns:
        Estimated fee in NZD per credit.
    """
    if subject_area and subject_area in _SUBJECT_FEE_PER_CREDIT:
        base = _SUBJECT_FEE_PER_CREDIT[subject_area]
    elif level >= 700:
        base = _DEFAULT_FEE_PER_CREDIT_PG
    else:
        base = _DEFAULT_FEE_PER_CREDIT_UG

    # Postgraduate surcharge (L700-900 cost more even in the same subject)
    if level >= 700 and base < 70:
        base = max(base, 70.0)

    if student_type == "international":
        base *= _INTERNATIONAL_MULTIPLIER

    return base


def estimate_course_fee(credits: int, subject_area: str | None, level: int,
                         student_type: str = "domestic") -> float:
    """Estimate total fee for a single course."""
    return credits * fee_per_credit(subject_area, level, student_type)


def estimate_plan_fees(
    semesters: list[dict],
    student_type: str = "domestic",
) -> dict:
    """
    Estimate TUITION fees for a full degree plan. Does not include the
    compulsory Student Services Levy or any other non-tuition fee. See
    module docstring. The real total a student is billed will be higher.

    Args:
        semesters: List of semester dicts from the plan API response,
                   each with a 'courses' list of course dicts.
        student_type: "domestic" or "international".

    Returns:
        Dict with 'total', 'by_year', 'excludes', and 'disclaimer' keys.
    """
    total = 0.0
    by_year: dict[int, float] = {}
    courses_seen = 0
    courses_on_default_rate = 0  # no subject-area match -> fell back to the flat default

    for sem in semesters:
        year = sem.get("year", 0)
        year_total = 0.0
        for course in sem.get("courses", []):
            credits = course.get("credits", 15)
            level = course.get("level", 100)
            subject_area = course.get("subject_area")
            year_total += estimate_course_fee(credits, subject_area, level, student_type)
            courses_seen += 1
            if not subject_area or subject_area not in _SUBJECT_FEE_PER_CREDIT:
                courses_on_default_rate += 1
        by_year[year] = by_year.get(year, 0.0) + year_total
        total += year_total

    rounded_by_year = {yr: round(amt, -1) for yr, amt in sorted(by_year.items())}
    # Derive total from the rounded by_year values, not from rounding the raw
    # total independently. Otherwise the displayed total and the sum of the
    # displayed per-year breakdown can disagree by a few dollars purely due
    # to rounding order (e.g. raw 455+455=910 rounds to 910 as a whole, but
    # 455 rounds to 460 individually, so by_year would sum to 920 while total
    # showed 910, a student adding up their own numbers would get a
    # different answer than what's displayed as the total).
    rounded_total = sum(rounded_by_year.values())

    default_rate_pct = round(100 * courses_on_default_rate / courses_seen) if courses_seen else 0

    return {
        "total": rounded_total,
        "by_year": rounded_by_year,
        "student_type": student_type,
        "excludes": [
            "Student Services Levy (compulsory, per-credit, capped at 120cr/year)",
            "Course-specific materials, field trip, or lab fees where they apply",
            "Any one-off administration or application fees",
        ],
        "confidence": (
            f"{default_rate_pct}% of courses in this plan have no subject-specific rate "
            f"and used the flat default instead. Treat this plan's estimate as lower-confidence."
            if default_rate_pct > 30 else
            "Most courses in this plan matched a subject-specific estimated rate."
        ),
        "disclaimer": (
            "These are rough TUITION-ONLY estimates manually derived from Massey's public fee "
            "tiers, not figures scraped from Massey (Massey does not publish a flat per-credit "
            "rate on any page this tool can read). They exclude the Student Services Levy and "
            "other non-tuition fees, so your real invoice will be higher than this total. "
            "Use this for rough budgeting only. Check massey.ac.nz/fees and your actual Offer "
            "of Enrolment for the real amount before making any financial decision."
        ),
    }
