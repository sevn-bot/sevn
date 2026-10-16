"""Secret backend errors."""


class SecretNotFound(Exception):
    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"secret not found: {name}")


class SecretBackendReadOnly(Exception):
    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"secret backend is read-only: {name}")
