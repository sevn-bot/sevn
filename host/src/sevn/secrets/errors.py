"""Secret backend errors."""


class SecretNotFound(Exception):
    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"secret not found: {name}")


class SecretBackendReadOnly(Exception):
    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"secret backend is read-only: {name}")


class SecretsBackendError(Exception):
    """The secret store cannot be used right now. ``code`` is stable; the message holds no value."""

    code: str = "secrets_unavailable"

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(f"{self.code}: {message}")


class SecretsLocked(SecretsBackendError):
    """The Secret Service collection is locked (plan 0025 D4)."""

    code = "secrets_locked"

    def __init__(self, message: str = "the Secret Service collection is locked") -> None:
        super().__init__(message)


class SecretsUnavailable(SecretsBackendError):
    """No Secret Service answers, or it refused an operation (plan 0025 D4)."""

    code = "secrets_unavailable"
