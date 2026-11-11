"""Failure type for the Azure data layer. Messages never contain credentials."""

from __future__ import annotations


class AzureDataError(RuntimeError):
    """An Azure read failed after retries, or returned data we cannot trust."""

    def __init__(self, operation: str, detail: str, *, status_code: int | None = None) -> None:
        self.operation = operation
        self.status_code = status_code
        super().__init__(f"{operation}: {detail}")
