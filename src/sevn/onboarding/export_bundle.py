"""Export / import a workspace bundle (secrets + ``sevn.json``) as a ``.env`` file.

``sevn export-secrets <workspace_root> --to-file <file>.env`` decrypts the workspace
secrets store and writes a single plaintext ``.env`` file that also embeds the full
``sevn.json`` document and the bot name. ``sevn onboard fast <file>`` consumes the same
file to recreate a bot non-interactively (`specs/22-onboarding.md`, `specs/06-secrets.md`).

Module: sevn.onboarding.export_bundle
Depends: copy, datetime, json, os, sys, pathlib, sevn.config.*, sevn.secrets.migrate,
    sevn.security.secrets.*, sevn.onboarding.seed, sevn.workspace.layout

Exports:
    ExportBundle — parsed ``version`` / ``bot_name`` / ``config_doc`` / ``secrets`` /
        ``provider_bindings``.
    ExportBundleError — base failure carrying a CLI ``exit_code``.
    ExportResult — outcome of a successful export write.
    build_export_text — render a bundle to ``.env`` text.
    parse_export_text — parse ``.env`` text into an ``ExportBundle``.
    bundle_seed_secrets — merge secrets + provider binding aliases for ``onboard fast``.
    provider_bindings_from_config_doc — derive provider→ref map from assigned slots (D6).
    resolve_export_workspace — locate ``sevn.json`` + content root for a workspace path.
    run_export_secrets — decrypt the store and write the bundle file (async).
"""

from __future__ import annotations

import asyncio
import copy
import json
import os
import shutil
import subprocess  # nosec B404
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from loguru import logger

from sevn.config.model_resolution import ModelSlot, resolve_model_slot
from sevn.config.provider_registry import (
    provider_credential_ref,
    resolve_provider_for_model_id,
)
from sevn.config.workspace_config import (
    WorkspaceConfig,
    effective_encrypted_file_key_source,
    parse_workspace_config,
)
from sevn.onboarding.seed import resolve_agent_display_name
from sevn.secrets.migrate import encrypted_file_backend_for_workspace
from sevn.security.secrets.errors import SecretsStoreCorruptError
from sevn.security.secrets.factory import resolve_primary_encrypted_store_path
from sevn.security.secrets.passphrase_prime import (
    fetch_unlock_secret_from_keychain,
    unlock_env_var_for,
)
from sevn.workspace.layout import WorkspaceLayout

EXPORT_FORMAT_VERSION = 1

_VERSION_KEY = "SEVN_EXPORT_VERSION"
_BOT_NAME_KEY = "SEVN_BOT_NAME"
_CONFIG_PREFIX = "config."
_PROVIDERS_SECTION_HEADER = "# --- providers (name → key alias) ---"
_PROVIDER_BINDING_PREFIX = "providers."
_PROVIDER_BINDING_SUFFIX = ".api_key"


class ExportBundleError(Exception):
    """Export/import failure carrying a CLI exit code.

    Args:
        message (str): Operator-facing error text.
        exit_code (int): CLI exit code (``2`` usage, ``3`` auth, ``4`` precondition).

    Examples:
        >>> ExportBundleError("bad", exit_code=2).exit_code
        2
    """

    def __init__(self, message: str, *, exit_code: int = 4) -> None:
        """Store ``message`` and the CLI ``exit_code`` for the command layer.

        Args:
            message (str): Operator-facing error text.
            exit_code (int): CLI exit code to surface.

        Examples:
            >>> ExportBundleError("x").exit_code
            4
        """
        super().__init__(message)
        self.message = message
        self.exit_code = exit_code


@dataclass(frozen=True)
class ExportBundle:
    """Parsed export bundle.

    Examples:
        >>> ExportBundle(version=1, bot_name="Sevn", config_doc={}, secrets={}).bot_name
        'Sevn'
    """

    version: int
    bot_name: str
    config_doc: dict[str, Any]
    secrets: dict[str, str] = field(default_factory=dict)
    provider_bindings: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ExportResult:
    """Outcome of a successful :func:`run_export_secrets`.

    Examples:
        >>> ExportResult(path=Path("/tmp/x.env"), secret_count=0, bot_name="Sevn").secret_count
        0
    """

    path: Path
    secret_count: int
    bot_name: str
    git_unignored_warning: bool = False


