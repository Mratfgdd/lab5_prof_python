import re
from decimal import Decimal

from reliable_importer.config import ProcessingConfig
from reliable_importer.validators import RecordValidator

CONFIG = ProcessingConfig(
    skip_invalid=False,
    minimum_grade=Decimal(60),
    group_pattern=re.compile(r"PI-\d{2}"),
    progress_every=1_000,
)

ROW: dict[str, object] = {
    "student_id": "1",
    "first_name": "Анна",
    "last_name": "Коваль",
    "group": "PI-21",
    "average_grade": "wrong",
}

RecordValidator(CONFIG).validate(2, ROW)
