"""``.llmignore/`` layout helpers (``specs/09-security-scanner.md`` §2.2, §4.4).

The ``DEFAULT_INDEX_DENY`` frozenset lists path prefixes every LLM-facing indexer must skip (§4.4).

Module: sevn.security.llmignore
Depends: pathlib, sevn.config.defaults, sevn.config.workspace_config,
    sevn.security.llm_guard_scanner

Exports:
    resolve_llmignore_root — resolved llmignore directory from workspace + config.
    ensure_llmignore_layout — create ``.llmignore/{blocked,quarantine,incidents}`` when missing.
    is_llmignored — whether a path resolves under the guarded subtree.
    write_blocked_inbound — persist blocked inbound JSON (atomic write).
    write_blocked_feedback — persist Web App feedback block JSON.
    sweep_expired — TTL sweep of blocked / quarantine / incidents.
    assert_shadow_workspace_excludes_llmignore — shadow workspace guard.

Examples:
    >>> isinstance(DEFAULT_INDEX_DENY, frozenset)
    True
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from contextlib import suppress
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final

from sevn.config.defaults import (
    DEFAULT_LLMIGNORE_REL_PATH,
    DEFAULT_SCANNER_MAX_INBOUND_BYTES,
)
from sevn.config.workspace_config import (
    SecurityLlmignoreRetentionSubConfig,
    WorkspaceConfig,
)

if TYPE_CHECKING:
    from pathlib import Path

    from sevn.security.llm_guard_scanner import ScanResult

DEFAULT_INDEX_DENY: Final[frozenset[str]] = frozenset(
    (
        ".llmignore",
        ".llmignore/",
        ".llmignore/blocked",
        ".llmignore/blocked/",
        ".llmignore/quarantine",
        ".llmignore/quarantine/",
        ".llmignore/incidents",
        ".llmignore/incidents/",
    ),
)


def resolve_llmignore_root(workspace: Path, config: WorkspaceConfig | None) -> Path:
    """Return the absolute ``.llmignore`` directory (§5 ``security.llmignore.path``).

    Args:
        workspace (Path): Workspace content root.
        config (WorkspaceConfig | None): Parsed config, or ``None`` for defaults only.

    Returns:
        Path: Resolved directory under ``workspace``.

    Raises:
        ValueError: When the configured path escapes the workspace root.

    Examples:
        >>> from pathlib import Path
        >>> resolve_llmignore_root(Path("/tmp/w"), None) == Path("/tmp/w/.llmignore").resolve()
        True
    """
    wr = workspace.expanduser().resolve()
    rel = DEFAULT_LLMIGNORE_REL_PATH
    if config and config.security and config.security.llmignore and config.security.llmignore.path:
        rel = config.security.llmignore.path.strip().strip("/")
    root = (wr / rel).resolve()
    try:
        root.relative_to(wr)
    except ValueError as exc:
        msg = "security.llmignore.path must resolve under the workspace root"
        raise ValueError(msg) from exc
    return root


def ensure_llmignore_layout(workspace: Path, config: WorkspaceConfig | None = None) -> Path:
    """Create ``.llmignore/`` and standard subdirectories when absent (§2.2).

    Args:
        workspace (Path): Workspace content root.
        config (WorkspaceConfig | None): Parsed config for custom ``security.llmignore.path``.

    Returns:
        Path: Resolved ``.llmignore`` directory.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> ws = Path(tempfile.mkdtemp())
        >>> root = ensure_llmignore_layout(ws)
        >>> (root / "blocked").is_dir()
        True
    """
    root = resolve_llmignore_root(workspace, config)
    root.mkdir(parents=True, exist_ok=True)
    for name in ("blocked", "quarantine", "incidents"):
        (root / name).mkdir(parents=True, exist_ok=True)
    return root


def is_llmignored(path: Path, workspace: Path) -> bool:
    """Return True when ``path`` resolves under ``workspace/.llmignore/``.

    Args:
        path (Path): Candidate filesystem path.
        workspace (Path): Workspace content root.

    Returns:
        bool: True when the real path lies under the default llmignore subtree.

    Examples:
        >>> from pathlib import Path
        >>> ws = Path("/tmp/x")
        >>> is_llmignored(ws / ".llmignore" / "blocked" / "a.json", ws)
        True
    """
    wr = workspace.expanduser().resolve()
    guard = (wr / DEFAULT_LLMIGNORE_REL_PATH).resolve()
    try:
        target = path.expanduser().resolve()
    except OSError:
        return False
    try:
        target.relative_to(guard)
    except ValueError:
        return False
    return True


def _retention(cfg: WorkspaceConfig | None) -> SecurityLlmignoreRetentionSubConfig:
    """Return ``security.llmignore.retention_days`` or schema defaults.

    Args:
        cfg (WorkspaceConfig | None): Parsed workspace config when available.

    Returns:
        SecurityLlmignoreRetentionSubConfig: Effective retention thresholds.

    Examples:
        >>> isinstance(_retention(None).blocked, int)
        True
    """
    if cfg and cfg.security and cfg.security.llmignore and cfg.security.llmignore.retention_days:
        return cfg.security.llmignore.retention_days
    return SecurityLlmignoreRetentionSubConfig()


def sweep_expired(workspace: Path, cfg: object) -> int:
    """Delete expired artefacts under ``.llmignore/`` (mtime + TTL).

    Args:
        workspace (Path): Workspace content root.
        cfg (object): ``WorkspaceConfig`` or compatible (see ``resolve_llmignore_root``).

    Returns:
        int: Number of files removed (best-effort).

    Examples:
        >>> sweep_expired(Path("."), None)  # doctest: +SKIP
        0
    """
    wc = cfg if isinstance(cfg, WorkspaceConfig) else None
    root = resolve_llmignore_root(workspace, wc)
    ret = _retention(wc)
    import time as _time

    now = _time.time()
    removed = 0
    subdirs: tuple[tuple[str, int], ...] = (
        ("blocked", ret.blocked),
        ("quarantine", ret.quarantine),
        ("incidents", ret.incidents),
    )
    for name, days in subdirs:
        d = root / name
        if not d.is_dir():
            continue
        cutoff = now - float(days) * 86400.0
        for p in d.iterdir():
            try:
                if not p.is_file():
                    continue
                if p.stat().st_mtime >= cutoff:
                    continue
                p.unlink(missing_ok=True)
                removed += 1
            except OSError:
                continue
    return removed


def assert_shadow_workspace_excludes_llmignore(shadow_root: Path) -> None:
    """Fail fast when the shadow tree exposes ``.llmignore`` material (§4.4).

    Args:
        shadow_root (Path): Materialized shadow workspace directory.

    Raises:
        AssertionError: When the shadow tree is unsafe.

    Examples:
        >>> from pathlib import Path
        >>> import tempfile
        >>> sh = Path(tempfile.mkdtemp())
        >>> assert_shadow_workspace_excludes_llmignore(sh)
    """
    sr = shadow_root.expanduser().resolve()
    if not sr.exists():
        msg = f"shadow workspace missing: {sr}"
        raise AssertionError(msg)
    if (sr / ".llmignore").exists():
        msg = "shadow workspace must not contain a top-level .llmignore entry"
        raise AssertionError(msg)
    for p in sr.rglob("*"):
        if not p.is_symlink():
            continue
        try:
            target = p.resolve()
        except OSError:
            continue
        if ".llmignore" in target.parts:
            msg = f"shadow workspace symlink leaks .llmignore: {p} -> {target}"
            raise AssertionError(msg)


def _verdict_blob(verdict: ScanResult) -> dict[str, Any]:
    """Serialize ``ScanResult`` into blocked-artefact JSON ``verdict`` object.

    Args:
        verdict (ScanResult): Scanner outcome.

    Returns:
        dict[str, Any]: Mapping suitable for ``json.dumps``.

    Examples:
        >>> from sevn.security.llm_guard_scanner import BlockReason, ScanResult, ScanVerdict
        >>> vr = ScanResult(
        ...     verdict=ScanVerdict.block,
        ...     reasons=(BlockReason.policy,),
        ...     scores={},
        ...     provider_used=None,
        ...     details={},
        ... )
        >>> _verdict_blob(vr)["verdict"]
        'block'
    """
    return {
        "verdict": verdict.verdict.value,
        "reasons": [r.value for r in verdict.reasons],
        "scores": dict(verdict.scores),
        "provider_used": verdict.provider_used,
    }


def _blocked_path(
    blocked_dir: Path,
    *,
    created_at: datetime,
    canonical_bytes: bytes,
) -> Path:
    """Derive deterministic blocked JSON filename from canonical bytes hash.

    Args:
        blocked_dir (Path): Parent ``blocked/`` directory.
        created_at (datetime): Creation timestamp (timezone-aware).
        canonical_bytes (bytes): Serialized JSON body bytes.

    Returns:
        Path: ``<utc-ts>-<sha12>.json`` under ``blocked_dir``.

    Examples:
        >>> from pathlib import Path
        >>> from datetime import UTC, datetime
        >>> p = _blocked_path(
        ...     Path("/tmp/b"),
        ...     created_at=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
        ...     canonical_bytes=b"{}",
        ... )
        >>> p.name.endswith(".json")
        True
    """
    digest = hashlib.sha256(canonical_bytes).hexdigest()[:12]
    ts = created_at.astimezone(UTC).strftime("%Y%m%d%H%M%S")
    return blocked_dir / f"{ts}-{digest}.json"


def _atomic_write_json(final_path: Path, payload_bytes: bytes) -> None:
    """Write JSON bytes via temp file + ``os.replace`` (§10.2).

    Args:
        final_path (Path): Destination path under ``.llmignore/``.
        payload_bytes (bytes): Serialized JSON UTF-8 payload.

    Returns:
        None: Always.

    Examples:
        >>> from pathlib import Path
        >>> import tempfile
        >>> p = Path(tempfile.mkdtemp()) / "out.json"
        >>> _atomic_write_json(p, b"{}")
        >>> p.read_bytes()
        b'{}'
    """
    final_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=final_path.parent,
        prefix=".blocked-",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(payload_bytes)
        os.replace(tmp_name, final_path)
    except OSError:
        with suppress(OSError):
            os.unlink(tmp_name)
        raise


def write_blocked_inbound(
    workspace: Path,
    *,
    text: str,
    verdict: ScanResult,
    channel: str,
    user_id: str,
) -> Path:
    """Atomically write ``blocked/<ts>-<hash>.json`` for inbound blocks (§3.1).

    Args:
        workspace (Path): Workspace content root.
        text (str): Raw inbound UTF-8 text (stored verbatim in JSON).
        verdict (ScanResult): Scanner verdict payload.
        channel (str): Dispatch channel label.
        user_id (str): Channel-scoped user id.

    Returns:
        Path: Final JSON path under ``.llmignore/blocked/``.

    Examples:
        >>> from pathlib import Path
        >>> import tempfile
        >>> from sevn.security.llm_guard_scanner import BlockReason, ScanResult, ScanVerdict
        >>> td = Path(tempfile.mkdtemp())
        >>> vr = ScanResult(
        ...     verdict=ScanVerdict.block,
        ...     reasons=(BlockReason.policy,),
        ...     scores={},
        ...     provider_used=None,
        ...     details={},
        ... )
        >>> p = write_blocked_inbound(td, text="x", verdict=vr, channel="c", user_id="u")
        >>> p.suffix == ".json"
        True
    """
    root = (workspace.expanduser().resolve() / DEFAULT_LLMIGNORE_REL_PATH).resolve()
    blocked_dir = root / "blocked"
    if len(text.encode("utf-8")) > DEFAULT_SCANNER_MAX_INBOUND_BYTES:
        msg = (
            "blocked inbound text exceeds DEFAULT_SCANNER_MAX_INBOUND_BYTES "
            "(align gateway max-message with security.scanner.max_inbound_bytes)"
        )
        raise ValueError(msg)
    created = datetime.now(UTC)
    doc_minimal = {
        "schema_version": 1,
        "created_at": created.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "kind": "blocked_inbound",
        "channel": channel,
        "user_id": user_id,
        "text": text,
        "verdict": _verdict_blob(verdict),
    }
    raw = json.dumps(doc_minimal, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    body = raw.encode("utf-8")
    final = _blocked_path(blocked_dir, created_at=created, canonical_bytes=body)
    _atomic_write_json(final, body)
    return final


def write_blocked_feedback(
    workspace: Path,
    *,
    text: str,
    verdict: ScanResult,
    telegram_user_id: str,
) -> Path:
    """Persist a feedback submit block with ``channel=telegram_webapp_feedback`` (§2.2).

    Args:
        workspace (Path): Workspace content root.
        text (str): Raw feedback body.
        verdict (ScanResult): Scanner verdict payload.
        telegram_user_id (str): Telegram user id string.

    Returns:
        Path: Final JSON path under ``.llmignore/blocked/``.

    Examples:
        >>> from pathlib import Path
        >>> import tempfile
        >>> from sevn.security.llm_guard_scanner import ScanVerdict, ScanResult
        >>> td = Path(tempfile.mkdtemp())
        >>> vr = ScanResult(
        ...     verdict=ScanVerdict.allow,
        ...     reasons=(),
        ...     scores={},
        ...     provider_used=None,
        ...     details={},
        ... )
        >>> p = write_blocked_feedback(td, text="y", verdict=vr, telegram_user_id="1")
        >>> "telegram_webapp_feedback" in p.read_text(encoding="utf-8")
        True
    """
    root = (workspace.expanduser().resolve() / DEFAULT_LLMIGNORE_REL_PATH).resolve()
    blocked_dir = root / "blocked"
    if len(text.encode("utf-8")) > DEFAULT_SCANNER_MAX_INBOUND_BYTES:
        msg = (
            "blocked feedback text exceeds DEFAULT_SCANNER_MAX_INBOUND_BYTES "
            "(align gateway max-message with security.scanner.max_inbound_bytes)"
        )
        raise ValueError(msg)
    created = datetime.now(UTC)
    doc_minimal = {
        "schema_version": 1,
        "created_at": created.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "kind": "blocked_feedback",
        "channel": "telegram_webapp_feedback",
        "user_id": telegram_user_id,
        "text": text,
        "verdict": _verdict_blob(verdict),
    }
    raw = json.dumps(doc_minimal, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    body = raw.encode("utf-8")
    final = _blocked_path(blocked_dir, created_at=created, canonical_bytes=body)
    _atomic_write_json(final, body)
    return final
