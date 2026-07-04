"""Course and offering domain types."""
from __future__ import annotations
from dataclasses import dataclass, field

from .prerequisite import PrerequisiteExpression

SEMESTER_ORDER: dict[str, int] = {"S1": 0, "S2": 1, "SS": 2}


def sort_semesters(semesters) -> list[str]:
    """
    Sort an iterable of semester codes into calendar order (S1, S2, SS).

    Plain alphabetical sort happens to produce this same order for these
    three specific strings (ASCII '1' < '2' < 'S'), which is easy to rely on
    without realizing it's a coincidence rather than a guarantee. Fragile
    if a new semester code were ever introduced that didn't happen to sort
    the same way alphabetically. This makes the intended order explicit.
    """
    return sorted(set(semesters), key=lambda s: SEMESTER_ORDER.get(s, 99))


@dataclass(frozen=True)
class Offering:
    """One available instance of a course in a specific semester and delivery mode."""
    semester:  str   # "S1", "S2", or "SS" (Summer School)
    campus:    str   # "D" (distance), "M" (Manawatu), "A" (Auckland), "W" (Wellington)
    mode:      str   # "DIS" (distance), "INT" (internal), "BLK" (block)
    full_year: bool = False  # True when the raw data was "Full Year" (must enrol S1+S2 as a unit)

    @property
    def campus_code(self) -> str:
        return self.campus

    @property
    def delivery_mode(self) -> str:
        return self.mode

    @property
    def location(self) -> str:
        """Human-readable location label."""
        _labels = {
            "D": "Distance and online",
            "M": "Manawatū campus (Palmerston North)",
            "A": "Auckland campus",
            "W": "Wellington campus",
            "N": "NZCM",
        }
        return _labels.get(self.campus, self.campus)


@dataclass(frozen=True)
class Course:
    """
    A Massey course as loaded from the dataset.

    corequisites: codes of courses that must be taken in the same semester or
    already completed before enrolment.

    restrictions: codes of courses that permanently block enrolment in this
    course once completed.
    """
    code:          str
    title:         str
    credits:       int
    level:         int
    offerings:     tuple[Offering, ...]
    prerequisites: PrerequisiteExpression | None = None
    corequisites:  frozenset[str] = field(default_factory=frozenset)
    restrictions:  frozenset[str] = field(default_factory=frozenset)
    url:           str | None = None
    description:   str | None = None
    subject_area:  str | None = None
    offering_inferred: bool = False

    def is_offered(self, semester: str, campus: str, mode: str) -> bool:
        return any(
            o.semester == semester and o.campus == campus and o.mode == mode
            for o in self.offerings
        )

    def has_full_year_offering(self) -> bool:
        """True if any offering was originally a Full Year enrolment."""
        return any(o.full_year for o in self.offerings)

    def offered_campuses(self) -> frozenset[str]:
        return frozenset(o.campus for o in self.offerings)

    def offered_modes(self) -> frozenset[str]:
        return frozenset(o.mode for o in self.offerings)

    def offered_semesters(self, campus: str | None = None, mode: str | None = None) -> frozenset[str]:
        return frozenset(
            o.semester for o in self.offerings
            if (campus is None or o.campus == campus)
            and (mode is None or o.mode == mode)
        )