def _git_ignored(path: Path) -> bool | None:
    """Return whether ``path.name`` is ignored inside ``path.parent``'s git work tree.

    Args:
        path (Path): Destination file path (uses ``path.parent`` as ``git -C`` root).

    Returns:
        bool | None: ``True`` when ignored, ``False`` when inside a repo but not ignored,
            ``None`` when not in a git work tree or git is unavailable.

    Examples:
        >>> _git_ignored.__name__
        '_git_ignored'
    """
    if shutil.which("git") is None:
        return None
    try:
        proc = subprocess.run(  # nosec
            ["git", "-C", str(path.parent), "check-ignore", "-q", path.name],
            capture_output=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode == 0:
        return True
    if proc.returncode == 1:
        return False
    return None


def _encode_env_value(value: str) -> str:
    """Render one secret/value for a ``.env`` line, quoting only when unsafe.

    Args:
        value (str): Plaintext value.

    Returns:
        str: Raw value when safe, else a JSON-quoted string (single line).

    Examples:
        >>> _encode_env_value("sk-123")
        'sk-123'
        >>> _encode_env_value("a\\nb")
        '"a\\\\nb"'
    """
    unsafe = "\n" in value or "\r" in value or value.strip() != value or value[:1] in {'"', "'"}
    return json.dumps(value, ensure_ascii=False) if unsafe else value


def _decode_env_value(raw: str) -> str:
    """Decode the right-hand side of a ``.env`` line written by :func:`_encode_env_value`.

    Args:
        raw (str): Text after the first ``=`` on a line.

    Returns:
        str: Decoded plaintext.

    Examples:
        >>> _decode_env_value("sk-123")
        'sk-123'
        >>> _decode_env_value('"a\\\\nb"')
        'a\\nb'
    """
    text = raw.strip()
    if len(text) >= 2 and text.startswith('"') and text.endswith('"'):
        try:
            decoded = json.loads(text)
        except json.JSONDecodeError:
            return text
        if isinstance(decoded, str):
            return decoded
    return text


def _encode_config_value(value: Any) -> str:
    """Render one flattened config leaf, keeping strings bare when unambiguous.

    Strings are written verbatim unless they are empty, need whitespace/newline
    protection, or would be misread as a non-string JSON scalar (e.g. ``"3001"``,
    ``"true"``). Non-string scalars and empty containers round-trip via JSON.

    Args:
        value (Any): Scalar leaf (str/int/float/bool/None) or empty ``{}`` / ``[]``.

    Returns:
        str: Encoded right-hand side for a ``config.*`` line.

    Examples:
        >>> _encode_config_value("127.0.0.1")
        '127.0.0.1'
        >>> _encode_config_value(3001)
        '3001'
        >>> _encode_config_value("3001")
        '"3001"'
        >>> _encode_config_value(True)
        'true'
    """
    if isinstance(value, str):
        if value == "":
            return '""'
        if "\n" in value or "\r" in value or value.strip() != value or value[:1] in {'"', "'"}:
            return json.dumps(value, ensure_ascii=False)
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return value
        return value if isinstance(parsed, str) else json.dumps(value, ensure_ascii=False)
    return json.dumps(value, ensure_ascii=False)


def _decode_config_value(raw: str) -> Any:
    """Decode a flattened config leaf written by :func:`_encode_config_value`.

    Args:
        raw (str): Text after the first ``=`` on a ``config.*`` line.

    Returns:
        Any: Typed scalar (str/int/float/bool/None) or empty container.

    Examples:
        >>> _decode_config_value("3001")
        3001
        >>> _decode_config_value("127.0.0.1")
        '127.0.0.1'
        >>> _decode_config_value('"3001"')
        '3001'
        >>> _decode_config_value("true")
        True
    """
    text = raw.strip()
    if text == "":
        return ""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _flatten_config(value: Any, prefix: str = "") -> dict[str, Any]:
    """Flatten a nested ``sevn.json`` document to dotted ``path -> leaf`` pairs.

    Object keys and list indices both become dot-separated segments; empty objects
    and lists are preserved as leaf values.

    Args:
        value (Any): Config sub-tree.
        prefix (str): Accumulated dotted path.

    Returns:
        dict[str, Any]: Flat map of dotted paths to scalar/empty-container leaves.

    Examples:
        >>> _flatten_config({"a": {"b": [1, 2]}}) == {"a.b.0": 1, "a.b.1": 2}
        True
    """
    out: dict[str, Any] = {}
    if isinstance(value, dict) and value:
        for key, sub in value.items():
            out.update(_flatten_config(sub, f"{prefix}.{key}" if prefix else str(key)))
    elif isinstance(value, list) and value:
        for idx, sub in enumerate(value):
            out.update(_flatten_config(sub, f"{prefix}.{idx}" if prefix else str(idx)))
    else:
        out[prefix] = value
    return out


def _flat_sort_key(flat_key: str) -> list[tuple[int, int | str]]:
    """Order flat keys naturally, with numeric segments sorted as integers.

    Args:
        flat_key (str): Dotted flat key.

    Returns:
        list[tuple[int, int | str]]: Comparable per-segment sort key.

    Examples:
        >>> _flat_sort_key("a.10") < _flat_sort_key("a.2")
        False
    """
    return [(0, int(part)) if part.isdigit() else (1, part) for part in flat_key.split(".")]


def _listify(node: Any) -> Any:
    """Convert dicts whose keys are contiguous ``0..n-1`` integers back into lists.

    Args:
        node (Any): Partially rebuilt structure (dicts keyed by path segments).

    Returns:
        Any: Structure with array-shaped dicts converted to lists.

    Examples:
        >>> _listify({"0": "a", "1": "b"})
        ['a', 'b']
        >>> _listify({"x": "y"})
        {'x': 'y'}
    """
    if not isinstance(node, dict):
        return node
    converted = {key: _listify(sub) for key, sub in node.items()}
    keys = list(converted)
    if keys and all(key.isdigit() for key in keys):
        idxs = sorted(int(key) for key in keys)
        if idxs == list(range(len(idxs))):
            return [converted[str(i)] for i in idxs]
    return converted


def _unflatten_config(flat: dict[str, Any]) -> dict[str, Any]:
    """Rebuild a nested ``sevn.json`` document from dotted ``path -> leaf`` pairs.

    Args:
        flat (dict[str, Any]): Flat map produced by :func:`_flatten_config`.

    Returns:
        dict[str, Any]: Reconstructed nested document.

    Examples:
        >>> _unflatten_config({"a.b.0": 1, "a.b.1": 2}) == {"a": {"b": [1, 2]}}
        True
    """
    root: dict[str, Any] = {}
    for flat_key, value in flat.items():
        parts = flat_key.split(".")
        cursor = root
        for part in parts[:-1]:
            nxt = cursor.get(part)
            if not isinstance(nxt, dict):
                nxt = {}
                cursor[part] = nxt
            cursor = nxt
        cursor[parts[-1]] = value
    result = _listify(root)
    return result if isinstance(result, dict) else {}


def _parse_provider_binding_key(key: str) -> str | None:
    """Return provider name when ``key`` is ``providers.<name>.api_key``.

    Args:
        key (str): Top-level export line key (not ``config.*``).

    Returns:
        str | None: Provider registry name, or ``None`` when not a binding line.

    Examples:
        >>> _parse_provider_binding_key("providers.minimax.api_key")
        'minimax'
        >>> _parse_provider_binding_key("SEVN_PROVIDER_API_KEY") is None
        True
    """
    if not key.startswith(_PROVIDER_BINDING_PREFIX) or not key.endswith(_PROVIDER_BINDING_SUFFIX):
        return None
    middle = key[len(_PROVIDER_BINDING_PREFIX) : -len(_PROVIDER_BINDING_SUFFIX)]
    if not middle or "." in middle:
        return None
    return middle


def _secret_alias_from_ref(ref: str) -> str | None:
    """Extract store alias from a ``${SECRET:alias}`` credential ref.

    Args:
        ref (str): Config or binding credential reference.

    Returns:
        str | None: Store alias when the ref matches ``${SECRET:…}``.

    Examples:
        >>> _secret_alias_from_ref("${SECRET:SEVN_SECRET_MINIMAX}")
        'SEVN_SECRET_MINIMAX'
    """
    prefix = "${SECRET:"
    if ref.startswith(prefix) and ref.endswith("}"):
        alias = ref[len(prefix) : -1].strip()
        return alias or None
    return None


def _parse_config_for_provider_export(config_doc: dict[str, Any]) -> WorkspaceConfig | None:
    """Parse ``config_doc`` for export pairing, tolerating missing optional gateway fields.

    Args:
        config_doc (dict[str, Any]): Source ``sevn.json`` document.

    Returns:
        WorkspaceConfig | None: Parsed config when valid or patchable; else ``None``.

    Examples:
        >>> cfg = _parse_config_for_provider_export({"schema_version": 1})
        >>> cfg is not None and cfg.schema_version == 1
        True
    """
    try:
        return parse_workspace_config(config_doc)
    except (ValueError, TypeError):
        pass
    patched = copy.deepcopy(config_doc)
    patched.setdefault("schema_version", 1)
    gateway = patched.get("gateway")
    if not isinstance(gateway, dict):
        gateway = {}
        patched["gateway"] = gateway
    if not str(gateway.get("token", "")).strip():
        gateway["token"] = "export-placeholder-token"  # nosec B105 — parse stub for export-only docs
    try:
        return parse_workspace_config(patched)
    except (ValueError, TypeError):
        return None


def _export_slot_model_id(cfg: WorkspaceConfig, slot: ModelSlot) -> str | None:
    """Return a stripped model id for export pairing when the slot resolves.

    Args:
        cfg (WorkspaceConfig): Parsed workspace config.
        slot (ModelSlot): Target slot.

    Returns:
        str | None: Catalog model id, or ``None`` when the slot cannot be read.

    Examples:
        >>> doc = {
        ...     "schema_version": 1,
        ...     "gateway": {"token": "t"},
        ...     "providers": {"tier_default": {"triager": "minimax/M2"}},
        ... }
        >>> cfg = _parse_config_for_provider_export(doc)
        >>> cfg is not None and _export_slot_model_id(cfg, ModelSlot.triager) == "minimax/M2"
        True
    """
    try:
        model_id = resolve_model_slot(cfg, slot)
    except Exception:
        return None
    if not isinstance(model_id, str) or not model_id.strip():
        return None
    return model_id.strip()


def provider_bindings_from_config_doc(config_doc: dict[str, Any]) -> dict[str, str]:
    """Derive provider→credential-ref pairings from assigned model slots (D6).

    Walks every :class:`~sevn.config.model_resolution.ModelSlot`, maps each resolved
    model id to a provider name (D1), and collects ``providers.<name>.api_key`` refs.

    Args:
        config_doc (dict[str, Any]): Full ``sevn.json`` document.

    Returns:
        dict[str, str]: Provider name → ``${SECRET:…}`` ref or literal api_key value.

    Examples:
        >>> doc = {
        ...     "schema_version": 1,
        ...     "gateway": {"token": "t"},
        ...     "providers": {
        ...         "tier_default": {"triager": "minimax/M2"},
        ...         "minimax": {"api_key": "${SECRET:MM}"},
        ...     },
        ... }
        >>> provider_bindings_from_config_doc(doc)["minimax"]
        '${SECRET:MM}'
    """
    try:
        cfg = _parse_config_for_provider_export(config_doc)
    except (ValueError, TypeError):
        return {}
    if cfg is None:
        return {}
    bindings: dict[str, str] = {}
    for slot in ModelSlot:
        model_id = _export_slot_model_id(cfg, slot)
        if model_id is None:
            continue
        provider_name = resolve_provider_for_model_id(cfg, model_id)
        if provider_name in bindings:
            continue
        ref = provider_credential_ref(cfg, provider_name)
        if ref:
            bindings[provider_name] = ref
    return bindings


def bundle_seed_secrets(bundle: ExportBundle) -> dict[str, str]:
    """Merge plaintext secrets and provider binding aliases for ``onboard fast``.

    Provider binding lines (``providers.<name>.api_key``) are re-seeded into the
    encrypted store alongside the secrets block (D6).

    Args:
        bundle (ExportBundle): Parsed export bundle.

    Returns:
        dict[str, str]: Combined alias map for :func:`run_fast_onboard` seeding.

    Examples:
        >>> b = ExportBundle(
        ...     version=1,
        ...     bot_name="X",
        ...     config_doc={},
        ...     secrets={"SEVN_SECRET_MINIMAX": "sk-mm"},
        ...     provider_bindings={"minimax": "${SECRET:SEVN_SECRET_MINIMAX}"},
        ... )
        >>> bundle_seed_secrets(b)["providers.minimax.api_key"]
        '${SECRET:SEVN_SECRET_MINIMAX}'
    """
    merged = dict(bundle.secrets)
    for name, ref in sorted(bundle.provider_bindings.items()):
        merged[f"{_PROVIDER_BINDING_PREFIX}{name}{_PROVIDER_BINDING_SUFFIX}"] = ref
    return merged


def build_export_text(
    *,
    bot_name: str,
    config_doc: dict[str, Any],
    secrets: dict[str, str],
    generated_at: str | None = None,
    target_name: str | None = None,
    provider_bindings: dict[str, str] | None = None,
) -> str:
    """Render an export bundle to ``.env`` text.

    Args:
        bot_name (str): Bot display name (also embedded in ``config_doc``).
        config_doc (dict[str, Any]): Full ``sevn.json`` document.
        secrets (dict[str, str]): Logical alias to plaintext map.
        generated_at (str | None): Timestamp banner; defaults to current UTC.
        target_name (str | None): File name shown in the ``onboard fast`` hint.
        provider_bindings (dict[str, str] | None): Provider name → credential ref;
            derived from ``config_doc`` assigned slots when omitted (D6).

    Returns:
        str: ``.env`` file text terminated by a newline.

    Examples:
        >>> text = build_export_text(
        ...     bot_name="Sevn",
        ...     config_doc={"schema_version": 1, "gateway": {"port": 3001}},
        ...     secrets={"SEVN_SECRET_MINIMAX": "k"},
        ...     generated_at="2026-06-07T00:00:00Z",
        ... )
        >>> "config.gateway.port=3001" in text and "SEVN_SECRET_MINIMAX=k" in text
        True
    """
    stamp = generated_at or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    hint = target_name or "<this-file>"
    bindings = (
        provider_bindings
        if provider_bindings is not None
        else provider_bindings_from_config_doc(config_doc)
    )
    lines: list[str] = [
        f"# sevn workspace export — generated {stamp}",
        "# Recreate a bot from this file:",
        f"#   sevn onboard fast {hint}",
        "# WARNING: contains PLAINTEXT secrets — keep private (written with 0600 perms).",
        "# Edit SEVN_BOT_NAME or any value below, then run `sevn onboard fast`.",
        "",
        f"{_VERSION_KEY}={EXPORT_FORMAT_VERSION}",
        f"{_BOT_NAME_KEY}={_encode_env_value(bot_name)}",
        "",
    ]
    if secrets:
        lines.append("# --- secrets (logical alias = plaintext) ---")
        for alias in sorted(secrets):
            lines.append(f"{alias}={_encode_env_value(secrets[alias])}")
        lines.append("")
    if bindings:
        lines.append(_PROVIDERS_SECTION_HEADER)
        for name in sorted(bindings):
            ref = bindings[name]
            config_ref = f"{_PROVIDER_BINDING_PREFIX}{name}{_PROVIDER_BINDING_SUFFIX}"
            store_alias = _secret_alias_from_ref(ref)
            if store_alias:
                lines.append(f"# {name} → {config_ref} → {store_alias}")
            else:
                lines.append(f"# {name} → {config_ref}")
            lines.append(f"{config_ref}={_encode_env_value(ref)}")
        lines.append("")
    lines.append("# --- workspace config (flattened sevn.json) ---")
    flat = _flatten_config(config_doc)
    for flat_key in sorted(flat, key=_flat_sort_key):
        lines.append(f"{_CONFIG_PREFIX}{flat_key}={_encode_config_value(flat[flat_key])}")
    lines.append("")
    return "\n".join(lines)


def parse_export_text(text: str) -> ExportBundle:
    """Parse ``.env`` export text into an :class:`ExportBundle`.

    Args:
        text (str): File contents written by :func:`build_export_text`.

    Returns:
        ExportBundle: Parsed version, bot name, config doc, and secrets.

    Raises:
        ExportBundleError: On malformed lines, missing/invalid config, or version mismatch
            (exit code ``2``).

    Examples:
        >>> b = parse_export_text(
        ...     'SEVN_EXPORT_VERSION=1\\n'
        ...     'SEVN_BOT_NAME=Nova\\n'
        ...     'SEVN_SECRET_MINIMAX=k\\n'
        ...     'config.schema_version=1\\n'
        ...     'config.gateway.port=3001\\n'
        ... )
        >>> (b.bot_name, b.secrets["SEVN_SECRET_MINIMAX"], b.config_doc["gateway"]["port"])
        ('Nova', 'k', 3001)
    """
    version: int | None = None
    bot_name: str | None = None
    flat_config: dict[str, Any] = {}
    secrets: dict[str, str] = {}
    provider_bindings: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            msg = f"malformed export line (expected KEY=value): {raw_line!r}"
            raise ExportBundleError(msg, exit_code=2)
        key, _, value = line.partition("=")
        key = key.strip()
        if key == _VERSION_KEY:
            try:
                version = int(value.strip())
            except ValueError as exc:
                raise ExportBundleError(f"{_VERSION_KEY} must be an integer", exit_code=2) from exc
        elif key == _BOT_NAME_KEY:
            bot_name = _decode_env_value(value) or None
        elif key.startswith(_CONFIG_PREFIX):
            flat_config[key[len(_CONFIG_PREFIX) :]] = _decode_config_value(value)
        else:
            provider_name = _parse_provider_binding_key(key)
            decoded = _decode_env_value(value)
            if provider_name is not None:
                provider_bindings[provider_name] = decoded
            else:
                secrets[key] = decoded
    if version is not None and version != EXPORT_FORMAT_VERSION:
        raise ExportBundleError(
            f"unsupported export version {version} (expected {EXPORT_FORMAT_VERSION})",
            exit_code=2,
        )
    if not flat_config:
        raise ExportBundleError("export file has no config.* lines", exit_code=2)
    config_doc = _unflatten_config(flat_config)
    if bot_name is None:
        bot_name = resolve_agent_display_name(config_doc)
    return ExportBundle(
        version=version or EXPORT_FORMAT_VERSION,
        bot_name=bot_name,
        config_doc=config_doc,
        secrets=secrets,
        provider_bindings=provider_bindings,
    )


def resolve_export_workspace(
    workspace_root: Path,
) -> tuple[Path, WorkspaceConfig, Path, dict[str, Any]]:
    """Locate ``sevn.json`` and resolve the content root for ``workspace_root``.

    Accepts a path to ``sevn.json`` itself, the directory holding it, or an operator
    home whose ``workspace/sevn.json`` exists.

    Args:
        workspace_root (Path): Workspace path supplied on the command line.

    Returns:
        tuple[Path, WorkspaceConfig, Path, dict[str, Any]]: ``sevn.json`` path, parsed
        config, resolved content root, and the raw JSON document.

    Raises:
        ExportBundleError: When no ``sevn.json`` is found or it cannot be parsed (exit ``4``).

    Examples:
        >>> resolve_export_workspace.__name__
        'resolve_export_workspace'
    """
    p = workspace_root.expanduser()
    p = p.resolve() if p.exists() else p
    if p.is_file() and p.name == "sevn.json":
        sevn_json = p
    elif p.is_dir() and (p / "sevn.json").is_file():
        sevn_json = p / "sevn.json"
    elif p.is_dir() and (p / "workspace" / "sevn.json").is_file():
        sevn_json = p / "workspace" / "sevn.json"
    else:
        raise ExportBundleError(
            f"no sevn.json found at {workspace_root} "
            "(point to a workspace dir, its sevn.json, or an operator home)",
            exit_code=4,
        )
    try:
        raw = json.loads(sevn_json.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ExportBundleError(f"cannot read {sevn_json}: {exc}", exit_code=4) from exc
    if not isinstance(raw, dict):
        raise ExportBundleError(f"{sevn_json} must contain a JSON object", exit_code=4)
    try:
        cfg = parse_workspace_config(raw)
    except (ValueError, TypeError) as exc:
        raise ExportBundleError(f"invalid sevn.json: {exc}", exit_code=4) from exc
    layout = WorkspaceLayout.from_config(sevn_json, cfg)
    return sevn_json, cfg, layout.content_root, raw


def _normalize_config_for_export(raw: dict[str, Any]) -> dict[str, Any]:
    """Return a portable copy of ``raw`` with any absolute ``workspace_root`` reset to ``.``.

    Args:
        raw (dict[str, Any]): Source ``sevn.json`` document.

    Returns:
        dict[str, Any]: Deep copy safe to re-onboard into a fresh operator home.

    Examples:
        >>> _normalize_config_for_export({"workspace_root": "/abs"})["workspace_root"]
        '.'
        >>> _normalize_config_for_export({"workspace_root": "sub"})["workspace_root"]
        'sub'
    """
    doc = copy.deepcopy(raw)
    wr = doc.get("workspace_root")
    if isinstance(wr, str) and Path(wr).is_absolute():
        doc["workspace_root"] = "."
    return doc


async def _decrypt_store_secrets(
    content_root: Path,
    cfg: WorkspaceConfig,
    *,
    passphrase_prompt: Callable[[str], str] | None,
) -> dict[str, str]:
    """Resolve the unlock credential and decrypt the encrypted-file store.

    Args:
        content_root (Path): Resolved workspace content root.
        cfg (WorkspaceConfig): Parsed workspace config.
        passphrase_prompt (Callable[[str], str] | None): Interactive fallback that
            receives the unlock env-var name and returns the secret; ``None`` disables it.

    Returns:
        dict[str, str]: Logical alias to plaintext map (empty when the store is absent).

    Raises:
        ExportBundleError: When the unlock credential is unavailable (exit ``3``) or the
            store cannot be decrypted (exit ``3``).

    Examples:
        >>> _decrypt_store_secrets.__name__
        '_decrypt_store_secrets'
    """
    store_path = resolve_primary_encrypted_store_path(content_root, cfg.secrets_backend)
    if not await asyncio.to_thread(store_path.exists):
        return {}
    key_source = effective_encrypted_file_key_source(cfg.secrets_backend)
    var = unlock_env_var_for(key_source)
    unlock = os.environ.get(var, "").strip()
    if not unlock:
        from_keychain = await fetch_unlock_secret_from_keychain(key_source=key_source)
        unlock = (from_keychain or "").strip()
    if not unlock and passphrase_prompt is not None:
        unlock = (passphrase_prompt(var) or "").strip()
    if not unlock:
        raise ExportBundleError(
            f"encrypted store is locked: set {var} (or unlock the login Keychain) to export",
            exit_code=3,
        )
    os.environ[var] = unlock
    try:
        backend = encrypted_file_backend_for_workspace(content_root, cfg)
    except ValueError as exc:
        raise ExportBundleError(str(exc), exit_code=3) from exc
    try:
        return await backend.load_decrypted_map()
    except SecretsStoreCorruptError as exc:
        raise ExportBundleError(
            f"could not decrypt secrets store ({exc}); check {var}",
            exit_code=3,
        ) from exc


def _check_out_path(to_file: Path, *, force: bool) -> Path:
    """Resolve and guard the destination ``.env`` path (blocking helper).

    Args:
        to_file (Path): Requested destination path.
        force (bool): Allow overwrite of an existing file.

    Returns:
        Path: Expanded destination path.

    Raises:
        ExportBundleError: When the file exists and ``force`` is False (exit ``4``).

    Examples:
        >>> _check_out_path.__name__
        '_check_out_path'
    """
    out_path = to_file.expanduser()
    if out_path.exists() and not force:
        raise ExportBundleError(
            f"{out_path} already exists (pass --force to overwrite)",
            exit_code=4,
        )
    return out_path


def _write_bundle_file(out_path: Path, text: str) -> None:
    """Write ``text`` to ``out_path`` and tighten permissions (blocking helper).

    Args:
        out_path (Path): Destination path.
        text (str): Bundle contents.

    Examples:
        >>> _write_bundle_file.__name__
        '_write_bundle_file'
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")
    try:
        os.chmod(out_path, 0o600)
    except OSError:
        # Best-effort hardening; non-POSIX filesystems may reject chmod.
        if sys.platform != "win32":
            raise


async def run_export_secrets(
    *,
    workspace_root: Path,
    to_file: Path,
    force: bool = False,
    passphrase_prompt: Callable[[str], str] | None = None,
) -> ExportResult:
    """Decrypt a workspace store and write a portable ``.env`` bundle.

    Args:
        workspace_root (Path): Workspace dir, its ``sevn.json``, or an operator home.
        to_file (Path): Destination ``.env`` path (written with ``0600`` perms).
        force (bool): Overwrite ``to_file`` when it already exists.
        passphrase_prompt (Callable[[str], str] | None): Interactive unlock fallback.

    Returns:
        ExportResult: Written path, secret count, and bot name.

    Raises:
        ExportBundleError: On workspace resolution, unlock, decrypt, or write failures.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(run_export_secrets)
        True
    """
    out_path = await asyncio.to_thread(_check_out_path, to_file, force=force)
    _sevn_json, cfg, content_root, raw = await asyncio.to_thread(
        resolve_export_workspace, workspace_root
    )
    secrets = await _decrypt_store_secrets(content_root, cfg, passphrase_prompt=passphrase_prompt)
    config_doc = _normalize_config_for_export(raw)
    bot_name = resolve_agent_display_name(raw)
    text = build_export_text(
        bot_name=bot_name,
        config_doc=config_doc,
        secrets=secrets,
        target_name=out_path.name,
    )
    await asyncio.to_thread(_write_bundle_file, out_path, text)
    git_unignored_warning = False
    ignored = await asyncio.to_thread(_git_ignored, out_path)
    if ignored is False:
        git_unignored_warning = True
        logger.warning("workspace_export_unignored path={}", out_path)
    return ExportResult(
        path=out_path,
        secret_count=len(secrets),
        bot_name=bot_name,
        git_unignored_warning=git_unignored_warning,
    )


__all__ = [
    "EXPORT_FORMAT_VERSION",
    "ExportBundle",
    "ExportBundleError",
    "ExportResult",
    "build_export_text",
    "bundle_seed_secrets",
    "parse_export_text",
    "provider_bindings_from_config_doc",
    "resolve_export_workspace",
    "run_export_secrets",
]
