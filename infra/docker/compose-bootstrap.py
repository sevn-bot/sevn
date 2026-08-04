#!/usr/bin/env python3
"""First-boot workspace bootstrap for operator compose stacks (#177).

Materializes ``/operator/workspace/sevn.json`` from the mounted onboard JSON and
profile fragment without interactive onboarding or live validation probes.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

# Known weak defaults — bootstrap must refuse these when passed via compose env.
_GATEWAY_TOKEN_SENTINELS = frozenset(
    {
        "0000000000000000000000000000000000000000000000000000000000000000",
        "change-me",
    }
)


def _assert_gateway_token_not_sentinel() -> None:
    """Refuse compose boot when ``SEVN_GATEWAY_TOKEN`` is a shipped weak default."""
    token = os.environ.get("SEVN_GATEWAY_TOKEN", "").strip()
    if token and token in _GATEWAY_TOKEN_SENTINELS:
        msg = (
            "SEVN_GATEWAY_TOKEN is a known weak default — set a unique secret "
            "in .env (see .env.example) before starting the operator stack"
        )
        raise ValueError(msg)


def _dockerize_config_doc(config_doc: dict[str, Any]) -> None:
    """Adjust onboard JSON for container-first boot (env-backed token, optional Telegram)."""
    gateway = config_doc.setdefault("gateway", {})
    token_ref = str(gateway.get("token", "")).strip()
    if "${SECRET:keychain" in token_ref:
        gateway["token"] = "${ENV:SEVN_GATEWAY_TOKEN}"

    channels = config_doc.setdefault("channels", {})
    telegram = channels.get("telegram")
    if (
        isinstance(telegram, dict)
        and telegram.get("enabled")
        and not os.environ.get("SEVN_TELEGRAM_BOT_TOKEN", "").strip()
    ):
        telegram["enabled"] = False


def bootstrap_compose_workspace() -> Path:
    """Promote workspace config when ``sevn.json`` is absent under ``SEVN_HOME``."""
    _assert_gateway_token_not_sentinel()
    os.environ.setdefault("SEVN_HOME", "/operator")
    from sevn.cli.workspace import bound_sevn_json_path, bound_workspace_dir
    from sevn.config.provider_secrets import apply_provider_credential_bindings
    from sevn.onboarding.draft_store import write_draft
    from sevn.onboarding.fast_onboard import _apply_bot_name, merge_config_layers
    from sevn.onboarding.promote import promote_draft
    from sevn.onboarding.seed import seed_narrative_templates
    from sevn.onboarding.validate import validate_workspace_document
    from sevn.onboarding.web_app import (
        apply_model_slot_policy,
        normalize_secrets_backend_section,
    )

    sevn_path = bound_sevn_json_path()
    if sevn_path.is_file():
        return sevn_path

    config_path = Path(
        os.environ.get("SEVN_COMPOSE_BOOTSTRAP_CONFIG", "/bootstrap/onboard-compose.json"),
    )
    profile_id = os.environ.get("SEVN_COMPOSE_BOOTSTRAP_PROFILE", "good_value_docker")
    bot_name = os.environ.get("SEVN_BOOTSTRAP_BOT_NAME", "Sevn")

    config_doc = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(config_doc, dict):
        msg = f"bootstrap config must be a JSON object: {config_path}"
        raise ValueError(msg)

    _dockerize_config_doc(config_doc)
    bound_workspace_dir().mkdir(parents=True, exist_ok=True)

    merged = merge_config_layers(config_doc, profile_id=profile_id)
    _apply_bot_name(merged, bot_name=bot_name, prompt_for_bot_name=False)
    apply_model_slot_policy(merged)
    normalize_secrets_backend_section(merged)
    apply_provider_credential_bindings(merged)
    validate_workspace_document(merged)

    write_draft(sevn_path, merged)
    promote_draft(sevn_path, backup_previous=False, check_provider_credentials=False)
    seed_narrative_templates(sevn_path, merged)
    return sevn_path


def main() -> int:
    """CLI entrypoint for gateway container entrypoints."""
    try:
        sevn_path = bootstrap_compose_workspace()
    except Exception as exc:
        sys.stderr.write(f"compose bootstrap failed: {exc}\n")
        return 1
    sys.stdout.write(f"compose bootstrap: workspace ready at {sevn_path}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
