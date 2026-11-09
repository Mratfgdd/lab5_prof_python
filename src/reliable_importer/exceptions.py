class ApplicationError(Exception):
    pass


class ConfigurationError(ApplicationError):
    pass


class DataError(ApplicationError):
    pass


class DataImportError(DataError):
    pass


class UnsupportedFormatError(DataImportError):
    pass


class DataExportError(DataError):
    pass


class RecordValidationError(DataError):
    def __init__(
        self,
        message: str,
        *,
        line_number: int | None = None,
        field: str | None = None,
        code: str = "invalid",
    ) -> None:
        super().__init__(message)
        self.message = message
        self.line_number = line_number
        self.field = field
        self.code = code

    def __str__(self) -> str:
        where = f"рядок {self.line_number}" if self.line_number is not None else "запис"
        column = f", поле {self.field!r}" if self.field else ""
        return f"{where}{column}: {self.message} [{self.code}]"
