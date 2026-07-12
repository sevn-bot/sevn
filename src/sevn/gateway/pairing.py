"""DM pairing store for channel access.

Module: sevn.gateway.pairing
Depends: hashlib, json, pathlib, secrets, threading, time

Exports:
    PairingStore — code-based DM pairing persistence under ``.sevn/pairing/``.
    pairing_dir_for_content_root — resolve pairing storage directory.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import tempfile
import threading
import time
from contextlib import suppress
from pathlib import Path
from typing import Any

from loguru import logger

_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_CODE_LENGTH = 8
_CODE_TTL_SECONDS = 3600
_RATE_LIMIT_SECONDS = 600
_LOCKOUT_SECONDS = 3600
_MAX_PENDING_PER_PLATFORM = 3
_MAX_FAILED_ATTEMPTS = 5


def pairing_dir_for_content_root(content_root: Path) -> Path:
    """Return pairing persistence directory for one workspace.

    Args:
        content_root (Path): Workspace content root.

    Returns:
        Path: ``<content_root>/.sevn/pairing``.

    Examples:
        >>> pairing_dir_for_content_root(Path("/tmp/w")).name
        'pairing'
    """
    return content_root.expanduser().resolve() / ".sevn" / "pairing"


def _secure_write(path: Path, data: str) -> None:
    """Write ``data`` atomically with owner-only permissions.

    Args:
        path (Path): Destination file path.
        data (str): JSON or text payload to write.

    Examples:
        >>> import tempfile
        >>> p = Path(tempfile.mkdtemp()) / "x.json"
        >>> _secure_write(p, "{}")
        >>> p.read_text(encoding="utf-8")
        '{}'
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
        with suppress(OSError):
            os.chmod(path, 0o600)
    except BaseException:
        with suppress(OSError):
            os.unlink(tmp_path)
        raise


