from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Set, List


class PrerequisiteExpression(ABC):
    """
    Base class for prerequisite logic tree.
    """

    @abstractmethod
    def is_satisfied(self, completed: Set[str]) -> bool:
        ...

    @abstractmethod
    def required_courses(self) -> Set[str]:
        ...


@dataclass(frozen=True)
class CourseRequirement(PrerequisiteExpression):
    code: str

    def is_satisfied(self, completed: Set[str]) -> bool:
        return self.code in completed

    def required_courses(self) -> Set[str]:
        return {self.code}


@dataclass(frozen=True)
class AndExpression(PrerequisiteExpression):
    children: List[PrerequisiteExpression]

    def is_satisfied(self, completed: Set[str]) -> bool:
        return all(child.is_satisfied(completed) for child in self.children)

    def required_courses(self) -> Set[str]:
        result: Set[str] = set()
        for child in self.children:
            result.update(child.required_courses())
        return result


@dataclass(frozen=True)
class OrExpression(PrerequisiteExpression):
    children: List[PrerequisiteExpression]

    def is_satisfied(self, completed: Set[str]) -> bool:
        return any(child.is_satisfied(completed) for child in self.children)

    def required_courses(self) -> Set[str]:
        result: Set[str] = set()
        for child in self.children:
            result.update(child.required_courses())
        return result
