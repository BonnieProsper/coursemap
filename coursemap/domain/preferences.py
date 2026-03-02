from dataclasses import dataclass
from typing import Optional, Set


@dataclass
class UserPreferences:
    preferred_semester_load: Optional[int] = None
    avoid_morning: bool = False
    preferred_courses: Optional[Set[str]] = None