import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from reliable_importer.config import ProcessingConfig
from reliable_importer.exceptions import RecordValidationError
from reliable_importer.models import StudentRecord
from reliable_importer.readers import RawRow

NAME_PATTERN = re.compile(r"[^\W\d_]+(?:[-'’ ][^\W\d_]+)*")
HUNDREDTH = Decimal("0.01")


class RecordValidator:
    def __init__(self, config: ProcessingConfig) -> None:
        self._config = config

    def validate(self, line_number: int, row: RawRow) -> StudentRecord:
        student_id = self._student_id(row, line_number)
        first_name = self._name(row, "first_name", line_number)
        last_name = self._name(row, "last_name", line_number)
        group = self._text(row, "group", line_number)
        if not self._config.group_pattern.fullmatch(group):
            raise RecordValidationError(
                "код групи не відповідає формату",
                line_number=line_number,
                field="group",
                code="bad_group",
            )
        grade = self._grade(row, line_number)
        return StudentRecord(line_number, student_id, first_name, last_name, group, grade)

    @staticmethod
    def _text(row: RawRow, field: str, line_number: int) -> str:
        value = row.get(field)
        if not isinstance(value, str) or not value.strip():
            raise RecordValidationError(
                "поле відсутнє або порожнє",
                line_number=line_number,
                field=field,
                code="missing_field",
            )
        return value.strip()

    def _name(self, row: RawRow, field: str, line_number: int) -> str:
        name = self._text(row, field, line_number)
        if not NAME_PATTERN.fullmatch(name):
            raise RecordValidationError(
                "ім'я містить недозволені символи",
                line_number=line_number,
                field=field,
                code="bad_name",
            )
        return name

    @staticmethod
    def _student_id(row: RawRow, line_number: int) -> int:
        value = row.get("student_id")
        if value is None or isinstance(value, bool):
            raise RecordValidationError(
                "поле відсутнє", line_number=line_number, field="student_id", code="missing_field"
            )
        try:
            student_id = int(str(value).strip())
        except ValueError as error:
            raise RecordValidationError(
                "ідентифікатор не є цілим числом",
                line_number=line_number,
                field="student_id",
                code="bad_id",
            ) from error
        if student_id < 1:
            raise RecordValidationError(
                "ідентифікатор має бути додатним",
                line_number=line_number,
                field="student_id",
                code="bad_id",
            )
        return student_id

    @staticmethod
    def _grade(row: RawRow, line_number: int) -> Decimal:
        value = row.get("average_grade")
        if value is None or isinstance(value, bool):
            raise RecordValidationError(
                "поле відсутнє",
                line_number=line_number,
                field="average_grade",
                code="missing_field",
            )
        try:
            grade = Decimal(str(value).strip())
        except InvalidOperation as error:
            raise RecordValidationError(
                "значення не є числом",
                line_number=line_number,
                field="average_grade",
                code="bad_number",
            ) from error
        if not grade.is_finite():
            raise RecordValidationError(
                "значення не є скінченним числом",
                line_number=line_number,
                field="average_grade",
                code="bad_number",
            )
        if not 0 <= grade <= 100:
            raise RecordValidationError(
                "середній бал має бути від 0 до 100",
                line_number=line_number,
                field="average_grade",
                code="grade_out_of_range",
            )
        return grade.quantize(HUNDREDTH, ROUND_HALF_UP)
