"""Auto-mint Telegram webhook secret on first setup (`specs/18-channel-telegram.md`).

Exports:
    ensure_webhook_secret_token — return existing or mint+persist secret.
"""

from __future__ import annotations

import json
import secrets
from pathlib import Path
from typing import Any

from sevn.config.workspace_config import WorkspaceConfig


def _telegram_channels_dict(doc: dict[str, Any]) -> dict[str, Any]:
    """Return the ``channels.telegram`` dict inside ``doc``, creating parents if needed.

    Args:
        doc (dict[str, Any]): Root ``sevn.json`` object (mutated in place).

    Returns:
        dict[str, Any]: Telegram channel subtree.

    Examples:
        >>> doc = {"channels": {}}
        >>> tg = _telegram_channels_dict(doc)
        >>> tg == {} and "telegram" in doc["channels"]
        True
    """
    channels = doc.setdefault("channels", {})
    if not isinstance(channels, dict):
        channels = {}
        doc["channels"] = channels
    tg = channels.setdefault("telegram", {})
    if not isinstance(tg, dict):
        tg = {}
        channels["telegram"] = tg
    return tg


def ensure_webhook_secret_token(
    workspace: WorkspaceConfig,
    sevn_json_path: Path,
) -> str:
    """Return configured webhook secret, minting and persisting when absent.

    Args:
        workspace (WorkspaceConfig): Parsed workspace config.
        sevn_json_path (Path): Path to ``sevn.json`` for atomic update.

    Returns:
        str: Non-empty secret token for ``setWebhook``.

    Examples:
        >>> ensure_webhook_secret_token.__name__
        'ensure_webhook_secret_token'
    """
    channels = workspace.channels
    tg = channels.telegram if channels is not None else None
    if tg is not None:
        for candidate in (tg.webhook_secret_token, tg.webhook_secret, tg.secret_token):
            if candidate and str(candidate).strip():
                return str(candidate).strip()

    token = secrets.token_urlsafe(32)
    raw = json.loads(sevn_json_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raw = {"schema_version": 1}
    tg_doc = _telegram_channels_dict(raw)
    tg_doc["webhook_secret_token"] = token
    tmp = sevn_json_path.with_suffix(".json.part")
    tmp.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
    tmp.replace(sevn_json_path)
    return token


__all__ = ["ensure_webhook_secret_token"]
