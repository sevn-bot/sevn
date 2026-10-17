"""Runtime failures."""

from __future__ import annotations


class ModelError(Exception):
    """A model name cannot be resolved or is not enabled."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class TurnError(Exception):
    """A turn cannot be loaded or has no result to store."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)
