"""OAuth helpers for the bundled ``google-workspace`` skill.

Module: sevn.skills.google_workspace
Depends: json, pathlib, subprocess, urllib, optional google-auth/google-api-python-client

Exports:
    GoogleWorkspacePaths — exported symbol.
    token_path — exported symbol.
    client_secret_path — exported symbol.
    pending_auth_path — exported symbol.
    paths — exported symbol.
    dry_run_requested — exported symbol.
    normalize_authorized_user_payload — exported symbol.
    load_token_payload — exported symbol.
    missing_scopes_from_payload — exported symbol.
    ensure_google_deps — exported symbol.
    install_deps — exported symbol.
    check_auth — exported symbol.
    check_auth_live — exported symbol.
    store_client_secret — exported symbol.
    get_auth_url — exported symbol.
    exchange_auth_code — exported symbol.
    revoke_token — exported symbol.
    get_credentials — exported symbol.
    build_service — exported symbol.
    gws_binary — exported symbol.
    get_valid_token_for_gws — exported symbol.
    run_gws — exported symbol.
    prefer_gws_enabled — exported symbol.
    use_gws_backend — §3.3 gws-first routing decision (logs Python fallback).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess  # nosec B404
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from loguru import logger

GOOGLE_WORKSPACE_SKILL_ID: Final[str] = "google-workspace"

SCOPES: Final[list[str]] = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/contacts.readonly",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/documents",
]

SERVICE_SCOPE_SETS: Final[dict[str, tuple[str, ...]]] = {
    "email": (
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.send",
        "https://www.googleapis.com/auth/gmail.modify",
    ),
    "calendar": ("https://www.googleapis.com/auth/calendar",),
    "drive": ("https://www.googleapis.com/auth/drive",),
    "sheets": ("https://www.googleapis.com/auth/spreadsheets",),
    "docs": ("https://www.googleapis.com/auth/documents",),
    "contacts": ("https://www.googleapis.com/auth/contacts.readonly",),
    "all": tuple(SCOPES),
}

_TOKEN_ENV: Final[str] = "SEVN_GOOGLE_TOKEN_PATH"
_CLIENT_SECRET_ENV: Final[str] = "SEVN_GOOGLE_CLIENT_SECRET_PATH"
_DRY_RUN_ENV: Final[str] = "SEVN_GOOGLE_DRY_RUN"
_GWS_BIN_ENV: Final[str] = "SEVN_GWS_BIN"
_GWS_CREDENTIALS_FILE_ENV: Final[str] = "GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE"
_GWS_TOKEN_ENV: Final[str] = "GOOGLE_WORKSPACE_CLI_TOKEN"

_DOT_SEVN_DIRNAME: Final[str] = ".sevn"
_TOKEN_FILENAME: Final[str] = "google_token.json"
_CLIENT_SECRET_FILENAME: Final[str] = "google_client_secret.json"
_PENDING_AUTH_FILENAME: Final[str] = "google_oauth_pending.json"
_LAST_AUTH_URL_FILENAME: Final[str] = "google_oauth_last_url.txt"

_DEFAULT_REDIRECT_URI: Final[str] = "http://localhost"
_GOOGLE_TOKEN_URI: Final[str] = "https://oauth2.googleapis.com/token"
_GOOGLE_REVOKE_URI: Final[str] = "https://oauth2.googleapis.com/revoke"
_GWS_TIMEOUT_SECONDS: Final[float] = 120.0
_TRUTHY: Final[frozenset[str]] = frozenset({"1", "true", "yes", "on"})
REQUIRED_PACKAGES: Final[tuple[str, ...]] = (
    "google-api-python-client",
    "google-auth-oauthlib",
    "google-auth-httplib2",
)
_AUTH_URI_HINT: Final[str] = (
    "google_workspace: optional Google auth libraries are not installed "
    "(install optional extra: uv pip install 'sevn[google-workspace]')"
)

if TYPE_CHECKING:
    from google.oauth2.credentials import Credentials


@dataclass(frozen=True)
class GoogleWorkspacePaths:
    """Workspace-scoped Google OAuth/auth-state file paths."""

    workspace: Path
    state_dir: Path
    token_path: Path
    client_secret_path: Path
    pending_auth_path: Path
    last_auth_url_path: Path


def token_path(workspace: Path) -> Path:
    """Return the Google token path for ``workspace``.

    Args:
        workspace (Path): Workspace content root.

    Returns:
        Path: Token JSON file path.

    Examples:
        >>> token_path(Path("/tmp/ws")).name
        'google_token.json'
    """
    override = os.environ.get(_TOKEN_ENV, "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return workspace.resolve() / _DOT_SEVN_DIRNAME / _TOKEN_FILENAME


def client_secret_path(workspace: Path) -> Path:
    """Return the Google client-secret path for ``workspace``.

    Args:
        workspace (Path): Workspace content root.

    Returns:
        Path: Client-secret JSON file path.

    Examples:
        >>> client_secret_path(Path("/tmp/ws")).name
        'google_client_secret.json'
    """
    override = os.environ.get(_CLIENT_SECRET_ENV, "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return workspace.resolve() / _DOT_SEVN_DIRNAME / _CLIENT_SECRET_FILENAME


def pending_auth_path(workspace: Path) -> Path:
    """Return the pending PKCE auth state path for ``workspace``.

    Args:
        workspace (Path): Workspace content root.

    Returns:
        Path: Pending auth JSON file path.

    Examples:
        >>> pending_auth_path(Path("/tmp/ws")).name
        'google_oauth_pending.json'
    """
    return workspace.resolve() / _DOT_SEVN_DIRNAME / _PENDING_AUTH_FILENAME


def paths(workspace: Path) -> GoogleWorkspacePaths:
    """Return grouped Google Workspace auth-state paths for ``workspace``.

    Args:
        workspace (Path): Parameter.

    Returns:
        GoogleWorkspacePaths: Result.

    Examples:
        >>> paths  # doctest: +SKIP
    """

    resolved = workspace.expanduser().resolve()
    return GoogleWorkspacePaths(
        workspace=resolved,
        state_dir=_dot_sevn_dir(resolved),
        token_path=token_path(resolved),
        client_secret_path=client_secret_path(resolved),
        pending_auth_path=pending_auth_path(resolved),
        last_auth_url_path=_last_auth_url_path(resolved),
    )


def dry_run_requested(
    argv: Sequence[str] | None = None,
    env: Mapping[str, str] | None = None,
) -> bool:
    """Return whether dry-run mode was requested via CLI or environment.

    Args:
        argv (Sequence[str] | None, optional): CLI argv slice.
        env (Mapping[str, str] | None, optional): Environment mapping; defaults to ``os.environ``.

    Returns:
        bool: ``True`` when dry-run is enabled.

    Examples:
        >>> dry_run_requested(["--dry-run"], {})
        True
        >>> dry_run_requested([], {"SEVN_GOOGLE_DRY_RUN": "1"})
        True
    """
    if any(str(arg).strip() == "--dry-run" for arg in argv or ()):
        return True
    mapping = os.environ if env is None else env
    return mapping.get(_DRY_RUN_ENV, "").strip().lower() in _TRUTHY


def normalize_authorized_user_payload(payload: Mapping[str, object]) -> dict[str, object]:
    """Normalize authorized-user JSON to the shape expected by google-auth.

    Args:
        payload (Mapping[str, object]): Raw token JSON mapping.

    Returns:
        dict[str, object]: Normalized payload with canonical ``scopes`` and ``token_uri`` fields.

    Examples:
        >>> normalize_authorized_user_payload({"scope": "a b"})["scopes"]
        ['a', 'b']
    """
    normalized: dict[str, object] = {str(key): value for key, value in payload.items()}
    scopes = _scope_values_from_payload(payload)
    if scopes:
        normalized["scopes"] = scopes
    normalized.setdefault("token_uri", _GOOGLE_TOKEN_URI)
    normalized.setdefault("type", "authorized_user")
    return normalized


def load_token_payload(workspace: Path) -> dict[str, object] | None:
    """Load and normalize the stored token payload for ``workspace``.

    Args:
        workspace (Path): Workspace content root.

    Returns:
        dict[str, object] | None: Normalized payload, or ``None`` when absent.

    Examples:
        >>> load_token_payload  # doctest: +SKIP
    """
    path = token_path(workspace)
    if not path.is_file():
        return None
    return normalize_authorized_user_payload(_load_json_object(path, label="token"))


def missing_scopes_from_payload(
    payload: Mapping[str, object] | None,
    required_scopes: Iterable[str] | None = None,
) -> list[str]:
    """Return required scopes missing from ``payload``.

    Args:
        payload (Mapping[str, object] | None): Authorized-user token payload.
        required_scopes (Iterable[str] | None, optional): Required scopes; defaults to :data:`SCOPES`.

    Returns:
        list[str]: Missing scopes in stable request order.

    Examples:
        >>> missing_scopes_from_payload({"scopes": [SCOPES[0]]}, [SCOPES[0], SCOPES[1]])
        ['https://www.googleapis.com/auth/gmail.send']
    """
    required = _unique_scopes(required_scopes or SCOPES)
    granted = set(_scope_values_from_payload(payload or {}))
    if "https://www.googleapis.com/auth/any-api" in granted:
        return []
    return [scope for scope in required if scope not in granted]


def ensure_google_deps() -> None:
    """Raise ``ImportError`` unless the optional Google client libraries are installed.

    Examples:
        >>> ensure_google_deps  # doctest: +SKIP
    """
    try:
        from google.auth.transport.requests import Request as _Request
        from google.oauth2.credentials import Credentials as _Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow as _InstalledAppFlow
        from googleapiclient.discovery import build as _build
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise ImportError(_AUTH_URI_HINT) from exc
    _ = (_Request, _Credentials, _InstalledAppFlow, _build)


def install_deps() -> dict[str, object]:
    """Install optional Google client libraries with ``uv pip``.

    Returns:
        dict[str, object]: Result.

    Examples:
        >>> install_deps  # doctest: +SKIP
    """

    try:
        ensure_google_deps()
    except ImportError:
        uv_bin = shutil.which("uv")
        if uv_bin is None:
            msg = (
                "google_workspace: uv not found on PATH; install deps with: "
                "uv pip install --python "
                f"{sys.executable} 'sevn[google-workspace]'"
            )
            logger.error(msg)
            raise RuntimeError(msg) from None
        command = [
            uv_bin,
            "pip",
            "install",
            "--python",
            sys.executable,
            *REQUIRED_PACKAGES,
        ]
        logger.info("google_workspace: installing optional deps via {}", " ".join(command))
        proc = subprocess.run(  # nosec B603
            command,
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            detail = proc.stderr.strip() or proc.stdout.strip() or "uv pip install failed"
            logger.error("google_workspace: {}", detail)
            raise RuntimeError(f"google_workspace: {detail}") from None
        ensure_google_deps()
        logger.info("google_workspace: optional Google client libraries installed")
        return {
            "status": "INSTALLED",
            "packages": list(REQUIRED_PACKAGES),
            "installer": "uv",
        }
    logger.debug("google_workspace: optional Google client libraries already installed")
    return {
        "status": "ALREADY_INSTALLED",
        "packages": list(REQUIRED_PACKAGES),
        "installer": "uv",
    }


def check_auth(workspace: Path) -> dict[str, object]:
    """Return offline Google Workspace auth status for ``workspace``.

    Args:
        workspace (Path): Parameter.

    Returns:
        dict[str, object]: Result.

    Examples:
        >>> check_auth  # doctest: +SKIP
    """
    token_file = token_path(workspace)
    client_secret_file = client_secret_path(workspace)
    pending_file = pending_auth_path(workspace)
    base: dict[str, object] = {
        "skill_id": GOOGLE_WORKSPACE_SKILL_ID,
        "token_path": str(token_file),
        "client_secret_path": str(client_secret_file),
        "pending_auth_path": str(pending_file),
        "has_client_secret": client_secret_file.is_file(),
        "has_pending_auth": pending_file.is_file(),
        "has_token": token_file.is_file(),
    }
    try:
        payload = load_token_payload(workspace)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {**base, "status": "TOKEN_CORRUPT", "error": str(exc)}
    if payload is None:
        return {
            **base,
            "status": "NOT_AUTHENTICATED",
            "missing_scopes": list(SCOPES),
            "scope_count": 0,
            "token_expired": False,  # nosec B105
            "refreshable": False,  # nosec B105
        }
    try:
        missing = missing_scopes_from_payload(payload)
        expiry = _parse_expiry(payload.get("expiry"))
    except (TypeError, ValueError) as exc:
        return {**base, "status": "TOKEN_CORRUPT", "error": str(exc)}
    refreshable = _payload_is_refreshable(payload)
    token_expired = expiry is not None and expiry <= _utcnow()
    status = "AUTHENTICATED"
    if missing:
        status = "MISSING_SCOPES"
    elif token_expired and not refreshable:
        status = "REFRESH_REQUIRED"
    return {
        **base,
        "status": status,
        "missing_scopes": missing,
        "scope_count": len(_scope_values_from_payload(payload)),
        "token_expired": token_expired,
        "refreshable": refreshable,
        "account": _string_or_none(payload.get("account")),
        "expiry": payload.get("expiry"),
    }


def check_auth_live(workspace: Path) -> dict[str, object]:
    """Return live auth status for ``workspace``, refreshing tokens when possible.

    Args:
        workspace (Path): Parameter.

    Returns:
        dict[str, object]: Result.

    Examples:
        >>> check_auth_live  # doctest: +SKIP
    """
    base = check_auth(workspace)
    if base["status"] in {"NOT_AUTHENTICATED", "TOKEN_CORRUPT"}:
        return {**base, "live": True}
    try:
        ensure_google_deps()
        from google.auth.exceptions import RefreshError
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        return {
            **base,
            "status": "DEPS_MISSING",
            "live": True,
            "error": str(exc),
        }
    try:
        credentials = get_credentials(workspace)
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        return {
            **base,
            "status": "DEPS_MISSING",
            "live": True,
            "error": str(exc),
        }
    except FileNotFoundError:
        return {**base, "status": "NOT_AUTHENTICATED", "live": True}
    except ValueError as exc:
        return {**base, "status": "TOKEN_CORRUPT", "live": True, "error": str(exc)}
    except RefreshError as exc:
        return {**base, "status": "REFRESH_FAILED", "live": True, "error": str(exc)}
    payload = normalize_authorized_user_payload(json.loads(credentials.to_json()))  # type: ignore[no-untyped-call]
    missing = missing_scopes_from_payload(payload)
    status = "MISSING_SCOPES" if missing else "AUTHENTICATED"
    return {
        **base,
        "status": status,
        "live": True,
        "missing_scopes": missing,
        "scope_count": len(_scope_values_from_payload(payload)),
        "token_expired": bool(getattr(credentials, "expired", False)),
        "credentials_valid": bool(getattr(credentials, "valid", False)),
        "expiry": payload.get("expiry"),
        "account": _string_or_none(payload.get("account")),
    }


def store_client_secret(workspace: Path, path: Path) -> dict[str, object]:
    """Validate and store a Google OAuth client-secret JSON file.

    Args:
        workspace (Path): Parameter.
        path (Path): Parameter.

    Returns:
        dict[str, object]: Result.

    Examples:
        >>> store_client_secret  # doctest: +SKIP
    """
    source = path.expanduser().resolve()
    payload = _load_json_object(source, label="client secret")
    client_type = _client_secret_client_type(payload)
    target = client_secret_path(workspace)
    _ensure_parent_dir(target)
    shutil.copyfile(source, target)
    _safe_unlink(pending_auth_path(workspace))
    _safe_unlink(_last_auth_url_path(workspace))
    return {
        "status": "CLIENT_SECRET_STORED",
        "client_type": client_type,
        "path": str(target),
        "source_path": str(source),
    }


def get_auth_url(workspace: Path, services: str | Iterable[str] = "all") -> None:
    """Write OAuth authorization state to disk for the requested Google service set.

    The authorization URL itself is written to ``last_auth_url_path``; setup scripts emit
    only file paths on stdout (read the URL from that file).

    Args:
        workspace (Path): Parameter.
        services (str | Iterable[str]): Parameter.

    Examples:
        >>> get_auth_url  # doctest: +SKIP
    """
    ensure_google_deps()
    from google_auth_oauthlib.flow import InstalledAppFlow

    _ = _load_client_secret_payload(workspace)
    service_names, requested_scopes = _services_to_scope_list(services)
    flow = InstalledAppFlow.from_client_secrets_file(
        str(client_secret_path(workspace)),
        requested_scopes,
        redirect_uri=_DEFAULT_REDIRECT_URI,
        autogenerate_code_verifier=True,
    )
    auth_url, state = flow.authorization_url(
        include_granted_scopes="true",
        prompt="consent",
    )
    pending_payload = {
        "status": "PENDING",
        "services": service_names,
        "scopes": requested_scopes,
        "state": state,
        "redirect_uri": flow.redirect_uri,
        "code_verifier": flow.code_verifier,
        "created_at": _utcnow().isoformat(),
    }
    _write_json_object(pending_auth_path(workspace), pending_payload)
    last_auth_url_file = _last_auth_url_path(workspace)
    last_auth_url_file.write_text(f"{auth_url}\n", encoding="utf-8")


def exchange_auth_code(workspace: Path, code_or_url: str) -> dict[str, object]:
    """Exchange an OAuth authorization code or redirect URL for a stored token.

    Args:
        workspace (Path): Parameter.
        code_or_url (str): Parameter.

    Returns:
        dict[str, object]: Result.

    Examples:
        >>> exchange_auth_code  # doctest: +SKIP
    """
    ensure_google_deps()
    from google_auth_oauthlib.flow import InstalledAppFlow

    _ = _load_client_secret_payload(workspace)
    pending = _load_json_object(pending_auth_path(workspace), label="pending auth")
    scopes = _scope_values_from_payload(pending)
    if not scopes:
        msg = "google_workspace: pending auth is missing requested scopes"
        raise ValueError(msg)
    flow = InstalledAppFlow.from_client_secrets_file(
        str(client_secret_path(workspace)),
        scopes,
        redirect_uri=str(pending.get("redirect_uri") or _DEFAULT_REDIRECT_URI),
        state=_string_or_none(pending.get("state")),
        code_verifier=_string_or_none(pending.get("code_verifier")),
    )
    raw = code_or_url.strip()
    auth_response = _extract_authorization_response(raw)
    if auth_response is not None:
        flow.fetch_token(authorization_response=auth_response)
    else:
        if not raw:
            msg = "google_workspace: auth code is required"
            raise ValueError(msg)
        flow.fetch_token(code=raw)
    credentials = flow.credentials
    _save_credentials(workspace, credentials)
    _safe_unlink(pending_auth_path(workspace))
    payload = load_token_payload(workspace)
    missing = missing_scopes_from_payload(payload, scopes)
    services_raw = pending.get("services")
    services_list = [str(item) for item in services_raw] if isinstance(services_raw, list) else []
    return {
        "status": "MISSING_SCOPES" if missing else "AUTHENTICATED",
        "token_path": str(token_path(workspace)),
        "services": services_list,
        "scopes": scopes,
        "missing_scopes": missing,
        "account": _string_or_none((payload or {}).get("account")),
    }


def revoke_token(workspace: Path) -> dict[str, object]:
    """Revoke the stored Google token and delete local token state.

    Args:
        workspace (Path): Parameter.

    Returns:
        dict[str, object]: Result.

    Examples:
        >>> revoke_token  # doctest: +SKIP
    """
    try:
        payload = load_token_payload(workspace)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {
            "status": "TOKEN_CORRUPT",
            "token_path": str(token_path(workspace)),
            "error": str(exc),
        }
    if payload is None:
        return {"status": "NOT_AUTHENTICATED", "token_path": str(token_path(workspace))}
    revocation_token = _string_or_none(payload.get("refresh_token")) or _string_or_none(
        payload.get("token"),
    )
    if not revocation_token:
        _safe_unlink(token_path(workspace))
        _safe_unlink(pending_auth_path(workspace))
        return {
            "status": "REVOKED",
            "token_path": str(token_path(workspace)),
            "revoked_remote": False,
            "local_only": True,
        }
    data = urllib.parse.urlencode({"token": revocation_token}).encode("utf-8")
    request = urllib.request.Request(
        _GOOGLE_REVOKE_URI,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    remote_ok = False
    http_status: int | None = None
    error_detail: str | None = None
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # nosec B310
            http_status = int(response.getcode())
            remote_ok = http_status == 200
    except urllib.error.HTTPError as exc:
        http_status = exc.code
        error_detail = str(exc)
        remote_ok = exc.code in {200, 400, 401}
    except urllib.error.URLError as exc:
        error_detail = str(exc)
    if remote_ok:
        _safe_unlink(token_path(workspace))
        _safe_unlink(pending_auth_path(workspace))
        return {
            "status": "REVOKED",
            "token_path": str(token_path(workspace)),
            "revoked_remote": http_status == 200,
            "http_status": http_status,
        }
    return {
        "status": "REVOKE_FAILED",
        "token_path": str(token_path(workspace)),
        "http_status": http_status,
        "error": error_detail or "google_workspace: token revoke request failed",
    }


def get_credentials(workspace: Path) -> Credentials:
    """Load, refresh if needed, persist, and return Google OAuth credentials.

    Args:
        workspace (Path): Parameter.

    Returns:
        Credentials: Result.

    Examples:
        >>> get_credentials  # doctest: +SKIP
    """
    ensure_google_deps()
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    payload = load_token_payload(workspace)
    if payload is None:
        msg = "google_workspace: no token stored; run auth first"
        raise FileNotFoundError(msg)
    scopes = _scope_values_from_payload(payload) or list(SCOPES)
    credentials = Credentials.from_authorized_user_info(payload, scopes)  # type: ignore[no-untyped-call]
    if bool(getattr(credentials, "expired", False)) or not bool(
        getattr(credentials, "valid", False)
    ):
        if not getattr(credentials, "refresh_token", None):
            msg = "google_workspace: token is expired or invalid and cannot be refreshed"
            raise ValueError(msg)
        credentials.refresh(Request())
        _save_credentials(workspace, credentials)
    elif _payload_needs_resave(payload):
        _save_credentials(workspace, credentials)
    return credentials  # type: ignore[no-any-return]


def build_service(workspace: Path, api: str, version: str) -> Any:
    """Return a google-api-python-client service bound to workspace credentials.

    Args:
        workspace (Path): Parameter.
        api (str): Parameter.
        version (str): Parameter.

    Returns:
        Any: Result.

    Examples:
        >>> build_service  # doctest: +SKIP
    """
    ensure_google_deps()
    from googleapiclient.discovery import build

    return build(api, version, credentials=get_credentials(workspace), cache_discovery=False)


def gws_binary() -> str | None:
    """Return the configured ``gws`` binary path, or ``None`` when unavailable.

    Returns:
        str | None: Result.

    Examples:
        >>> gws_binary  # doctest: +SKIP
    """

    override = os.environ.get(_GWS_BIN_ENV, "").strip()
    if override:
        return str(Path(override).expanduser())
    return shutil.which("gws")


def get_valid_token_for_gws(workspace: Path) -> str:
    """Return a refreshed Google access token for the optional ``gws`` CLI.

    Args:
        workspace (Path): Parameter.

    Returns:
        str: Result.

    Examples:
        >>> get_valid_token_for_gws  # doctest: +SKIP
    """

    token = _string_or_none(getattr(get_credentials(workspace), "token", None))
    if token is None:
        msg = "google_workspace: refreshed credentials did not expose an access token"
        raise ValueError(msg)
    return token


def run_gws(
    workspace: Path,
    parts: list[str],
    params: Mapping[str, object] | None = None,
    body: object | None = None,
) -> dict[str, object]:
    """Run ``gws`` with refreshed auth env and return parsed output.

    Args:
        workspace (Path): Parameter.
        parts (list[str]): Parameter.
        params (Mapping[str, object] | None): Parameter.
        body (object | None): Parameter.

    Returns:
        dict[str, object]: Result.

    Examples:
        >>> run_gws  # doctest: +SKIP
    """

    binary = gws_binary()
    if binary is None:
        msg = "google_workspace: gws CLI not found on PATH"
        raise FileNotFoundError(msg)
    command = [binary, *[str(part) for part in parts], *_gws_params_argv(params)]
    proc = subprocess.run(  # nosec B603
        command,
        input=_gws_stdin_body(body),
        capture_output=True,
        text=True,
        check=False,
        env=_gws_environment(workspace),
        timeout=_GWS_TIMEOUT_SECONDS,
    )
    stdout = proc.stdout.strip()
    stderr = proc.stderr.strip()
    if proc.returncode != 0:
        detail = stderr or stdout or f"exit {proc.returncode}"
        logger.error("google_workspace: gws failed ({}): {}", " ".join(command), detail)
        raise RuntimeError(f"google_workspace: gws failed: {detail}")
    if not stdout:
        return {}
    try:
        parsed = json.loads(stdout)
    except json.JSONDecodeError:
        return {"stdout": stdout}
    if isinstance(parsed, dict):
        return {str(key): value for key, value in parsed.items()}
    return {"data": parsed}


def prefer_gws_enabled(workspace: Path) -> bool:
    """Return the effective ``skills.google_workspace.prefer_gws`` setting.

    Args:
        workspace (Path): Parameter.

    Returns:
        bool: Result.

    Examples:
        >>> prefer_gws_enabled  # doctest: +SKIP
    """

    settings = _google_workspace_settings_from_disk(workspace)
    return bool(getattr(settings, "prefer_gws", True))


def use_gws_backend(workspace: Path) -> bool:
    """Return True when §3.3 should route through ``gws`` (prefer_gws + on PATH).

    When ``prefer_gws`` is set but ``gws`` is missing, logs that the Python client
    backend is used so the fallback is observable to operators and tests.

    Args:
        workspace (Path): Workspace root with ``sevn.json``.

    Returns:
        bool: True when handlers should call ``run_gws`` instead of ``build_service``.

    Examples:
        >>> use_gws_backend  # doctest: +SKIP
    """

    prefer = prefer_gws_enabled(workspace)
    binary = gws_binary()
    if prefer and binary is not None:
        logger.debug("google_workspace: execution backend=gws ({})", binary)
        return True
    if prefer:
        logger.info(
            "google_workspace: prefer_gws=true but gws not on PATH; using Python backend",
        )
    else:
        logger.debug("google_workspace: execution backend=python (prefer_gws=false)")
    return False


def _dot_sevn_dir(workspace: Path) -> Path:
    """_dot_sevn_dir helper.

    Args:
        workspace (Path): Parameter.

    Returns:
        Path: Result.

    Examples:
        >>> _dot_sevn_dir  # doctest: +SKIP
    """
    return workspace.resolve() / _DOT_SEVN_DIRNAME


def _google_workspace_settings_from_disk(workspace: Path) -> Any:
    """_google_workspace_settings_from_disk helper.

    Args:
        workspace (Path): Parameter.

    Returns:
        Any: Result.

    Examples:
        >>> _google_workspace_settings_from_disk  # doctest: +SKIP
    """
    from sevn.config.workspace_config import google_workspace_settings, parse_workspace_config

    sevn_json_path = workspace.resolve() / "sevn.json"
    if not sevn_json_path.is_file():
        return google_workspace_settings(None)
    try:
        with sevn_json_path.open("r", encoding="utf-8") as handle:
            raw_doc = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return google_workspace_settings(None)
    if not isinstance(raw_doc, dict):
        return google_workspace_settings(None)
    try:
        return google_workspace_settings(parse_workspace_config(raw_doc))
    except ValueError:
        return google_workspace_settings(None)


def _gws_environment(workspace: Path) -> dict[str, str]:
    """_gws_environment helper.

    Args:
        workspace (Path): Parameter.

    Returns:
        dict[str, str]: Result.

    Examples:
        >>> _gws_environment  # doctest: +SKIP
    """
    env = dict(os.environ)
    token_file = token_path(workspace)
    try:
        env[_GWS_TOKEN_ENV] = get_valid_token_for_gws(workspace)
    except (FileNotFoundError, ImportError, ValueError):
        if token_file.is_file():
            env[_GWS_CREDENTIALS_FILE_ENV] = str(token_file)
        else:
            raise
    return env


def _gws_params_argv(params: Mapping[str, object] | None) -> list[str]:
    """_gws_params_argv helper.

    Args:
        params (Mapping[str, object] | None): Parameter.

    Returns:
        list[str]: Result.

    Examples:
        >>> _gws_params_argv  # doctest: +SKIP
    """
    argv: list[str] = []
    if not params:
        return argv
    for key, raw_value in params.items():
        flag_name = str(key).strip().replace("_", "-")
        if not flag_name:
            continue
        flag = flag_name if flag_name.startswith("-") else f"--{flag_name}"
        if raw_value is None or raw_value is False:
            continue
        if raw_value is True:
            argv.append(flag)
            continue
        if isinstance(raw_value, Sequence) and not isinstance(raw_value, (str, bytes)):
            for item in raw_value:
                argv.extend([flag, str(item)])
            continue
        if isinstance(raw_value, Mapping):
            argv.extend([flag, json.dumps(dict(raw_value), sort_keys=True)])
            continue
        argv.extend([flag, str(raw_value)])
    return argv


def _gws_stdin_body(body: object | None) -> str | None:
    """_gws_stdin_body helper.

    Args:
        body (object | None): Parameter.

    Returns:
        str | None: Result.

    Examples:
        >>> _gws_stdin_body  # doctest: +SKIP
    """
    if body is None:
        return None
    if isinstance(body, str):
        return body
    return json.dumps(body)


def _last_auth_url_path(workspace: Path) -> Path:
    """_last_auth_url_path helper.

    Args:
        workspace (Path): Parameter.

    Returns:
        Path: Result.

    Examples:
        >>> _last_auth_url_path  # doctest: +SKIP
    """
    return _dot_sevn_dir(workspace) / _LAST_AUTH_URL_FILENAME


def _ensure_parent_dir(path: Path) -> None:
    """_ensure_parent_dir helper.

    Args:
        path (Path): Parameter.

    Examples:
        >>> _ensure_parent_dir  # doctest: +SKIP
    """
    path.parent.mkdir(parents=True, exist_ok=True)


def _safe_unlink(path: Path) -> None:
    """_safe_unlink helper.

    Args:
        path (Path): Parameter.

    Examples:
        >>> _safe_unlink  # doctest: +SKIP
    """
    try:
        path.unlink()
    except FileNotFoundError:
        return


def _load_json_object(path: Path, *, label: str) -> dict[str, object]:
    """_load_json_object helper.

    Args:
        path (Path): Parameter.
        label (str): Parameter.

    Returns:
        dict[str, object]: Result.

    Examples:
        >>> _load_json_object  # doctest: +SKIP
    """
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        msg = f"google_workspace: {label} JSON at {path} must be an object"
        raise ValueError(msg)
    return {str(key): value for key, value in data.items()}


def _write_json_object(path: Path, payload: Mapping[str, object]) -> None:
    """_write_json_object helper.

    Args:
        path (Path): Parameter.
        payload (Mapping[str, object]): Parameter.

    Examples:
        >>> _write_json_object  # doctest: +SKIP
    """
    _ensure_parent_dir(path)
    path.write_text(
        json.dumps(dict(payload), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _utcnow() -> datetime:
    """_utcnow helper.

    Returns:
        datetime: Result.

    Examples:
        >>> _utcnow  # doctest: +SKIP
    """
    return datetime.now(tz=UTC)


def _scope_values_from_payload(payload: Mapping[str, object]) -> list[str]:
    """_scope_values_from_payload helper.

    Args:
        payload (Mapping[str, object]): Parameter.

    Returns:
        list[str]: Result.

    Examples:
        >>> _scope_values_from_payload  # doctest: +SKIP
    """
    collected: list[str] = []
    for key in ("scopes", "granted_scopes", "scope"):
        raw = payload.get(key)
        if isinstance(raw, str):
            pieces = [piece.strip() for piece in raw.replace(",", " ").split() if piece.strip()]
        elif isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
            pieces = [str(piece).strip() for piece in raw if str(piece).strip()]
        else:
            pieces = []
        for scope in pieces:
            if scope not in collected:
                collected.append(scope)
    return collected


def _unique_scopes(values: Iterable[str]) -> list[str]:
    """_unique_scopes helper.

    Args:
        values (Iterable[str]): Parameter.

    Returns:
        list[str]: Result.

    Examples:
        >>> _unique_scopes  # doctest: +SKIP
    """
    unique: list[str] = []
    for value in values:
        scope = str(value).strip()
        if scope and scope not in unique:
            unique.append(scope)
    return unique


def _parse_expiry(value: object) -> datetime | None:
    """_parse_expiry helper.

    Args:
        value (object): Parameter.

    Returns:
        datetime | None: Result.

    Examples:
        >>> _parse_expiry  # doctest: +SKIP
    """
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _payload_is_refreshable(payload: Mapping[str, object]) -> bool:
    """_payload_is_refreshable helper.

    Args:
        payload (Mapping[str, object]): Parameter.

    Returns:
        bool: Result.

    Examples:
        >>> _payload_is_refreshable  # doctest: +SKIP
    """
    return all(
        _string_or_none(payload.get(field))
        for field in ("refresh_token", "client_id", "client_secret")
    )


def _payload_needs_resave(payload: Mapping[str, object]) -> bool:
    """_payload_needs_resave helper.

    Args:
        payload (Mapping[str, object]): Parameter.

    Returns:
        bool: Result.

    Examples:
        >>> _payload_needs_resave  # doctest: +SKIP
    """
    return "scopes" not in payload and "scope" in payload


def _string_or_none(value: object) -> str | None:
    """_string_or_none helper.

    Args:
        value (object): Parameter.

    Returns:
        str | None: Result.

    Examples:
        >>> _string_or_none  # doctest: +SKIP
    """
    if isinstance(value, str):
        text = value.strip()
        if text:
            return text
    return None


def _client_secret_client_type(payload: Mapping[str, object]) -> str:
    """_client_secret_client_type helper.

    Args:
        payload (Mapping[str, object]): Parameter.

    Returns:
        str: Result.

    Examples:
        >>> _client_secret_client_type  # doctest: +SKIP
    """
    if isinstance(payload.get("installed"), dict):
        return "installed"
    if isinstance(payload.get("web"), dict):
        return "web"
    msg = "google_workspace: client secret JSON must contain an 'installed' or 'web' object"
    raise ValueError(msg)


def _load_client_secret_payload(workspace: Path) -> dict[str, object]:
    """_load_client_secret_payload helper.

    Args:
        workspace (Path): Parameter.

    Returns:
        dict[str, object]: Result.

    Examples:
        >>> _load_client_secret_payload  # doctest: +SKIP
    """
    path = client_secret_path(workspace)
    if not path.is_file():
        msg = f"google_workspace: client secret not found at {path}"
        raise FileNotFoundError(msg)
    payload = _load_json_object(path, label="client secret")
    _ = _client_secret_client_type(payload)
    return payload


def _services_to_scope_list(services: str | Iterable[str]) -> tuple[list[str], list[str]]:
    """_services_to_scope_list helper.

    Args:
        services (str | Iterable[str]): Parameter.

    Returns:
        tuple[list[str], list[str]]: Result.

    Examples:
        >>> _services_to_scope_list  # doctest: +SKIP
    """
    if isinstance(services, str):
        requested_services = [
            part.strip().lower() for part in services.replace(",", " ").split() if part.strip()
        ]
    else:
        requested_services = []
        for item in services:
            requested_services.extend(
                [
                    part.strip().lower()
                    for part in str(item).replace(",", " ").split()
                    if part.strip()
                ],
            )
    if not requested_services:
        requested_services = ["all"]
    if "all" in requested_services:
        requested_services = ["all"]
    invalid = sorted(set(requested_services) - set(SERVICE_SCOPE_SETS))
    if invalid:
        joined = ", ".join(invalid)
        msg = f"google_workspace: unknown service set(s): {joined}"
        raise ValueError(msg)
    scopes: list[str] = []
    for service in requested_services:
        for scope in SERVICE_SCOPE_SETS[service]:
            if scope not in scopes:
                scopes.append(scope)
    return requested_services, scopes


def _extract_authorization_response(value: str) -> str | None:
    """_extract_authorization_response helper.

    Args:
        value (str): Parameter.

    Returns:
        str | None: Result.

    Examples:
        >>> _extract_authorization_response  # doctest: +SKIP
    """
    if not value:
        return None
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme not in {"http", "https"}:
        return None
    query = urllib.parse.parse_qs(parsed.query)
    if query.get("error"):
        msg = f"google_workspace: authorization failed: {query['error'][0]}"
        raise ValueError(msg)
    if query.get("code"):
        return value
    return None


def _save_credentials(workspace: Path, credentials: Any) -> None:
    """_save_credentials helper.

    Args:
        workspace (Path): Parameter.
        credentials (Credentials): Parameter.

    Examples:
        >>> _save_credentials  # doctest: +SKIP
    """
    payload = normalize_authorized_user_payload(json.loads(credentials.to_json()))
    _write_json_object(token_path(workspace), payload)


__all__ = [
    "GOOGLE_WORKSPACE_SKILL_ID",
    "REQUIRED_PACKAGES",
    "SCOPES",
    "SERVICE_SCOPE_SETS",
    "GoogleWorkspacePaths",
    "build_service",
    "check_auth",
    "check_auth_live",
    "client_secret_path",
    "dry_run_requested",
    "ensure_google_deps",
    "exchange_auth_code",
    "get_auth_url",
    "get_credentials",
    "get_valid_token_for_gws",
    "gws_binary",
    "install_deps",
    "load_token_payload",
    "missing_scopes_from_payload",
    "normalize_authorized_user_payload",
    "paths",
    "pending_auth_path",
    "prefer_gws_enabled",
    "revoke_token",
    "run_gws",
    "store_client_secret",
    "token_path",
    "use_gws_backend",
]
