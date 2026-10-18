"""Eval harness errors."""


class EvalsError(Exception):
    """The eval suite could not run."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)
