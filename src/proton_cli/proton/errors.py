"""Proton API transport errors."""

from __future__ import annotations


class ErrUnauthorized(Exception):
    """Session expired and token refresh did not recover."""


class ErrHVUnavailable(Exception):
    """Human verification required but no token could be resolved."""


class NetworkError(Exception):
    """Transport-level failure (exit 5)."""

    def exit_code(self) -> int:
        return 5


class APIError(Exception):
    """Non-2xx Proton API response."""

    def __init__(
        self,
        *,
        http_status: int,
        code: int = 0,
        message: str = "",
        raw_body: bytes = b"",
    ) -> None:
        self.http_status = http_status
        self.code = code
        self.message = message
        self.raw_body = raw_body
        if code:
            super().__init__(f"[HTTP {http_status}] {code}: {message}")
        else:
            super().__init__(f"[HTTP {http_status}] {message}")

    def exit_code(self) -> int:
        if self.http_status in (401, 403):
            return 2
        if self.http_status == 404:
            return 3
        if self.http_status in (409, 422):
            return 4
        if self.http_status >= 500:
            return 5
        return 1


class HumanVerificationError(Exception):
    """Proton code 9001 — CAPTCHA required."""

    def __init__(
        self, *, token: str = "", methods: list[str] | None = None, web_url: str = ""
    ) -> None:
        self.token = token
        self.methods = methods or []
        self.web_url = web_url
        super().__init__(f"human verification required: {web_url}")


class ErrHVUnavailable(Exception):
    """HV challenge could not be solved automatically."""