class PairingStore:
    """Manage pairing codes and approved user lists per channel adapter."""

    def __init__(self, content_root: Path) -> None:
        """Bind pairing storage to one workspace content root.

        Args:
            content_root (Path): Workspace content root.

        Examples:
            >>> PairingStore(Path("/tmp/w")) is not None
            True
        """
        self._dir = pairing_dir_for_content_root(content_root)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    @property
    def storage_dir(self) -> Path:
        """Return on-disk pairing directory.

        Returns:
            Path: Pairing directory path.

        Examples:
            >>> store = PairingStore(Path("/tmp/w"))
            >>> store.storage_dir.name
            'pairing'
        """
        return self._dir

    def _pending_path(self, platform: str) -> Path:
        """Return pending-codes file path for one platform.

        Args:
            platform (str): Channel adapter name.

        Returns:
            Path: Pending codes JSON path.

        Examples:
            >>> PairingStore(Path("/tmp/w"))._pending_path("telegram").name
            'telegram-pending.json'
        """
        return self._dir / f"{platform}-pending.json"

    def _approved_path(self, platform: str) -> Path:
        """Return approved-users file path for one platform.

        Args:
            platform (str): Channel adapter name.

        Returns:
            Path: Approved users JSON path.

        Examples:
            >>> PairingStore(Path("/tmp/w"))._approved_path("telegram").name
            'telegram-approved.json'
        """
        return self._dir / f"{platform}-approved.json"

    def _rate_limit_path(self) -> Path:
        """Return shared rate-limit state file path.

        Returns:
            Path: Rate-limit JSON path.

        Examples:
            >>> PairingStore(Path("/tmp/w"))._rate_limit_path().name
            '_rate_limits.json'
        """
        return self._dir / "_rate_limits.json"

    def _load_json(self, path: Path) -> dict[str, Any]:
        """Load JSON object from ``path`` or return empty dict.

        Args:
            path (Path): File to read.

        Returns:
            dict[str, Any]: Parsed object or ``{}``.

        Examples:
            >>> PairingStore(Path("/tmp/w"))._load_json(Path("/missing"))
            {}
        """
        if path.exists():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return {}
            if isinstance(loaded, dict):
                return loaded
        return {}

    def _save_json(self, path: Path, data: dict[str, Any]) -> None:
        """Persist ``data`` as JSON at ``path``.

        Args:
            path (Path): Destination file.
            data (dict[str, Any]): JSON-serializable payload.

        Examples:
            >>> store = PairingStore(Path("/tmp/w"))
            >>> store._save_json(store._rate_limit_path(), {})
        """
        _secure_write(path, json.dumps(data, indent=2, ensure_ascii=False))

    @staticmethod
    def _hash_code(code: str, salt: bytes) -> str:
        """Return salted SHA-256 hex digest for one pairing code.

        Args:
            code (str): Plaintext pairing code.
            salt (bytes): Random salt bytes.

        Returns:
            str: Hex digest.

        Examples:
            >>> len(PairingStore._hash_code("ABCD2345", b"salt")) == 64
            True
        """
        return hashlib.sha256(salt + code.encode("utf-8")).hexdigest()

    def is_approved(self, platform: str, user_id: str) -> bool:
        """Return whether ``user_id`` is approved on ``platform``.

        Args:
            platform (str): Channel adapter name.
            user_id (str): Sender id.

        Returns:
            bool: Approval verdict.

        Examples:
            >>> store = PairingStore(Path("/tmp/w"))
            >>> store.is_approved("telegram", "99")
            False
        """
        approved = self._load_json(self._approved_path(platform))
        normalized = str(user_id or "").strip()
        return normalized in approved

    def list_approved(self, platform: str | None = None) -> list[dict[str, Any]]:
        """List approved users, optionally filtered by platform.

        Args:
            platform (str | None): Channel filter or ``None`` for all.

        Returns:
            list[dict[str, Any]]: Approved user rows.

        Examples:
            >>> import tempfile
            >>> PairingStore(Path(tempfile.mkdtemp())).list_approved("telegram")
            []
        """
        results: list[dict[str, Any]] = []
        platforms = [platform] if platform else self._all_platforms("approved")
        for name in platforms:
            approved = self._load_json(self._approved_path(name))
            for uid, info in approved.items():
                row = {"platform": name, "user_id": uid}
                if isinstance(info, dict):
                    row.update(info)
                results.append(row)
        return results

    def _approve_user(self, platform: str, user_id: str, user_name: str = "") -> None:
        """Persist one approved user id for ``platform``.

        Args:
            platform (str): Channel adapter name.
            user_id (str): Approved sender id.
            user_name (str): Optional display name.

        Examples:
            >>> store = PairingStore(Path("/tmp/w"))
            >>> store._approve_user("telegram", "1")
        """
        approved = self._load_json(self._approved_path(platform))
        normalized = str(user_id or "").strip()
        approved[normalized] = {
            "user_name": user_name,
            "approved_at": time.time(),
        }
        self._save_json(self._approved_path(platform), approved)

    def revoke(self, platform: str, user_id: str) -> bool:
        """Remove one approved user.

        Args:
            platform (str): Channel adapter name.
            user_id (str): User to revoke.

        Returns:
            bool: ``True`` when a row was removed.

        Examples:
            >>> import tempfile
            >>> PairingStore(Path(tempfile.mkdtemp())).revoke("telegram", "1")
            False
        """
        path = self._approved_path(platform)
        with self._lock:
            approved = self._load_json(path)
            normalized = str(user_id or "").strip()
            if normalized in approved:
                del approved[normalized]
                self._save_json(path, approved)
                return True
        return False

    def generate_code(
        self,
        platform: str,
        user_id: str,
        *,
        user_name: str = "",
    ) -> str | None:
        """Generate a pairing code for a new user.

        Args:
            platform (str): Channel adapter name.
            user_id (str): Requesting user id.
            user_name (str): Optional display name.

        Returns:
            str | None: Plaintext code for the user, or ``None`` when blocked.

        Examples:
            >>> store = PairingStore(Path("/tmp/w"))
            >>> code = store.generate_code("telegram", "42", user_name="Alex")
            >>> code is None or len(code) == 8
            True
        """
        with self._lock:
            self._cleanup_expired(platform)
            if self._is_locked_out(platform):
                return None
            if self._is_rate_limited(platform, user_id):
                return None
            pending = self._load_json(self._pending_path(platform))
            if len(pending) >= _MAX_PENDING_PER_PLATFORM:
                return None
            code = "".join(secrets.choice(_ALPHABET) for _ in range(_CODE_LENGTH))
            salt = os.urandom(16)
            entry_id = secrets.token_hex(8)
            pending[entry_id] = {
                "hash": self._hash_code(code, salt),
                "salt": salt.hex(),
                "user_id": str(user_id or "").strip(),
                "user_name": user_name,
                "created_at": time.time(),
            }
            self._save_json(self._pending_path(platform), pending)
            self._record_rate_limit(platform, user_id)
            return code

    def approve_code(self, platform: str, code: str) -> dict[str, str] | None:
        """Approve a pairing code and persist the user.

        Args:
            platform (str): Channel adapter name.
            code (str): Operator-supplied code.

        Returns:
            dict[str, str] | None: ``{user_id, user_name}`` on success.

        Examples:
            >>> store = PairingStore(Path("/tmp/w"))
            >>> store.approve_code("telegram", "INVALID1") is None
            True
        """
        with self._lock:
            self._cleanup_expired(platform)
            if self._is_locked_out(platform):
                return None
            normalized_code = code.upper().strip()
            pending = self._load_json(self._pending_path(platform))
            matched_key: str | None = None
            matched_entry: dict[str, Any] | None = None
            for entry_id, entry in pending.items():
                if not isinstance(entry, dict):
                    continue
                salt_hex = entry.get("salt")
                hash_val = entry.get("hash")
                if not isinstance(salt_hex, str) or not isinstance(hash_val, str):
                    continue
                try:
                    salt = bytes.fromhex(salt_hex)
                except ValueError:
                    continue
                candidate = self._hash_code(normalized_code, salt)
                if secrets.compare_digest(candidate, hash_val):
                    matched_key = entry_id
                    matched_entry = entry
                    break
            if matched_key is None or matched_entry is None:
                self._record_failed_attempt(platform)
                return None
            del pending[matched_key]
            self._save_json(self._pending_path(platform), pending)
            user_id = str(matched_entry.get("user_id", "")).strip()
            user_name = str(matched_entry.get("user_name", "")).strip()
            self._approve_user(platform, user_id, user_name=user_name)
            return {"user_id": user_id, "user_name": user_name}

    def list_pending(self, platform: str | None = None) -> list[dict[str, Any]]:
        """List pending pairing requests without revealing plaintext codes.

        Args:
            platform (str | None): Optional channel filter.

        Returns:
            list[dict[str, Any]]: Pending request summaries.

        Examples:
            >>> import tempfile
            >>> PairingStore(Path(tempfile.mkdtemp())).list_pending()
            []
        """
        results: list[dict[str, Any]] = []
        with self._lock:
            platforms = [platform] if platform else self._all_platforms("pending")
            for name in platforms:
                self._cleanup_expired(name)
                pending = self._load_json(self._pending_path(name))
                for _entry_id, info in pending.items():
                    if not isinstance(info, dict):
                        continue
                    created_at = info.get("created_at")
                    if not isinstance(created_at, (int, float)):
                        continue
                    hash_val = info.get("hash")
                    code_display = hash_val[:8] if isinstance(hash_val, str) else "legacy"
                    results.append(
                        {
                            "platform": name,
                            "code": code_display,
                            "user_id": info.get("user_id", ""),
                            "user_name": info.get("user_name", ""),
                            "age_minutes": int((time.time() - created_at) / 60),
                        },
                    )
        return results

    def clear_pending(self, platform: str | None = None) -> int:
        """Clear pending pairing requests.

        Args:
            platform (str | None): Optional channel filter.

        Returns:
            int: Count removed.

        Examples:
            >>> import tempfile
            >>> PairingStore(Path(tempfile.mkdtemp())).clear_pending()
            0
        """
        with self._lock:
            count = 0
            platforms = [platform] if platform else self._all_platforms("pending")
            for name in platforms:
                pending = self._load_json(self._pending_path(name))
                count += len(pending)
                self._save_json(self._pending_path(name), {})
        return count

    def _is_rate_limited(self, platform: str, user_id: str) -> bool:
        """Return whether ``user_id`` is within the pairing rate limit.

        Args:
            platform (str): Channel adapter name.
            user_id (str): Requesting user id.

        Returns:
            bool: Rate-limit verdict.

        Examples:
            >>> PairingStore(Path("/tmp/w"))._is_rate_limited("telegram", "1")
            False
        """
        limits = self._load_json(self._rate_limit_path())
        key = f"{platform}:{str(user_id or '').strip()}"
        last_request = limits.get(key, 0)
        return (
            isinstance(last_request, (int, float))
            and (time.time() - last_request) < _RATE_LIMIT_SECONDS
        )

    def _record_rate_limit(self, platform: str, user_id: str) -> None:
        """Record a pairing code request timestamp for rate limiting.

        Args:
            platform (str): Channel adapter name.
            user_id (str): Requesting user id.

        Examples:
            >>> store = PairingStore(Path("/tmp/w"))
            >>> store._record_rate_limit("telegram", "1")
        """
        limits = self._load_json(self._rate_limit_path())
        limits[f"{platform}:{str(user_id or '').strip()}"] = time.time()
        self._save_json(self._rate_limit_path(), limits)

    def _is_locked_out(self, platform: str) -> bool:
        """Return whether ``platform`` is in failed-approval lockout.

        Args:
            platform (str): Channel adapter name.

        Returns:
            bool: Lockout verdict.

        Examples:
            >>> PairingStore(Path("/tmp/w"))._is_locked_out("telegram")
            False
        """
        limits = self._load_json(self._rate_limit_path())
        lockout_until = limits.get(f"_lockout:{platform}", 0)
        return isinstance(lockout_until, (int, float)) and time.time() < lockout_until

    def _record_failed_attempt(self, platform: str) -> None:
        """Increment failed approval counter and maybe start lockout.

        Args:
            platform (str): Channel adapter name.

        Examples:
            >>> store = PairingStore(Path("/tmp/w"))
            >>> store._record_failed_attempt("telegram")
        """
        limits = self._load_json(self._rate_limit_path())
        fail_key = f"_failures:{platform}"
        fails = int(limits.get(fail_key, 0)) + 1
        limits[fail_key] = fails
        if fails >= _MAX_FAILED_ATTEMPTS:
            limits[f"_lockout:{platform}"] = time.time() + _LOCKOUT_SECONDS
            limits[fail_key] = 0
            logger.warning(
                "pairing lockout platform={} duration_s={}",
                platform,
                _LOCKOUT_SECONDS,
            )
        self._save_json(self._rate_limit_path(), limits)

    def _cleanup_expired(self, platform: str) -> None:
        """Drop expired pending pairing entries for ``platform``.

        Args:
            platform (str): Channel adapter name.

        Examples:
            >>> store = PairingStore(Path("/tmp/w"))
            >>> store._cleanup_expired("telegram")
        """
        path = self._pending_path(platform)
        pending = self._load_json(path)
        now = time.time()
        expired: list[str] = []
        for entry_id, info in pending.items():
            if not isinstance(info, dict):
                expired.append(entry_id)
                continue
            created_at = info.get("created_at")
            if not isinstance(created_at, (int, float)):
                expired.append(entry_id)
                continue
            if (now - created_at) > _CODE_TTL_SECONDS:
                expired.append(entry_id)
        if expired:
            for entry_id in expired:
                del pending[entry_id]
            self._save_json(path, pending)

    def _all_platforms(self, suffix: str) -> list[str]:
        """List platform names that have on-disk ``suffix`` state files.

        Args:
            suffix (str): File suffix segment (``pending`` or ``approved``).

        Returns:
            list[str]: Platform names discovered on disk.

        Examples:
            >>> import tempfile
            >>> PairingStore(Path(tempfile.mkdtemp()))._all_platforms("pending")
            []
        """
        platforms: list[str] = []
        for path in self._dir.iterdir():
            if path.name.endswith(f"-{suffix}.json") and not path.name.startswith("_"):
                platforms.append(path.name.replace(f"-{suffix}.json", ""))
        return platforms


__all__ = ["PairingStore", "pairing_dir_for_content_root"]
