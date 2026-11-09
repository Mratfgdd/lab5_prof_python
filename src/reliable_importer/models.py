from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class StudentRecord:
    line_number: int
    student_id: int
    first_name: str
    last_name: str
    group: str
    average_grade: Decimal

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"

    def to_dict(self) -> dict[str, object]:
        return {
            "student_id": self.student_id,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "group": self.group,
            "average_grade": self.average_grade,
        }


@dataclass(slots=True)
class ImportStatistics:
    total: int = 0
    valid: int = 0
    invalid: int = 0
    below_minimum: int = 0
    exported: int = 0
    errors: Counter[str] = field(default_factory=Counter)
    groups: Counter[str] = field(default_factory=Counter)

    def to_dict(self) -> dict[str, object]:
        return {
            "total": self.total,
            "valid": self.valid,
            "invalid": self.invalid,
            "below_minimum": self.below_minimum,
            "exported": self.exported,
            "errors_by_code": dict(self.errors),
            "exported_by_group": dict(sorted(self.groups.items())),
        }
