"""Local FastAPI onboarding wizard (`specs/22-onboarding.md` §2.1, §4.6, §8).
Module: sevn.onboarding.web_app
Depends: fastapi, pathlib, pydantic, time, typing, sevn.onboarding.*
**Routing:** ``sevn onboard --web`` starts this app on loopback; the gateway also
mounts it at ``/onboarding`` via ``sevn.gateway.onboarding.onboarding_mount`` (``specs/17-gateway.md``).
**Auth:** every request carries ``onboard_token`` via query string, ``X-Onboard-Token``
header, or the ``sevn_onboard_session`` cookie. On the first authenticated hit the cookie
is set automatically so that a plain browser refresh of ``/`` (where the query string is
gone after navigation) keeps working until the TTL elapses.
Exports:
    create_onboarding_app — FastAPI app factory with ``onboard_token`` gate.
    normalize_secrets_backend_section — persist ``encrypted_file.path`` + ``chain[]`` pairing.
    normalize_llm_main_model_layer — map TUI ``llm.main_model`` to triager on promote.
    apply_model_slot_policy — unified strip or per-slot fill-missing on promote.
Examples:
    >>> from sevn.onboarding.web_app import create_onboarding_app
    >>> app = create_onboarding_app("secret-token")
    >>> app.title.startswith("sevn")
    True
"""

from __future__ import annotations

import json
import os
import re
import signal
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any

from fastapi import (
    Cookie,
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
    StreamingResponse,
)
from loguru import logger
from pydantic import ValidationError

from sevn.agent.runtimes.pyodide_deno import reconcile_sandbox_mode_document
from sevn.config.defaults import (
    DEFAULT_ENCRYPTED_FILE_KEY_SOURCE,
    ONBOARDING_TOKEN_TTL_SECONDS,
    SUPPORTED_SCHEMA_VERSIONS,
)
from sevn.config.errors import UnsupportedSchemaVersionError
from sevn.onboarding.browser_automation import (
    BrowserSession,
    get_browser_session,
    register_shutdown_hooks,
    stop_browser_on_shutdown,
)
from sevn.onboarding.capabilities_manifest import (
    list_groups,
    load_manifest,
    merged_capability_defaults,
)
from sevn.onboarding.dashboard_url import apply_web_ui_url_for_dashboard
from sevn.onboarding.draft_store import read_draft, write_draft
from sevn.onboarding.github_oauth import (
    GITHUB_TOKEN_LOGICAL_KEY,
    build_authorize_url,
    callback_redirect_uri,
    exchange_code_for_token,
    fetch_github_user,
    mint_oauth_state,
    oauth_client_credentials,
    oauth_configured,
    set_wizard_oauth_credentials,
    validate_oauth_state,
)
from sevn.onboarding.live_validate import run_live_validation
from sevn.onboarding.merge import merge_layers
from sevn.onboarding.my_telegram_automation import (
    CONFIGURE_LATER_HINT,
    MyTelegramApiExtract,
    MyTelegramSkipError,
    run_fetch_my_telegram_api,
)
from sevn.onboarding.openai_oauth import poll_wizard_codex_oauth, start_wizard_codex_oauth
from sevn.onboarding.profiles import (
    load_profile_catalog_for_wizard,
    load_profile_fragment,
    profile_default_sandbox_mode,
)
from sevn.onboarding.promote import promote_draft
from sevn.onboarding.seed import (
    list_deployed_core_skill_ids,
    load_personality_presets,
    seed_narrative_templates,
    seed_personality_from_wizard,
    verify_core_skills_deployed,
)
from sevn.onboarding.telegram_automation import (
    TelegramBotExtract,
    normalize_bot_username,
    open_telegram_web,
    run_create_new_bot,
    run_lookup_existing_bot,
    wait_for_login,
)
from sevn.onboarding.validate import validate_workspace_document
from sevn.onboarding.wizard_credentials import (
    assigned_provider_names_from_doc,
    credentials_status,
    delete_wizard_credential,
    get_wizard_credential,
    probe_host_github_token,
    read_wizard_credential_values,
    resolve_wizard_secrets_section,
    secrets_section_from_sevn_json,
    store_wizard_credentials,
    unlock_wizard_keystore,
    verify_wizard_passphrase,
)
from sevn.onboarding.workspace_backup import (
    create_workspace_backup_repo,
    resolve_backup_default_name,
    sanitize_repo_name,
)
from sevn.security.secrets.errors import SecretsStoreCorruptError
from sevn.ui.shared import register_shared_ui_routes
from sevn.workspace.layout import WorkspaceLayout

ONBOARD_SESSION_COOKIE = "sevn_onboard_session"
WIZARD_STATIC_ROOT: Path = (Path(__file__).resolve().parent / "web_wizard").resolve()
_WIZARD_MIME: dict[str, str] = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
}
_DEFAULT_BASE: dict[str, Any] = {
    "schema_version": 1,
    "workspace_root": ".",
    "gateway": {
        "host": "127.0.0.1",
        "port": 3001,
        "queue_mode": "cancel",
        "token": "${SECRET:keychain:sevn.gateway.token}",  # nosec B105
    },
    "channels": {
        "telegram": {
            "enabled": True,
            "dm_policy": "pairing",
            "bot_token_ref": "${ENV:SEVN_TELEGRAM_BOT_TOKEN}",  # nosec B105 — env ref placeholder
            "api_id_ref": "${ENV:SEVN_TELEGRAM_API_ID}",
            "api_hash_ref": "${ENV:SEVN_TELEGRAM_API_HASH}",
            "phone_ref": "${ENV:SEVN_TELEGRAM_PHONE}",
        },
        "webchat": {"enabled": True},
    },
    "telemetry": {"enabled": False},
    "agent": {
        "codemode": {
            "max_retries": 3,
        },
    },
    "my_sevn": {
        "repo_url": "https://github.com/sevn-bot/sevn",
        "sync": {"enabled": True, "cron": "0 4 * * *"},
    },
    "self_improve": {
        "enabled": True,
        "hub": {"use_github": True, "provider": "github", "repo": "sevn-bot/sevn"},
    },
}
_SECRET_PATTERN = re.compile(
    r"(token|secret|password|api[_-]?key|credential|bearer)\s*[:=]\s*\S+",
    re.IGNORECASE,
)
DEFAULT_ENCRYPTED_FILE_REL_PATH = ".sevn/secrets/store.enc"


@lru_cache(maxsize=1)
def _load_field_help_paths() -> dict[str, dict[str, str]]:
    """Load wizard field long descriptions from packaged or infra JSON.
    Returns:
        dict[str, dict[str, str]]: ``field_id`` → ``long_description`` / ``how_to_collect``.
    Examples:
        >>> isinstance(_load_field_help_paths(), dict)
        True
    """
    from sevn.config.field_help import load_config_field_help

    out = dict(load_config_field_help())
    out.setdefault(
        "channels.telegram.bot_token_ref",
        {
            "long_description": (
                "Indirect reference to your Telegram bot token — never paste the raw secret "
                "into sevn.json."
            ),
            "how_to_collect": (
                "Create a bot via @BotFather, export SEVN_TELEGRAM_BOT_TOKEN in your "
                "environment, then set ${ENV:SEVN_TELEGRAM_BOT_TOKEN} here."
            ),
        },
    )
    out.setdefault(
        "my_sevn.repo_url",
        {
            "long_description": (
                "Upstream sevn.bot repository used for core checkout sync and evolution "
                "issue filing."
            ),
            "how_to_collect": (
                "Keeping https://github.com/sevn-bot/sevn means core checkout updates "
                "can overwrite local core changes. Evolution and self-improve are limited to "
                "non-core tools and skills. The upside is automatic bug and feature issue "
                "filing against upstream."
            ),
        },
    )
    return out


def _redact_detail(message: str) -> str:
    """Strip obvious secret material from operator-facing error strings.
    Args:
        message (str): Raw error text.
    Returns:
        str: Redacted copy safe for JSON responses.
    Examples:
        >>> _redact_detail("token: abc123secret")
        'token=[redacted]'
    """
    return _SECRET_PATTERN.sub(r"\1=[redacted]", message)


def _serve_wizard_asset(asset_path: str) -> Response:
    """Serve a file from ``web_wizard`` with path traversal protection.
    Args:
        asset_path (str): Relative path under the wizard root.
    Returns:
        Response: ``FileResponse`` or 404 JSON.
    Examples:
        >>> isinstance(_serve_wizard_asset("index.html"), Response)
        True
    """
    rel = asset_path.lstrip("/")
    if not rel:
        rel = "index.html"
    candidate = (WIZARD_STATIC_ROOT / rel).resolve()
    try:
        candidate.relative_to(WIZARD_STATIC_ROOT)
    except ValueError:
        return JSONResponse(status_code=404, content={"error": "not_found"})
    if not candidate.is_file():
        return JSONResponse(status_code=404, content={"error": "not_found"})
    media = _WIZARD_MIME.get(candidate.suffix.lower(), "application/octet-stream")
    return FileResponse(candidate, media_type=media)


def _expand_and_test_file(path_str: str) -> tuple[bool, str]:
    """Expand ``~`` then test if the path is an existing file.
    Args:
        path_str (str): Operator-supplied path that may include ``~``.
    Returns:
        tuple[bool, str]: ``(exists, expanded_path_string)``.
    Examples:
        >>> _expand_and_test_file("/no/such/file")
        (False, '/no/such/file')
    """
    expanded = Path(path_str).expanduser()
    return expanded.is_file(), str(expanded)


def _set_nested(doc: dict[str, Any], dotted: str, value: Any) -> None:
    """Assign ``value`` at a dot-separated path, creating intermediate dicts.

    Thin wrapper over :func:`sevn.gateway.config_io.workspace_config_io.set_nested` (shared util).

    Args:
        doc (dict[str, Any]): Target document (mutated in place).
        dotted (str): Field id such as ``gateway.port``.
        value (Any): Leaf value to store.
    Examples:
        >>> d: dict[str, Any] = {}
        >>> _set_nested(d, "gateway.port", 3001)
        >>> d["gateway"]["port"]
        3001
    """
    from sevn.gateway.config_io.workspace_config_io import set_nested

    set_nested(doc, dotted, value)


def _get_nested(doc: dict[str, Any], dotted: str) -> Any:
    """Read a dot-separated path from ``doc``.
    Args:
        doc (dict[str, Any]): Source document.
        dotted (str): Field id.
    Returns:
        Any: Value at path, or ``None`` when any segment is missing.
    Examples:
        >>> _get_nested({"gateway": {"port": 1}}, "gateway.port")
        1
    """
    cur: Any = doc
    for key in dotted.split("."):
        if not key or not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def normalize_secrets_backend_section(doc: dict[str, Any]) -> None:
    """Ensure ``encrypted_file.path`` matches the ``chain[]`` entry when selected.
    When ``secrets_backend.chain`` includes ``encrypted_file``, promoted config
    must record the same relative path on ``secrets_backend.encrypted_file.path``
    and the matching chain row, and an explicit ``key_source`` (default ``passphrase``) so the
    onboarded config is self-documenting and immune to default changes (``specs/06-secrets.md``
    §5.2).
    Args:
        doc (dict[str, Any]): Workspace document mutated in place.
    Returns:
        None: ``doc["secrets_backend"]`` is updated when applicable.
    Examples:
        >>> payload = {"secrets_backend": {"chain": [{"type": "encrypted_file"}]}}
        >>> normalize_secrets_backend_section(payload)
        >>> payload["secrets_backend"]["encrypted_file"]["path"]
        '.sevn/secrets/store.enc'
        >>> payload["secrets_backend"]["encrypted_file"]["key_source"]
        'passphrase'
    """
    sb = doc.get("secrets_backend")
    if not isinstance(sb, dict):
        return
    chain = sb.get("chain")
    if not isinstance(chain, list):
        return
    has_encrypted = any(
        isinstance(entry, dict) and entry.get("type") == "encrypted_file" for entry in chain
    )
    if not has_encrypted:
        return
    enc_raw = sb.get("encrypted_file")
    enc: dict[str, Any] = enc_raw if isinstance(enc_raw, dict) else {}
    sb["encrypted_file"] = enc
    path: str | None = None
    enc_path = enc.get("path")
    if isinstance(enc_path, str) and enc_path.strip():
        path = enc_path.strip()
    if path is None:
        for entry in chain:
            if not isinstance(entry, dict) or entry.get("type") != "encrypted_file":
                continue
            chain_path = entry.get("path")
            if isinstance(chain_path, str) and chain_path.strip():
                path = chain_path.strip()
                break
    if path is None:
        path = DEFAULT_ENCRYPTED_FILE_REL_PATH
    enc["path"] = path
    # Resolve the unlock mechanism the same way (entry > defaults block > passphrase) and stamp
    # it explicitly so the promoted config never relies on the implicit default.
    key_source: str | None = None
    enc_ks = enc.get("key_source")
    if isinstance(enc_ks, str) and enc_ks.strip():
        key_source = enc_ks.strip()
    if key_source is None:
        for entry in chain:
            if isinstance(entry, dict) and entry.get("type") == "encrypted_file":
                chain_ks = entry.get("key_source")
                if isinstance(chain_ks, str) and chain_ks.strip():
                    key_source = chain_ks.strip()
                    break
    if key_source is None:
        key_source = DEFAULT_ENCRYPTED_FILE_KEY_SOURCE
    enc["key_source"] = key_source
    for entry in chain:
        if isinstance(entry, dict) and entry.get("type") == "encrypted_file":
            entry["path"] = path
            entry["key_source"] = key_source


def _config_from_fields(fields: dict[str, Any]) -> dict[str, Any]:
    """Build a nested workspace document from flat wizard field ids.
    Args:
        fields (dict[str, Any]): ``field_id`` → value map from the browser.
    Returns:
        dict[str, Any]: Partial ``sevn.json`` tree.
    Examples:
        >>> _config_from_fields({"gateway.port": 3001})["gateway"]["port"]
        3001
    """
    doc: dict[str, Any] = {}
    for field_id, value in fields.items():
        if field_id.startswith("wizard."):
            continue
        if value is None or value == "":
            continue
        if field_id == "schema_version":
            doc["schema_version"] = int(value) if not isinstance(value, int) else value
            continue
        if field_id == "telemetry.enabled":
            doc.setdefault("telemetry", {})["enabled"] = bool(value)
            continue
        if field_id == "onboarding.applied_profile":
            pid = str(value).strip()
            if pid and pid != "skip":
                doc.setdefault("onboarding", {})["applied_profile"] = pid
            continue
        if field_id.startswith("onboarding.capability_selections."):
            # Flat keys (``extra.web_fetch``) — not nested under ``extra.*`` subtrees.
            cap_key = field_id.removeprefix("onboarding.capability_selections.")
            if not cap_key:
                continue
            selections = doc.setdefault("onboarding", {}).setdefault("capability_selections", {})
            if isinstance(value, bool):
                selections[cap_key] = value
            elif isinstance(value, str):
                text = value.strip()
                if text:
                    selections[cap_key] = text
            elif value is not None:
                selections[cap_key] = bool(value)
            continue
        if field_id.startswith("channels."):
            _, channel, *rest = field_id.split(".")
            if not rest:
                continue
            leaf = rest[-1]
            ch = doc.setdefault("channels", {}).setdefault(channel, {})
            if leaf == "enabled":
                ch["enabled"] = bool(value) if not isinstance(value, bool) else value
            else:
                ch[leaf] = value
            continue
        if field_id == "secrets_backend.type":
            # The wizard exposes a single dropdown that picks the *first* chain entry.
            # `SecretsBackendSectionConfig` rejects a bare `type` key (extra_forbidden)
            # — translate to the structured `chain: [{"type": ...}]` form so pydantic
            # validation passes. Operator can layer cache_ttl / write_targets later
            # by hand-editing sevn.json.
            tag = str(value).strip()
            if not tag:
                continue
            sb = doc.setdefault("secrets_backend", {})
            existing_chain = sb.get("chain")
            if isinstance(existing_chain, list) and existing_chain:
                existing_chain[0]["type"] = tag
            else:
                sb["chain"] = [{"type": tag}]
            continue
        if field_id == "secrets_backend.encrypted_file.path":
            text = str(value).strip()
            if not text:
                continue
            sb = doc.setdefault("secrets_backend", {})
            sb.setdefault("encrypted_file", {})["path"] = text
            # Also propagate to the chain entry so the operator's choice is
            # used when the chain has multiple encrypted_file entries.
            chain = sb.get("chain")
            if isinstance(chain, list):
                for entry in chain:
                    if isinstance(entry, dict) and entry.get("type") == "encrypted_file":
                        entry["path"] = text
                        break
            continue
        if field_id.startswith("secrets_backend."):
            doc.setdefault("secrets_backend", {})[field_id.split(".", 1)[1]] = value
            continue
        if field_id.startswith("sandbox."):
            doc.setdefault("sandbox", {})[field_id.split(".", 1)[1]] = value
            continue
        if field_id.startswith("infrastructure."):
            _set_nested(doc, field_id, value)
            continue
        if field_id.startswith("skills."):
            _set_nested(doc, field_id, value)
            continue
        if field_id == "providers.use_main_model_for_all":
            doc.setdefault("providers", {})["use_main_model_for_all"] = (
                bool(value)
                if not isinstance(value, str)
                else value.strip().lower() in ("1", "true", "yes", "on")
            )
            continue
        if field_id.startswith("memory."):
            _set_nested(doc, field_id, value)
            continue
        if "." in field_id:
            _set_nested(doc, field_id, value)
        else:
            doc[field_id] = value
    return doc


def normalize_llm_main_model_layer(doc: dict[str, Any]) -> None:
    """Map legacy TUI ``llm.main_*`` into ``providers`` for promote/merge.

    Args:
        doc (dict[str, Any]): Draft or merged document (mutated in place).

    Examples:
        >>> d: dict[str, Any] = {"llm": {"main_model": "minimax/M2"}}
        >>> normalize_llm_main_model_layer(d)
        >>> d["providers"]["tier_default"]["triager"]
        'minimax/M2'
    """
    llm = doc.get("llm")
    if not isinstance(llm, dict):
        return
    main_model = llm.get("main_model")
    if isinstance(main_model, str) and main_model.strip():
        providers = doc.setdefault("providers", {})
        tier = providers.setdefault("tier_default", {})
        if not isinstance(tier, dict):
            tier = {}
            providers["tier_default"] = tier
        if not tier.get("triager"):
            tier["triager"] = main_model.strip()
    providers = doc.setdefault("providers", {})
    if providers.get("use_main_model_for_all") is not False:
        providers["use_main_model_for_all"] = True
    doc.pop("llm", None)


def apply_model_slot_policy(doc: dict[str, Any]) -> None:
    """Normalize model flags and per-slot keys after merge, promote, or dashboard write.

    When ``use_main_model_for_all`` is true, strip per-slot overrides. When false,
    fill only **missing** slots from triager (never overwrite saved values).

    Args:
        doc (dict[str, Any]): Workspace document (mutated in place).

    Examples:
        >>> from sevn.config.model_resolution import fill_missing_model_slots_from_triager
        >>> d: dict[str, Any] = {
        ...     "providers": {
        ...         "use_main_model_for_all": False,
        ...         "tier_default": {"triager": "m", "B": "x"},
        ...     },
        ... }
        >>> apply_model_slot_policy(d)
        >>> d["providers"]["tier_default"]["C"]
        'm'
    """
    from sevn.config.model_resolution import fill_missing_model_slots_from_triager

    normalize_llm_main_model_layer(doc)
    providers = doc.get("providers")
    if isinstance(providers, dict) and providers.get("use_main_model_for_all") is False:
        fill_missing_model_slots_from_triager(doc)
        return
    _apply_unified_model_cleanup(doc)


def _apply_unified_model_cleanup(doc: dict[str, Any]) -> None:
    """Drop per-slot model overrides when ``use_main_model_for_all`` is true.

    Args:
        doc (dict[str, Any]): Merged workspace document (mutated in place).

    Examples:
        >>> d: dict[str, Any] = {
        ...     "providers": {
        ...         "use_main_model_for_all": True,
        ...         "tier_default": {"triager": "m", "B": "x"},
        ...     },
        ...     "lcm": {"summary_model": "y"},
        ... }
        >>> _apply_unified_model_cleanup(d)
        >>> d["providers"]["tier_default"]
        {'triager': 'm'}
    """
    normalize_llm_main_model_layer(doc)
    providers = doc.get("providers")
    if not isinstance(providers, dict) or providers.get("use_main_model_for_all") is False:
        return
    providers["use_main_model_for_all"] = True
    tier = providers.get("tier_default")
    if isinstance(tier, dict):
        triager = tier.get("triager")
        providers["tier_default"] = {"triager": triager} if triager else {}
    lcm = doc.get("lcm")
    if isinstance(lcm, dict):
        lcm.pop("summary_model", None)
    memory = doc.get("memory")
    if isinstance(memory, dict):
        flush = memory.get("pre_compaction_flush")
        if isinstance(flush, dict):
            flush.pop("model", None)
        dreaming = memory.get("dreaming")
        if isinstance(dreaming, dict):
            scoring = dreaming.get("scoring")
            if isinstance(scoring, dict):
                ranker = scoring.get("llm_ranker")
                if isinstance(ranker, dict):
                    ranker.pop("model", None)
        user_model = memory.get("user_model")
        if isinstance(user_model, dict):
            user_model.pop("extractor_model", None)
    security = doc.get("security")
    if isinstance(security, dict):
        scanner = security.get("scanner")
        if isinstance(scanner, dict):
            scanner.pop("model", None)


def _apply_profile_sandbox_default(doc: dict[str, Any], profile_id: str) -> None:
    """Back-fill ``sandbox.mode`` from the preset host tag when the wizard left it empty.

    Args:
        doc (dict[str, Any]): Merged workspace document (mutated in place).
        profile_id (str): Catalog preset id (not ``skip``).

    Examples:
        >>> from sevn.onboarding.web_app import _apply_profile_sandbox_default
        >>> d: dict[str, object] = {"schema_version": 1}
        >>> _apply_profile_sandbox_default(d, "good_value_osx")
        >>> d.get("sandbox", {}).get("mode") in (None, "pyodide_deno", "docker")
        True
    """
    default_mode = profile_default_sandbox_mode(profile_id)
    if not default_mode:
        return
    sandbox = doc.setdefault("sandbox", {})
    if not isinstance(sandbox, dict):
        return
    explicit = sandbox.get("mode") or sandbox.get("driver") or sandbox.get("runtime")
    if isinstance(explicit, str) and explicit.strip():
        return
    sandbox["mode"] = default_mode


def _apply_profile_triager_override(doc: dict[str, Any], profile_id: str) -> None:
    """Force profile ``tier_default.triager`` after field merge (OE Wave 1).

    Args:
        doc (dict[str, Any]): Merged workspace document (mutated in place).
        profile_id (str): Catalog preset id (not ``skip``).

    Examples:
        >>> from sevn.onboarding.web_app import _apply_profile_triager_override
        >>> d: dict[str, Any] = {
        ...     "schema_version": 1,
        ...     "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        ...     "providers": {
        ...         "tier_default": {"triager": "openai/gpt-4o"},
        ...     },
        ... }
        >>> _apply_profile_triager_override(d, "good_value_osx")
        >>> d["providers"]["tier_default"]["triager"]
        'minimax/MiniMax-M2.7'
    """
    frag = load_profile_fragment(profile_id)
    providers = frag.get("providers")
    if not isinstance(providers, dict):
        return
    doc_providers = doc.setdefault("providers", {})
    if not isinstance(doc_providers, dict):
        return
    if providers.get("use_main_model_for_all") is True:
        doc_providers["use_main_model_for_all"] = True
    tier = providers.get("tier_default")
    if isinstance(tier, dict):
        triager = tier.get("triager")
        if isinstance(triager, str) and triager.strip():
            doc_tier = doc_providers.setdefault("tier_default", {})
            if isinstance(doc_tier, dict):
                doc_tier["triager"] = triager.strip()


def _apply_telegram_owner_from_fields(
    tg: dict[str, Any],
    fields: Any,
) -> None:
    """Write ``allowed_users`` from the wizard owner id field.

    Args:
        tg (dict[str, Any]): ``channels.telegram`` subtree (mutated in place).
        fields (Any): Flat wizard ``fields`` map from the browser payload.

    Examples:
        >>> tg: dict[str, Any] = {}
        >>> _apply_telegram_owner_from_fields(
        ...     tg,
        ...     {"wizard.telegram_owner_user_id": "123456789"},
        ... )
        >>> tg["allowed_users"]
        [123456789]
    """
    if not isinstance(fields, dict):
        return
    raw = fields.get("wizard.telegram_owner_user_id")
    if raw is None:
        return
    text = str(raw).strip()
    if not text:
        return
    tg["allowed_users"] = [int(text)]


def _wizard_payload_sets_triager(payload: dict[str, Any]) -> bool:
    """True when the browser payload carries an explicit ``tier_default.triager`` value.

    The wizard's triager field is ``required`` and always submitted, so an operator
    who edits the model away from a preset default must win over the preset. Used to
    gate :func:`_apply_profile_triager_override` so it only back-fills the preset
    model when the operator left the field untouched/blank.

    Args:
        payload (dict[str, Any]): Request body with optional ``fields`` / ``config``.

    Returns:
        bool: True when a non-empty triager id is present in ``fields`` or ``config``.

    Examples:
        >>> _wizard_payload_sets_triager(
        ...     {"fields": {"providers.tier_default.triager": "minimax/MiniMax-M3"}}
        ... )
        True
        >>> _wizard_payload_sets_triager({"fields": {"providers.tier_default.triager": ""}})
        False
        >>> _wizard_payload_sets_triager({})
        False
    """
    fields = payload.get("fields")
    if isinstance(fields, dict):
        value = fields.get("providers.tier_default.triager")
        if isinstance(value, str) and value.strip():
            return True
    raw_config = payload.get("config")
    if isinstance(raw_config, dict):
        value = _get_nested(raw_config, "providers.tier_default.triager")
        if isinstance(value, str) and value.strip():
            return True
    return False


def _wizard_gateway_token_plaintext(fields: dict[str, Any]) -> str:
    """Return wizard gateway token plaintext, auto-generating when the client omitted it.

    Args:
        fields (dict[str, Any]): Wizard ``fields`` map from the request body.

    Returns:
        str: Validated gateway bearer token (min 32 chars).

    Examples:
        >>> from sevn.gateway.runtime.gateway_token import GATEWAY_TOKEN_MIN_CHARS
        >>> len(_wizard_gateway_token_plaintext({})) >= GATEWAY_TOKEN_MIN_CHARS
        True
    """
    from sevn.gateway.runtime.gateway_token import (
        generate_gateway_token,
        validate_gateway_token_plaintext,
    )

    raw = fields.get("wizard.gateway_token")
    if isinstance(raw, str) and raw.strip():
        return validate_gateway_token_plaintext(raw)
    return generate_gateway_token()


def _provider_api_keys_from_fields(fields: dict[str, Any]) -> dict[str, str] | None:
    """Collect per-provider API keys from wizard ``fields`` (``wizard.provider_api_key.<name>``).

    Args:
        fields (dict[str, Any]): Wizard ``fields`` map from the request body.

    Returns:
        dict[str, str] | None: Provider name → plaintext key, or ``None`` when absent.

    Examples:
        >>> _provider_api_keys_from_fields(
        ...     {"wizard.provider_api_key.minimax": "sk-mm", "wizard.provider_api_key.openai": "sk-o"}
        ... ) == {"minimax": "sk-mm", "openai": "sk-o"}
        True
    """
    prefix = "wizard.provider_api_key."
    out: dict[str, str] = {}
    for key, val in fields.items():
        if not isinstance(key, str) or not key.startswith(prefix):
            continue
        if not isinstance(val, str) or not val.strip():
            continue
        name = key[len(prefix) :].strip()
        if name:
            out[name] = val.strip()
    return out or None


def _provider_api_keys_from_data(data: dict[str, Any]) -> dict[str, str] | None:
    """Parse ``provider_api_keys`` from a credentials API request body.

    Args:
        data (dict[str, Any]): JSON body from ``POST /api/credentials``.

    Returns:
        dict[str, str] | None: Provider name → plaintext key, or ``None`` when absent.

    Examples:
        >>> _provider_api_keys_from_data({"provider_api_keys": {"minimax": "sk-mm"}})
        {'minimax': 'sk-mm'}
    """
    raw = data.get("provider_api_keys")
    if not isinstance(raw, dict):
        return None
    out: dict[str, str] = {}
    for key, val in raw.items():
        if isinstance(key, str) and key.strip() and isinstance(val, str) and val.strip():
            out[key.strip()] = val.strip()
    return out or None


def _merge_wizard_payload(
    payload: dict[str, Any],
    *,
    profile_id: str | None,
) -> dict[str, Any]:
    """Apply profile fragment and wizard fields onto shipped defaults.
    Args:
        payload (dict[str, Any]): Request body with optional ``config`` or ``fields``.
        profile_id (str | None): Preset id from body or ``onboarding.applied_profile``.
    Returns:
        dict[str, Any]: Merged preview document.
    Examples:
        >>> doc = _merge_wizard_payload({"fields": {"gateway.port": 3002}}, profile_id=None)
        >>> doc["gateway"]["port"]
        3002
    """
    layers: list[dict[str, Any]] = [dict(_DEFAULT_BASE)]
    pid = profile_id or payload.get("profile_id")
    if isinstance(pid, str) and pid.strip() and pid.strip() != "skip":
        layers.append(load_profile_fragment(pid.strip()))
    raw_config = payload.get("config")
    if isinstance(raw_config, dict):
        layers.append(raw_config)
    fields = payload.get("fields")
    if isinstance(fields, dict):
        layers.append(_config_from_fields(fields))
    merged = merge_layers(*layers)
    # Back-fill the preset's triager only when the operator did NOT type their own
    # model. The field is ``required`` so it is always submitted; forcing the preset
    # value unconditionally clobbered an edited model (e.g. operator picks a preset,
    # changes triager to ``minimax/MiniMax-M3``, but it saved as the preset default).
    if (
        isinstance(pid, str)
        and pid.strip()
        and pid.strip() != "skip"
        and not _wizard_payload_sets_triager(payload)
    ):
        _apply_profile_triager_override(merged, pid.strip())
    if isinstance(pid, str) and pid.strip() and pid.strip() != "skip":
        _apply_profile_sandbox_default(merged, pid.strip())
    reconcile_sandbox_mode_document(merged)
    apply_model_slot_policy(merged)
    from sevn.config.provider_secrets import apply_provider_credential_bindings

    apply_provider_credential_bindings(merged)
    ch = merged.setdefault("channels", {})
    tg = ch.setdefault("telegram", {})
    tg["enabled"] = True
    tg.setdefault("dm_policy", "pairing")
    _apply_telegram_owner_from_fields(tg, payload.get("fields"))
    tg.setdefault("bot_token_ref", "${ENV:SEVN_TELEGRAM_BOT_TOKEN}")
    tg.setdefault("api_id_ref", "${ENV:SEVN_TELEGRAM_API_ID}")
    tg.setdefault("api_hash_ref", "${ENV:SEVN_TELEGRAM_API_HASH}")
    tg.setdefault("phone_ref", "${ENV:SEVN_TELEGRAM_PHONE}")
    wc = ch.setdefault("webchat", {})
    wc["enabled"] = True
    gw = merged.setdefault("gateway", {})
    if isinstance(gw, dict):
        from sevn.gateway.runtime.gateway_token import GATEWAY_TOKEN_CONFIG_REF

        gw.setdefault("token", GATEWAY_TOKEN_CONFIG_REF)
    return merged


def _validation_error_response(exc: Exception) -> JSONResponse:
    """Map validation failures to a 422 JSON envelope with redacted detail.
    Args:
        exc (Exception): ``ValidationError`` or ``UnsupportedSchemaVersionError``.
    Returns:
        JSONResponse: 422 body with ``ok: false`` and ``detail``.
    Examples:
        >>> resp = _validation_error_response(ValueError("bad"))
        >>> resp.status_code
        422
    """
    errors: list[dict[str, str]] = []
    if isinstance(exc, ValidationError):
        for err in exc.errors():
            loc_parts = [str(p) for p in err.get("loc", ()) if p != "__root__"]
            errors.append(
                {
                    "loc": ".".join(loc_parts) or "(root)",
                    "type": str(err.get("type", "")),
                    "msg": _redact_detail(str(err.get("msg", ""))),
                }
            )
        detail = "; ".join(f"{e['loc']}: {e['msg']}" for e in errors[:8]) or "validation failed"
        logger.warning(
            "validate-all rejected payload: {} error(s)\n{}",
            len(errors),
            "\n".join(f"  - {e['loc']}: {e['msg']} (type={e['type']})" for e in errors),
        )
    else:
        detail = _redact_detail(str(exc))
        errors.append({"loc": "(root)", "type": exc.__class__.__name__, "msg": detail})
        logger.warning("validate-all rejected payload: {}: {}", exc.__class__.__name__, detail)
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={"ok": False, "detail": detail, "errors": errors},
    )


async def _validate_field(
    field_id: str, value: Any, *, context: dict[str, Any]
) -> tuple[bool, str]:
    """Validate a single wizard field against schema-oriented rules.
    Args:
        field_id (str): Dot-path id aligned with ``infra/sevn.schema.json``.
        value (Any): Submitted value.
        context (dict[str, Any]): Optional sibling fields from the client.
    Returns:
        tuple[bool, str]: ``(ok, message)`` for the UI.
    Examples:
        >>> import asyncio
        >>> asyncio.run(_validate_field("gateway.port", 3001, context={}))[0]
        True
    """
    if field_id == "schema_version":
        try:
            ver = int(value)
        except (TypeError, ValueError):
            return False, "schema_version must be an integer"
        if ver not in SUPPORTED_SCHEMA_VERSIONS:
            return False, f"unsupported schema_version {ver}"
        return True, "ok"
    if field_id == "workspace_root":
        if not str(value).strip():
            return False, "workspace_root is required"
        return True, "ok"
    if field_id == "gateway.port":
        try:
            port = int(value)
        except (TypeError, ValueError):
            return False, "gateway.port must be an integer"
        if not 1 <= port <= 65535:
            return False, "gateway.port must be between 1 and 65535"
        return True, "ok"
    if field_id == "gateway.host":
        if not str(value).strip():
            return False, "gateway.host is required"
        return True, "ok"
    if field_id == "gateway.queue_mode":
        if str(value) not in ("cancel", "steer", "multi"):
            return False, "gateway.queue_mode must be cancel, steer, or multi"
        return True, "ok"
    if field_id == "onboarding.applied_profile":
        pid = str(value).strip()
        if not pid or pid == "skip":
            return True, "ok"
        try:
            load_profile_fragment(pid)
        except (FileNotFoundError, ValueError, OSError) as exc:
            return False, _redact_detail(str(exc))
        return True, "ok"
    if field_id == "wizard.gateway_token":
        from sevn.gateway.runtime.gateway_token import validate_gateway_token_plaintext

        try:
            validate_gateway_token_plaintext(str(value))
        except ValueError as exc:
            return False, str(exc)
        return True, "ok"
    if field_id == "wizard.telegram_create_new_bot":
        return True, "ok"
    if field_id == "wizard.telegram_bot_name":
        create_new = (
            context.get("wizard.telegram_create_new_bot") if isinstance(context, dict) else None
        )
        if create_new is False or str(create_new).lower() == "false":
            return True, "ok"
        text = str(value).strip()
        if not text:
            return False, "bot name is required when creating a new bot via BotFather"
        if len(text) > 64:
            return False, "bot name must be 64 characters or fewer"
        return True, "ok"
    if field_id == "wizard.telegram_bot_username":
        create_new = context.get("wizard.telegram_create_new_bot")
        if create_new is True or str(create_new).lower() == "true":
            return True, "ok"
        text = str(value).strip().lstrip("@")
        if not text:
            return False, "bot username is required when not creating a new bot via BotFather"
        try:
            normalize_bot_username(text)
        except ValueError as exc:
            return False, str(exc)
        return True, "ok"
    if field_id == "wizard.telegram_bot_token":
        text = str(value).strip()
        if not text:
            return False, "Telegram bot token is required"
        if ":" not in text and len(text) < 20:
            return False, "token looks too short — paste the full token from @BotFather"
        return True, "ok"
    if field_id == "wizard.telegram_owner_user_id":
        text = str(value).strip()
        if not text:
            return False, "Your Telegram user id is required so the bot only responds to you"
        try:
            uid = int(text)
        except ValueError:
            return False, "user id must be numeric digits only"
        if uid <= 0:
            return False, "user id must be a positive integer"
        return True, "ok"
    if field_id.startswith("wizard.provider_api_key."):
        provider = field_id.removeprefix("wizard.provider_api_key.").strip()
        if not provider:
            return False, "Provider name is required"
        if provider == "openai" and not str(value).strip():
            if context.get("wizard.openai_oauth_connected") is True:
                return True, "ok"
            return False, "OpenAI API key or Sign in with ChatGPT (Codex OAuth) is required"
        if not str(value).strip():
            return False, f"API key is required for provider {provider!r}"
        return True, "ok"
    if field_id == "wizard.secrets_passphrase":
        text = str(value).strip()
        backend = context.get("secrets_backend.type") if isinstance(context, dict) else None
        if backend == "openbao":
            return True, "ok"
        if not text:
            return False, "Passphrase is required for the encrypted_file backend"
        if len(text) < 8:
            return False, "Passphrase must be at least 8 characters"
        return True, "ok"
    if field_id == "wizard.telegram_phone":
        phone = str(value).strip()
        if not phone:
            return True, "ok"
        if not re.fullmatch(r"\+\d{8,15}", phone):
            return False, "use international format like +15551234567 (digits only after the +)"
        return True, "ok"
    if field_id == "wizard.telegram_api_id":
        text = str(value).strip()
        if not text:
            return True, "ok"
        try:
            api_id = int(text)
        except ValueError:
            return False, "api_id must be a positive integer from my.telegram.org/apps"
        if api_id <= 0:
            return False, "api_id must be a positive integer"
        return True, "ok"
    if field_id == "wizard.telegram_api_hash":
        text = str(value).strip()
        if not text:
            return True, "ok"
        if not re.fullmatch(r"[0-9a-fA-F]{32}", text):
            return False, "api_hash must be 32 hex characters from my.telegram.org/apps"
        return True, "ok"
    if field_id == "infrastructure.tunnel.cloudflare.token":
        text = str(value).strip()
        sibling = (
            context.get("infrastructure.tunnel.cloudflare.credentials_file")
            if isinstance(context, dict)
            else None
        )
        mode = context.get("infrastructure.tunnel.mode") if isinstance(context, dict) else None
        if mode == "cloudflare" and not text and not (sibling and str(sibling).strip()):
            return False, "paste a Cloudflare tunnel token or set the credentials_file path below"
        return True, "ok"
    if field_id == "infrastructure.tunnel.cloudflare.credentials_file":
        text = str(value).strip()
        if not text:
            return True, "ok"
        import asyncio as _asyncio

        candidate = await _asyncio.to_thread(_expand_and_test_file, text)
        if not candidate[0]:
            return False, f"file not found: {candidate[1]}"
        return True, "ok"
    if field_id == "infrastructure.tunnel.ngrok.authtoken":
        text = str(value).strip()
        mode = context.get("infrastructure.tunnel.mode") if isinstance(context, dict) else None
        if mode == "ngrok" and not text:
            return False, "ngrok authtoken is required (sign in at https://dashboard.ngrok.com)"
        return True, "ok"
    if field_id == "infrastructure.tunnel.tailscale.hostname":
        return True, "ok"
    if field_id == "infrastructure.tunnel.mode":
        if str(value) not in ("none", "tailscale_serve", "tailscale_funnel", "cloudflare", "ngrok"):
            return False, "unsupported tunnel mode"
        return True, "ok"
    if field_id == "channels.telegram.bot_token_ref":
        text = str(value).strip()
        if not text:
            return True, "ok"
        if text.startswith("${ENV:") and text.endswith("}"):
            return True, "ok"
        return False, "use ${ENV:SEVN_TELEGRAM_BOT_TOKEN} indirection in sevn.json"
    if field_id == "telemetry.enabled":
        return True, "ok"
    if field_id == "secrets_backend.type":
        if str(value) not in ("openbao", "encrypted_file"):
            return False, "secrets_backend.type must be openbao or encrypted_file"
        return True, "ok"
    if field_id == "providers.tier_default.triager":
        if not str(value).strip():
            return False, "main model (triager) is required"
        return True, "ok"
    if field_id == "providers.use_main_model_for_all":
        return True, "ok"
    if field_id.startswith("providers.tier_default.") or field_id in (
        "lcm.summary_model",
        "memory.pre_compaction_flush.model",
        "memory.dreaming.scoring.llm_ranker.model",
        "memory.user_model.extractor_model",
        "security.scanner.model",
    ):
        if not str(value).strip():
            return False, "model id is required when customizing per-slot models"
        return True, "ok"
    if field_id == "agent.display_name":
        if not str(value).strip():
            return False, "bot name is required"
        return True, "ok"
    if field_id == "my_sevn.repo_url":
        text = str(value).strip()
        if not text:
            return False, "repository URL is required"
        if not text.startswith(("http://", "https://")):
            return False, "repository URL must start with http:// or https://"
        return True, "ok"
    if field_id == "my_sevn.workspace_backup.repo_url":
        text = str(value).strip()
        if not text:
            return True, "ok"
        if not text.startswith("https://github.com/"):
            return False, "workspace backup URL must be https://github.com/{owner}/{repo}"
        return True, "ok"
    if field_id in ("my_sevn.sync.enabled", "self_improve.enabled", "self_improve.hub.use_github"):
        return True, "ok"
    return True, "ok"


def _check_workspace(path_str: str) -> dict[str, Any]:
    """Inspect a workspace directory for onboarding UI hints.
    Args:
        path_str (str): Filesystem path (may include ``~``).
    Returns:
        dict[str, Any]: Existence, config presence, and narrative file listing.
    Examples:
        >>> _check_workspace("/no/such/path")["exists"]
        False
    """
    p = Path(path_str).expanduser().resolve()
    if not p.exists():
        return {"exists": False, "path": str(p)}
    sevn_json = p / "sevn.json"
    draft = p / ".sevn.json.draft"
    summary: dict[str, Any] = {}
    if sevn_json.is_file():
        try:
            cfg = json.loads(sevn_json.read_text(encoding="utf-8"))
            if isinstance(cfg, dict):
                gw_raw = cfg.get("gateway")
                gw: dict[str, Any] = gw_raw if isinstance(gw_raw, dict) else {}
                summary = {
                    "gateway_port": gw.get("port"),
                    "has_channels": bool(cfg.get("channels")),
                    "schema_version": cfg.get("schema_version"),
                }
        except (OSError, json.JSONDecodeError):
            summary = {"parse_error": True}
    md_files = sorted(f.name for f in p.glob("*.md") if f.is_file())
    return {
        "exists": True,
        "path": str(p),
        "has_config": sevn_json.is_file(),
        "has_draft": draft.is_file(),
        "config_summary": summary,
        "files": {
            "md_files": md_files,
            "has_sevn_dir": (p / ".sevn").is_dir(),
            "has_logs": (p / "logs").is_dir(),
        },
    }


def create_onboarding_app(
    onboard_token: str,
    *,
    sevn_json_path: Path | None = None,
    onboard_port: int = 8844,
) -> FastAPI:
    """Build a loopback wizard app guarded by ``onboard_token`` (query, header, or cookie).
    Args:
        onboard_token (str): Nonce minted by the CLI (`specs/22-onboarding.md` §4.6).
        sevn_json_path (Path | None): Target ``sevn.json``; defaults to CLI-bound workspace.
        onboard_port (int): Loopback bind port for OAuth callback URI construction.
    Returns:
        FastAPI: App instance (caller runs with ``uvicorn``).
    Examples:
        >>> from sevn.onboarding.web_app import create_onboarding_app
        >>> create_onboarding_app("x").title.startswith("sevn")
        True
    """
    created_mono = time.monotonic()
    target_json = sevn_json_path

    def _resolve_sevn_json() -> Path:
        if target_json is not None:
            return target_json.expanduser().resolve()
        from sevn.cli.workspace import bound_sevn_json_path

        return bound_sevn_json_path()

    @asynccontextmanager
    async def _wizard_lifespan(_app: FastAPI) -> AsyncIterator[None]:
        register_shutdown_hooks()
        yield
        await stop_browser_on_shutdown()

    app = FastAPI(title="sevn onboarding wizard", version="0", lifespan=_wizard_lifespan)
    register_shared_ui_routes(app)

    async def _require_token_union(
        response: Response,
        onboard_token_q: Annotated[str | None, Query(alias="onboard_token")] = None,
        x_onboard_token: Annotated[str | None, Header(alias="X-Onboard-Token")] = None,
        session_cookie: Annotated[str | None, Cookie(alias=ONBOARD_SESSION_COOKIE)] = None,
    ) -> None:
        fresh = onboard_token_q or x_onboard_token
        token = fresh or session_cookie
        if token != onboard_token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid or missing onboard_token",
            )
        age = time.monotonic() - created_mono
        if age > ONBOARDING_TOKEN_TTL_SECONDS:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="onboard_token expired — restart `sevn onboard --web`",
            )
        if fresh is not None:
            remaining = max(1, int(ONBOARDING_TOKEN_TTL_SECONDS - age))
            response.set_cookie(
                key=ONBOARD_SESSION_COOKIE,
                value=onboard_token,
                max_age=remaining,
                httponly=True,
                samesite="strict",
                path="/",
            )

    @app.get("/healthz", response_class=PlainTextResponse)
    async def healthz() -> str:
        """Unauthenticated health for local process managers."""
        return "ok"

    @app.get("/api/field-help", response_class=JSONResponse)
    async def api_field_help(_: None = Depends(_require_token_union)) -> dict[str, Any]:
        """Return per-field long descriptions for the wizard UI."""
        return {"fields": _load_field_help_paths()}

    @app.get("/", response_class=HTMLResponse)
    async def shell(
        response: Response,
        _: None = Depends(_require_token_union),
    ) -> HTMLResponse:
        """Serve the packaged wizard shell."""
        text = (WIZARD_STATIC_ROOT / "index.html").read_text(encoding="utf-8")
        out = HTMLResponse(content=text)
        if "set-cookie" in response.headers:
            out.headers["set-cookie"] = response.headers["set-cookie"]
        return out

    @app.get("/wizard/{asset_path:path}")
    async def wizard_static(
        asset_path: str,
        _: None = Depends(_require_token_union),
    ) -> Response:
        """Serve ``style.css`` and ``app.js`` from the packaged wizard tree."""
        return _serve_wizard_asset(asset_path)

    @app.get("/api/meta", response_class=JSONResponse)
    async def api_meta(_: None = Depends(_require_token_union)) -> dict[str, Any]:
        """Bootstrap catalog, defaults, and schema hints for the wizard UI."""
        sj = _resolve_sevn_json()
        return {
            "profiles": load_profile_catalog_for_wizard(),
            "defaults": _DEFAULT_BASE,
            "fresh_install": not sj.is_file(),
            "onboard_port": onboard_port,
            "supported_schema_versions": sorted(SUPPORTED_SCHEMA_VERSIONS),
            "sevn_json_path": str(sj),
            "steps": [
                {"id": "profile", "title": "Profile"},
                {"id": "workspace", "title": "Workspace"},
                {"id": "my_sevn", "title": "My Sevn.bot"},
                {"id": "model", "title": "Main model"},
                {"id": "capabilities", "title": "Capabilities"},
                {"id": "channels", "title": "Channels"},
                {"id": "secrets", "title": "Secrets backend"},
                {"id": "sandbox", "title": "Sandbox"},
                {"id": "tunnel", "title": "Public access"},
                {"id": "personality", "title": "Personality"},
                {"id": "validate", "title": "Live validation"},
                {"id": "promote", "title": "Save & promote"},
                {"id": "handoff", "title": "Handoff"},
            ],
        }

    @app.get("/api/personality-presets", response_class=JSONResponse)
    async def api_personality_presets(_: None = Depends(_require_token_union)) -> dict[str, Any]:
        """Return style and preferences dropdown presets for the Personality step."""
        return load_personality_presets()

    @app.get("/api/capabilities", response_class=JSONResponse)
    async def api_capabilities(
        profile_id: str | None = Query(default=None),
        _: None = Depends(_require_token_union),
    ) -> dict[str, Any]:
        """Return grouped capability manifest with profile-merged defaults."""
        manifest = load_manifest()
        fragment: dict[str, Any] | None = None
        pid = (profile_id or "").strip()
        if pid and pid != "skip":
            try:
                fragment = load_profile_fragment(pid)
            except FileNotFoundError as exc:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"unknown profile_id={pid!r}",
                ) from exc
        defaults = merged_capability_defaults(profile_fragment=fragment, manifest=manifest)
        groups_out: list[dict[str, Any]] = []
        for group in list_groups(manifest):
            caps: list[dict[str, Any]] = []
            for cap in group.capabilities:
                row = dict(cap)
                row["merged_default"] = defaults.get(str(cap["capability_id"]), cap.get("default"))
                caps.append(row)
            groups_out.append(
                {
                    "id": group.id,
                    "label": group.label,
                    "description": group.description,
                    "sort_order": group.sort_order,
                    "capabilities": caps,
                }
            )
        return {
            "schema_version": manifest.schema_version,
            "profile_id": pid or None,
            "groups": groups_out,
            "defaults": defaults,
        }

    @app.get("/api/onboarding/folder-picker", response_class=JSONResponse)
    async def api_onboarding_folder_picker(
        path: str = Query(default="."),
        _: None = Depends(_require_token_union),
    ) -> dict[str, Any]:
        """List workspace subdirectories for onboarding folder_picker controls."""
        from sevn.second_brain.bootstrap import detect_layout
        from sevn.second_brain.folder_picker import list_workspace_subdirs, normalise_browse_path

        content_root = _content_root_for_wizard()
        rel = normalise_browse_path(path)
        entries = list_workspace_subdirs(content_root, rel)
        detected_layout: str | None = None
        adoption_note: str | None = None
        if rel and rel != ".":
            target = (content_root / rel).resolve()
            if target.is_dir():
                detected_layout = detect_layout(target)
                if detected_layout == "para":
                    adoption_note = (
                        "Existing PARA vault detected — choose layout para to adopt "
                        "non-destructively (missing folders only)."
                    )
        return {
            "path": rel,
            "entries": entries,
            "detected_layout": detected_layout,
            "adoption_note": adoption_note,
        }

    @app.get("/api/profile-inspector", response_class=JSONResponse)
    async def api_profile_inspector(
        profile_id: str = Query(..., min_length=1),
        _: None = Depends(_require_token_union),
    ) -> dict[str, Any]:
        """Return read-only tab-grouped rows for a preset profile (D12 / W7)."""
        pid = profile_id.strip()
        if pid == "skip":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="profile_id cannot be 'skip'",
            )
        try:
            from sevn.onboarding.profile_inspector import (
                build_profile_inspector_payload,
            )

            return build_profile_inspector_payload(pid)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc
        except FileNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"unknown profile_id={pid!r}",
            ) from exc

    @app.get("/api/browser/agpl-notice", response_class=JSONResponse)
    async def api_browser_agpl_notice(_: None = Depends(_require_token_union)) -> dict[str, Any]:
        """Return browser engine metadata (legacy route; no AGPL notice required)."""
        return {"browser_engine": "cdp"}

    @app.post("/api/browser/start", response_class=JSONResponse)
    async def api_browser_start(
        request: Request,
        _: None = Depends(_require_token_union),
    ) -> JSONResponse:
        """Start or attach system Chrome for onboarding automation (D3)."""
        data = await request.json()
        if data is not None and not isinstance(data, dict):
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"ok": False, "detail": "body must be a JSON object"},
            )
        body = data if isinstance(data, dict) else {}
        cdp_url = body.get("cdp_url")
        user_data_dir = body.get("user_data_dir")
        if cdp_url is not None and not isinstance(cdp_url, str):
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"ok": False, "detail": "cdp_url must be a string"},
            )
        if user_data_dir is not None and not isinstance(user_data_dir, str):
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"ok": False, "detail": "user_data_dir must be a string"},
            )
        session = get_browser_session()
        try:
            payload = await session.start(
                cdp_url=cdp_url,
                user_data_dir=user_data_dir,
            )
        except ImportError as exc:
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={"ok": False, "detail": str(exc)},
            )
        except (RuntimeError, OSError) as exc:
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={"ok": False, "detail": str(exc)},
            )
        return JSONResponse({"ok": True, **payload})

    @app.post("/api/browser/stop", response_class=JSONResponse)
    async def api_browser_stop(_: None = Depends(_require_token_union)) -> JSONResponse:
        """Stop onboarding browser automation and release CDP attach."""
        payload = await get_browser_session().stop()
        return JSONResponse({"ok": True, **payload})

    @app.get("/api/browser/status", response_class=JSONResponse)
    async def api_browser_status(_: None = Depends(_require_token_union)) -> dict[str, Any]:
        """Poll automation progress steps and session health."""
        return get_browser_session().status_payload()

    async def _ensure_browser_for_telegram() -> BrowserSession:
        """Start the shared browser session when idle (D3 / W5)."""
        session = get_browser_session()
        if not session.running:
            await session.start()
        return session

    def _telegram_extract_response(
        extract: TelegramBotExtract,
        *,
        written: dict[str, bool],
    ) -> dict[str, Any]:
        """Build a token-gated JSON body without logging raw secrets."""
        return {
            "ok": True,
            "bot_username": extract.bot_username,
            "suggested_owner_user_id": extract.owner_user_id,
            "token_stored": bool(written.get("SEVN_TELEGRAM_BOT_TOKEN")),
            "bot_token": extract.bot_token,
            "steps": get_browser_session().status_payload().get("steps", []),
        }

    @app.post("/api/telegram/login", response_class=JSONResponse)
    async def api_telegram_login(_: None = Depends(_require_token_union)) -> JSONResponse:
        """Open Telegram Web in the onboarding browser session (W5.4)."""
        try:
            session = await _ensure_browser_for_telegram()
            tab = await open_telegram_web(session)
            await wait_for_login(session)
        except ImportError as exc:
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={"ok": False, "detail": str(exc)},
            )
        except (RuntimeError, OSError, TimeoutError) as exc:
            logger.warning("telegram_login_failed err={}", _redact_detail(str(exc)))
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={"ok": False, "detail": _redact_detail(str(exc))},
            )
        return JSONResponse({"ok": True, "logged_in": True, "tab": tab, **session.status_payload()})

    @app.post("/api/telegram/automate", response_class=JSONResponse)
    async def api_telegram_automate(
        request: Request,
        _: None = Depends(_require_token_union),
    ) -> JSONResponse:
        """Run BotFather create or lookup flow; store token via wizard credentials (W5.2-W5.5)."""
        data = await request.json()
        if not isinstance(data, dict):
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"ok": False, "detail": "body must be a JSON object"},
            )
        create_new = data.get("create_new", True)
        if not isinstance(create_new, bool):
            create_new = str(create_new).lower() in ("1", "true", "yes")
        display_name = data.get("display_name")
        bot_username_raw = data.get("bot_username")
        try:
            session = await _ensure_browser_for_telegram()
            if create_new:
                if not isinstance(display_name, str) or not display_name.strip():
                    return JSONResponse(
                        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                        content={
                            "ok": False,
                            "detail": "display_name (bot name) is required when create_new is true",
                        },
                    )
                extract = await run_create_new_bot(session, display_name=display_name.strip())
            else:
                if not isinstance(bot_username_raw, str) or not bot_username_raw.strip():
                    return JSONResponse(
                        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                        content={
                            "ok": False,
                            "detail": "bot_username is required when create_new is false",
                        },
                    )
                extract = await run_lookup_existing_bot(session, bot_username=bot_username_raw)
        except ImportError as exc:
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={"ok": False, "detail": str(exc)},
            )
        except ValueError as exc:
            return JSONResponse(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                content={"ok": False, "detail": str(exc)},
            )
        except (RuntimeError, OSError, TimeoutError) as exc:
            logger.warning("telegram_automate_failed err={}", _redact_detail(str(exc)))
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={"ok": False, "detail": _redact_detail(str(exc))},
            )
        cred_root, cred_section = _wizard_credentials_context()
        written = await store_wizard_credentials(
            cred_root,
            bot_token=extract.bot_token,
            section=cred_section,
        )
        logger.info(
            "telegram_automate_ok username={} token_stored={}",
            extract.bot_username,
            bool(written.get("SEVN_TELEGRAM_BOT_TOKEN")),
        )
        return JSONResponse(_telegram_extract_response(extract, written=written))

    def _my_telegram_api_response(
        extract: MyTelegramApiExtract,
        *,
        written: dict[str, bool],
    ) -> dict[str, Any]:
        """Build JSON for my.telegram.org credential extraction."""
        return {
            "ok": True,
            "api_id": extract.api_id,
            "api_hash": extract.api_hash,
            "phone": extract.phone,
            "api_stored": bool(written.get("SEVN_TELEGRAM_API_ID")),
            "hash_stored": bool(written.get("SEVN_TELEGRAM_API_HASH")),
            "steps": get_browser_session().status_payload().get("steps", []),
        }

    @app.post("/api/telegram/my-api", response_class=JSONResponse)
    async def api_telegram_my_api(
        request: Request,
        _: None = Depends(_require_token_union),
    ) -> JSONResponse:
        """Fetch api_id/api_hash from my.telegram.org via CDP browser automation (optional phone)."""
        data = await request.json()
        if not isinstance(data, dict):
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"ok": False, "detail": "body must be a JSON object"},
            )
        phone_raw = data.get("phone")
        phone = phone_raw if isinstance(phone_raw, str) and phone_raw.strip() else None
        try:
            session = await _ensure_browser_for_telegram()
            extract = await run_fetch_my_telegram_api(session, phone=phone)
        except MyTelegramSkipError as exc:
            logger.info("telegram_my_api_skipped reason={}", exc.reason)
            with suppress(Exception):
                await get_browser_session().stop()
            return JSONResponse(
                {
                    "ok": True,
                    "skipped": True,
                    "skip_reason": exc.reason,
                    "detail": exc.message,
                    "configure_later": CONFIGURE_LATER_HINT,
                    "steps": get_browser_session().status_payload().get("steps", []),
                }
            )
        except ImportError as exc:
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={"ok": False, "detail": str(exc)},
            )
        except ValueError as exc:
            return JSONResponse(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                content={"ok": False, "detail": str(exc)},
            )
        except (RuntimeError, OSError, TimeoutError) as exc:
            logger.warning("telegram_my_api_failed err={}", _redact_detail(str(exc)))
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={"ok": False, "detail": _redact_detail(str(exc))},
            )
        cred_root, cred_section = _wizard_credentials_context()
        written = await store_wizard_credentials(
            cred_root,
            telegram_api_id=extract.api_id,
            telegram_api_hash=extract.api_hash,
            telegram_phone=extract.phone,
            section=cred_section,
        )
        logger.info(
            "telegram_my_api_ok api_stored={} hash_stored={}",
            bool(written.get("SEVN_TELEGRAM_API_ID")),
            bool(written.get("SEVN_TELEGRAM_API_HASH")),
        )
        return JSONResponse(_my_telegram_api_response(extract, written=written))

    @app.get("/api/discover-install", response_class=JSONResponse)
    async def api_discover_install(_: None = Depends(_require_token_union)) -> dict[str, Any]:
        """List installed operator homes and whether step 00 should appear."""
        from sevn.cli.install_discovery import candidate_to_dict
        from sevn.onboarding.install_gate import install_gate_state

        state = install_gate_state()
        return {
            "show_gate": state.show_gate,
            "active_home": str(state.active_home),
            "active_has_config": state.active_has_config,
            "active_has_workspace_artifacts": state.active_has_workspace_artifacts,
            "active_has_keystore": state.active_has_keystore,
            "candidates": [candidate_to_dict(row) for row in state.candidates],
        }

    @app.post("/api/resolve-install", response_class=JSONResponse)
    async def api_resolve_install(
        request: Request,
        _: None = Depends(_require_token_union),
    ) -> JSONResponse:
        """Bind ``SEVN_HOME`` after reuse or wipe (step 00)."""
        from sevn.cli.operator_lock import OperatorLockHeld
        from sevn.cli.service_manager import ServiceManagerError
        from sevn.onboarding.install_gate import (
            apply_install_resolution,
            resolve_install_action,
        )

        data = await request.json()
        if not isinstance(data, dict):
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"ok": False, "detail": "body must be a JSON object"},
            )
        action = str(data.get("action", ""))
        home_raw = data.get("home")
        if not isinstance(home_raw, str) or not home_raw.strip():
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"ok": False, "detail": "home is required"},
            )
        confirm = data.get("confirm")
        confirm_str = confirm if isinstance(confirm, str) else None
        try:
            resolution = resolve_install_action(
                action=action,
                home=Path(home_raw),
                confirm=confirm_str,
            )
        except ValueError as exc:
            return JSONResponse(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                content={"ok": False, "detail": str(exc)},
            )
        except (OperatorLockHeld, ServiceManagerError) as exc:
            return JSONResponse(
                status_code=status.HTTP_409_CONFLICT,
                content={"ok": False, "detail": str(exc)},
            )
        bound = apply_install_resolution(resolution)
        return JSONResponse(
            {
                "ok": True,
                "home": str(bound),
                "reuse": resolution.reuse,
            }
        )

    @app.post("/api/replace-keystore", response_class=JSONResponse)
    async def api_replace_keystore(_: None = Depends(_require_token_union)) -> dict[str, Any]:
        """Delete the encrypted keystore so the operator can re-enter credentials."""
        from sevn.onboarding.install_gate import replace_keystore

        sj = _resolve_sevn_json()
        removed = replace_keystore(sevn_json=sj)
        return {
            "ok": True,
            "removed": str(removed) if removed is not None else None,
        }

    @app.get("/api/existing-config", response_class=JSONResponse)
    async def api_existing_config(_: None = Depends(_require_token_union)) -> dict[str, Any]:
        """Return promoted config and/or draft for resume."""
        from sevn.cli.install_discovery import (
            resolve_keystore_path,
            resolve_workspace_keystore_path,
            workspace_has_artifacts,
        )
        from sevn.cli.install_gate import parse_reuse_from_env

        sj = _resolve_sevn_json()
        workspace_dir = sj.parent
        gate_resolved = os.environ.get("SEVN_ONBOARD_GATE_RESOLVED") == "1"
        has_artifacts = workspace_has_artifacts(workspace_dir)
        if has_artifacts and not gate_resolved:
            return {
                "exists": False,
                "config": {},
                "draft": None,
                "draft_exists": False,
                "reuse": False,
                "should_prefill_secrets": False,
                "gate_required": True,
                "credentials_status": {"present": {}, "ready_for_handoff": False},
                "has_keystore": resolve_workspace_keystore_path(workspace_dir) is not None,
                "keystore_path": None,
                "needs_passphrase": False,  # nosec B105 — wizard UI flag, not a credential
                "keystore_locked": False,
                "wizard_secrets": {},
            }
        promoted: dict[str, Any] | None = None
        if sj.is_file():
            raw = json.loads(sj.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                promoted = raw
        draft = read_draft(sj)
        reuse = parse_reuse_from_env()
        should_prefill_secrets = gate_resolved and (reuse or promoted is not None)
        content_root, section = _wizard_credentials_context()
        cred = await credentials_status(content_root, section=section)
        keystore = resolve_keystore_path(sevn_json=sj) if sj.is_file() else None
        if keystore is None:
            keystore = resolve_workspace_keystore_path(workspace_dir)
        wizard_secrets: dict[str, str] = {}
        if should_prefill_secrets:
            provider_names: frozenset[str] | None = None
            cfg_doc = promoted or draft
            if isinstance(cfg_doc, dict):
                provider_names = assigned_provider_names_from_doc(cfg_doc)
            try:
                wizard_secrets = await read_wizard_credential_values(
                    content_root,
                    section=section,
                    provider_names=provider_names,
                )
            except SecretsStoreCorruptError:
                wizard_secrets = {}
        return {
            "exists": promoted is not None,
            "config": promoted or {},
            "draft": draft,
            "draft_exists": draft is not None,
            "reuse": reuse,
            "should_prefill_secrets": should_prefill_secrets,
            "credentials_status": cred,
            "has_keystore": keystore is not None,
            "keystore_path": str(keystore) if keystore is not None else None,
            "needs_passphrase": bool(cred.get("needs_passphrase")),
            "keystore_locked": bool(cred.get("keystore_locked")),
            "wizard_secrets": wizard_secrets,
        }

    @app.get("/api/check-workspace", response_class=JSONResponse)
    async def api_check_workspace(
        path: str = "",
        _: None = Depends(_require_token_union),
    ) -> dict[str, Any]:
        """Check workspace directory contents."""
        sj = _resolve_sevn_json()
        if not path.strip() or path.strip() in (".", "./"):
            from sevn.config.workspace_config import WorkspaceConfig

            cfg = WorkspaceConfig.minimal(workspace_root=".")
            layout = WorkspaceLayout.from_config(sj, cfg)
            path = str(layout.content_root)
        return _check_workspace(path)

    @app.post("/api/validate-field", response_class=JSONResponse)
    async def api_validate_field(
        request: Request,
        _: None = Depends(_require_token_union),
    ) -> JSONResponse:
        """Validate a single credential or config field."""
        data = await request.json()
        if not isinstance(data, dict):
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"ok": False, "detail": "body must be a JSON object"},
            )
        field_id = str(data.get("field_id", ""))
        raw_ctx = data.get("context")
        ctx: dict[str, Any] = raw_ctx if isinstance(raw_ctx, dict) else {}
        ok, message = await _validate_field(
            field_id,
            data.get("value"),
            context=ctx,
        )
        status_code = status.HTTP_200_OK if ok else status.HTTP_422_UNPROCESSABLE_CONTENT
        return JSONResponse(
            status_code=status_code, content={"ok": ok, "message": message, "field": field_id}
        )

    @app.post("/api/validate-all", response_class=JSONResponse)
    async def api_validate_all(
        request: Request,
        _: None = Depends(_require_token_union),
    ) -> JSONResponse:
        """Schema-validate merged preview and run live probes."""
        data = await request.json()
        if not isinstance(data, dict):
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"ok": False, "detail": "body must be a JSON object"},
            )
        profile_id = data.get("profile_id")
        pid = profile_id if isinstance(profile_id, str) else None
        try:
            merged = _merge_wizard_payload(data, profile_id=pid)
            normalize_secrets_backend_section(merged)
            validate_workspace_document(merged)
        except (ValidationError, UnsupportedSchemaVersionError, ValueError, OSError) as exc:
            return _validation_error_response(exc)
        sj = _resolve_sevn_json()
        from sevn.config.workspace_config import parse_workspace_config

        parsed = parse_workspace_config(merged)
        layout = WorkspaceLayout.from_config(sj, parsed)
        raw_fields = data.get("fields")
        fields: dict[str, Any] = raw_fields if isinstance(raw_fields, dict) else {}

        def _str_field(name: str) -> str | None:
            val = fields.get(name)
            return val if isinstance(val, str) else None

        await store_wizard_credentials(
            layout.content_root,
            gateway_token=_wizard_gateway_token_plaintext(fields),
            github_token=_str_field("wizard.github_token"),
            openwiki_llm_api_key=_str_field("wizard.openwiki_llm_api_key"),
            bot_token=_str_field("wizard.telegram_bot_token"),
            provider_api_keys=_provider_api_keys_from_fields(fields),
            telegram_api_id=_str_field("wizard.telegram_api_id"),
            telegram_api_hash=_str_field("wizard.telegram_api_hash"),
            telegram_phone=_str_field("wizard.telegram_phone"),
            secrets_passphrase=_str_field("wizard.secrets_passphrase"),
            section=parsed.secrets_backend,
        )
        report = await run_live_validation(
            workspace_root=layout.content_root,
            merged_preview=merged,
            profile_id=pid,
        )
        from sevn.onboarding.live_validate import install_status_to_dict

        return JSONResponse(
            {
                "ok": not report.has_error(),
                "schema_ok": True,
                "live_validation": [
                    {
                        "check_id": c.check_id,
                        "ok": c.ok,
                        "severity": c.severity,
                        "detail": _redact_detail(c.detail),
                        "hint": c.hint,
                    }
                    for c in report.checks
                ],
                "install_status": [install_status_to_dict(row) for row in report.install_status],
            }
        )

    @app.post("/api/install-plan", response_class=JSONResponse)
    async def api_install_plan(
        request: Request,
        _: None = Depends(_require_token_union),
    ) -> JSONResponse:
        """Dry-run install plan for selected capabilities (D2 phase a)."""
        from sevn.onboarding.install_orchestrator import build_install_plan

        data = await request.json()
        if not isinstance(data, dict):
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"ok": False, "detail": "body must be a JSON object"},
            )
        profile_id = data.get("profile_id")
        pid = profile_id if isinstance(profile_id, str) else None
        try:
            merged = _merge_wizard_payload(data, profile_id=pid)
            plan = build_install_plan(merged)
        except ValueError as exc:
            return JSONResponse(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                content={"ok": False, "detail": _redact_detail(str(exc))},
            )
        return JSONResponse({"ok": True, **plan.to_dict()})

    @app.post("/api/install-run")
    async def api_install_run(
        request: Request,
        _: None = Depends(_require_token_union),
    ) -> StreamingResponse:
        """Execute install plan with NDJSON progress lines (D2 phase b)."""
        from sevn.onboarding.install_orchestrator import (
            build_install_plan,
            format_ndjson_event,
            run_install_plan,
        )

        data = await request.json()
        if not isinstance(data, dict):
            return StreamingResponse(
                iter([format_ndjson_event({"type": "error", "detail": "body must be object"})]),
                media_type="application/x-ndjson",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        profile_id = data.get("profile_id")
        pid = profile_id if isinstance(profile_id, str) else None
        try:
            merged = _merge_wizard_payload(data, profile_id=pid)
            plan = build_install_plan(merged)
        except ValueError as exc:
            return StreamingResponse(
                iter([format_ndjson_event({"type": "error", "detail": _redact_detail(str(exc))})]),
                media_type="application/x-ndjson",
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            )
        content_root = _content_root_for_wizard()

        async def _stream() -> AsyncIterator[str]:
            async for event in run_install_plan(
                plan,
                merged_config=merged,
                content_root=content_root,
            ):
                yield format_ndjson_event(event)

        return StreamingResponse(_stream(), media_type="application/x-ndjson")

    @app.post("/api/save", response_class=JSONResponse)
    async def api_save(
        request: Request,
        _: None = Depends(_require_token_union),
    ) -> JSONResponse:
        """Merge, validate, write draft, promote, and seed narrative templates."""
        from sevn.onboarding.install_orchestrator import (
            build_install_plan,
            collect_install_run,
            selected_capability_ids,
        )
        from sevn.onboarding.seed import (
            opt_in_skill_ids_from_capabilities,
            seed_bundled_skills,
        )

        data = await request.json()
        if not isinstance(data, dict):
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"ok": False, "detail": "body must be a JSON object"},
            )
        profile_id = data.get("profile_id")
        pid = profile_id if isinstance(profile_id, str) else None
        sj = _resolve_sevn_json()
        sj.parent.mkdir(parents=True, exist_ok=True)
        try:
            merged = _merge_wizard_payload(data, profile_id=pid)
            await _stamp_openai_oauth_auth_mode(merged)
            normalize_secrets_backend_section(merged)
            validate_workspace_document(merged)
            # Route any wizard-collected secrets through the operator's chosen
            # `secrets_backend` chain before promoting, so a user who picked
            # encrypted_file with a custom path / passphrase actually lands the
            # bot token + provider key in that file (not the host-default chain).
            from sevn.config.workspace_config import parse_workspace_config

            parsed = parse_workspace_config(merged)
            section = parsed.secrets_backend
            raw_fields = data.get("fields")
            fields: dict[str, Any] = raw_fields if isinstance(raw_fields, dict) else {}

            def _str_field(name: str) -> str | None:
                val = fields.get(name)
                return val if isinstance(val, str) else None

            await store_wizard_credentials(
                _content_root_for_wizard(),
                gateway_token=_wizard_gateway_token_plaintext(fields),
                github_token=_str_field("wizard.github_token"),
                openwiki_llm_api_key=_str_field("wizard.openwiki_llm_api_key"),
                bot_token=_str_field("wizard.telegram_bot_token"),
                provider_api_keys=_provider_api_keys_from_fields(fields),
                telegram_api_id=_str_field("wizard.telegram_api_id"),
                telegram_api_hash=_str_field("wizard.telegram_api_hash"),
                telegram_phone=_str_field("wizard.telegram_phone"),
                secrets_passphrase=_str_field("wizard.secrets_passphrase"),
                section=section,
            )
            cred_root, cred_section = _wizard_credentials_context()
            cred = await credentials_status(cred_root, section=cred_section, config_doc=merged)
            if not cred.get("ready_for_handoff"):
                return JSONResponse(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    content={
                        "ok": False,
                        "detail": "store required credentials (gateway, Telegram, provider keys) before saving",
                    },
                )
            apply_web_ui_url_for_dashboard(merged)
            write_draft(sj, merged)
            promote_draft(sj, backup_previous=sj.is_file())
            seeded = seed_narrative_templates(sj, merged)
            cfg = parse_workspace_config(merged)
            content_root = WorkspaceLayout.from_config(sj, cfg).content_root
            personality_seeded = seed_personality_from_wizard(content_root, merged)
            seeded = [*seeded, *personality_seeded]
            selected_caps = selected_capability_ids(merged)
            seed_bundled_skills(
                content_root,
                enabled_opt_in_skill_ids=opt_in_skill_ids_from_capabilities(selected_caps),
            )
            install_plan = build_install_plan(merged)
            install_summary = await collect_install_run(
                install_plan,
                merged_config=merged,
                content_root=content_root,
            )
            seeded_skill_ids = list_deployed_core_skill_ids(content_root)
            missing_core_skills = verify_core_skills_deployed(content_root)
        except (ValidationError, UnsupportedSchemaVersionError, ValueError, OSError) as exc:
            return _validation_error_response(exc)
        daemon_install: str | None = None
        daemon_install_error: str | None = None
        from sevn.cli.install_gate import maybe_install_daemon_after_promote
        from sevn.cli.operator_lock import OperatorLockHeld
        from sevn.cli.service_manager import ServiceManagerError

        try:
            daemon_install = maybe_install_daemon_after_promote()
        except (OperatorLockHeld, ServiceManagerError) as exc:
            daemon_install_error = str(exc)
        payload: dict[str, Any] = {
            "ok": True,
            "message": "Configuration saved and promoted",
            "sevn_json": str(sj),
            "seeded_files": [str(p) for p in seeded],
            "seeded_skills_count": len(seeded_skill_ids),
            "seeded_skill_ids": seeded_skill_ids,
            "missing_core_skills": missing_core_skills,
            "install": install_summary.to_dict(),
        }
        if daemon_install:
            payload["daemon_install"] = daemon_install
        if daemon_install_error:
            payload["daemon_install_error"] = daemon_install_error
        import asyncio

        from sevn.onboarding.service_restart import restart_services_after_promote

        try:
            restart_body = await asyncio.to_thread(
                restart_services_after_promote,
                sevn_json_path=sj,
            )
        except Exception as exc:
            payload["services_restart_error"] = str(exc)
        else:
            payload["services_restart"] = restart_body
        return JSONResponse(payload)

    def _content_root_for_wizard() -> Path:
        sj = _resolve_sevn_json()
        from sevn.config.workspace_config import WorkspaceConfig

        return WorkspaceLayout.from_config(
            sj, WorkspaceConfig.minimal(workspace_root=".")
        ).content_root

    def _wizard_credentials_context() -> tuple[Path, Any]:
        sj = _resolve_sevn_json()
        return _content_root_for_wizard(), secrets_section_from_sevn_json(sj)

    def _wizard_config_doc_for_credentials() -> dict[str, Any] | None:
        sj = _resolve_sevn_json()
        from sevn.onboarding.draft_store import read_draft

        draft = read_draft(sj)
        if isinstance(draft, dict):
            return draft
        if sj.is_file():
            try:
                raw = json.loads(sj.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return None
            return raw if isinstance(raw, dict) else None
        return None

    async def _stamp_openai_oauth_auth_mode(doc: dict[str, Any]) -> None:
        """Set ``providers.openai.auth_mode=oauth`` when ``oauth.openai`` is stored (D1)."""
        from sevn.security.oauth.storage import load_codex_oauth_credential
        from sevn.security.secrets.factory import secrets_chain_from_workspace

        cred_root, cred_section = _wizard_credentials_context()
        chain = secrets_chain_from_workspace(cred_root, cred_section)
        try:
            credential = await load_codex_oauth_credential(chain)
        except ValueError:
            credential = None
        if credential is None:
            return
        providers = doc.setdefault("providers", {})
        if not isinstance(providers, dict):
            return
        openai_block = providers.setdefault("openai", {})
        if isinstance(openai_block, dict):
            openai_block["auth_mode"] = "oauth"

    @app.get("/api/credentials-status", response_class=JSONResponse)
    async def api_credentials_status(_: None = Depends(_require_token_union)) -> dict[str, Any]:
        """Return which wizard secrets are stored for this workspace."""
        content_root, section = _wizard_credentials_context()
        return await credentials_status(
            content_root,
            section=section,
            config_doc=_wizard_config_doc_for_credentials(),
        )

    @app.post("/api/verify-passphrase", response_class=JSONResponse)
    async def api_verify_passphrase(
        request: Request,
        _: None = Depends(_require_token_union),
    ) -> JSONResponse:
        """Verify the encrypted keystore passphrase before the wizard proceeds."""
        data = await request.json()
        if not isinstance(data, dict):
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"ok": False, "detail": "body must be a JSON object"},
            )
        passphrase = data.get("passphrase")
        if not isinstance(passphrase, str) or not passphrase.strip():
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"ok": False, "detail": "passphrase is required"},
            )
        content_root, section = _wizard_credentials_context()
        body = await verify_wizard_passphrase(
            content_root,
            passphrase,
            section=section,
        )
        if not body.get("ok"):
            return JSONResponse(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                content=body,
            )
        return JSONResponse(body)

    @app.post("/api/unlock-keystore", response_class=JSONResponse)
    async def api_unlock_keystore(
        request: Request,
        _: None = Depends(_require_token_union),
    ) -> JSONResponse:
        """Unlock an existing encrypted keystore with the operator passphrase."""
        data = await request.json()
        if not isinstance(data, dict):
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"ok": False, "detail": "body must be a JSON object"},
            )
        passphrase = data.get("passphrase")
        if not isinstance(passphrase, str) or not passphrase.strip():
            return JSONResponse(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                content={"ok": False, "detail": "passphrase is required"},
            )
        content_root, section = _wizard_credentials_context()
        try:
            body = await unlock_wizard_keystore(
                content_root,
                passphrase,
                section=section,
            )
        except SecretsStoreCorruptError as exc:
            return JSONResponse(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                content={"ok": False, "detail": _redact_detail(str(exc))},
            )
        if not body.get("ok"):
            return JSONResponse(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                content=body,
            )
        secrets = await read_wizard_credential_values(content_root, section=section)
        if isinstance(passphrase, str) and passphrase.strip():
            secrets.setdefault("SEVN_SECRETS_PASSPHRASE", passphrase.strip())
        return JSONResponse({**body, "secrets": secrets})

    @app.post("/api/credentials", response_class=JSONResponse)
    async def api_credentials(
        request: Request,
        _: None = Depends(_require_token_union),
    ) -> JSONResponse:
        """Persist bot token, provider key, and optional Telegram user API secrets."""
        data = await request.json()
        if not isinstance(data, dict):
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"ok": False, "detail": "body must be a JSON object"},
            )
        cred_root, cred_section = _wizard_credentials_context()
        passphrase_raw = data.get("secrets_passphrase")
        passphrase = passphrase_raw if isinstance(passphrase_raw, str) else None
        if cred_section is not None:
            section = cred_section
        elif passphrase and passphrase.strip():
            section = resolve_wizard_secrets_section(None)
        else:
            section = None
        gateway_raw = data.get("gateway_token")
        gateway_tok = gateway_raw if isinstance(gateway_raw, str) and gateway_raw.strip() else None
        written = await store_wizard_credentials(
            _content_root_for_wizard(),
            gateway_token=gateway_tok,
            github_token=data.get("github_token")
            if isinstance(data.get("github_token"), str)
            else None,
            bot_token=data.get("bot_token") if isinstance(data.get("bot_token"), str) else None,
            provider_api_keys=_provider_api_keys_from_data(data),
            telegram_api_id=data.get("telegram_api_id")
            if isinstance(data.get("telegram_api_id"), str)
            else None,
            telegram_api_hash=data.get("telegram_api_hash")
            if isinstance(data.get("telegram_api_hash"), str)
            else None,
            telegram_phone=data.get("telegram_phone")
            if isinstance(data.get("telegram_phone"), str)
            else None,
            secrets_passphrase=passphrase,
            section=section,
        )
        cred_root, cred_section = _wizard_credentials_context()
        status_body = await credentials_status(
            cred_root,
            section=cred_section,
            config_doc=_wizard_config_doc_for_credentials(),
        )
        return JSONResponse({"ok": True, "written": written, **status_body})

    @app.post("/api/shutdown", response_class=JSONResponse)
    async def api_shutdown(_: None = Depends(_require_token_union)) -> JSONResponse:
        """Schedule a graceful uvicorn shutdown after the response flushes.
        The wizard hits this when the operator clicks **Finish** on the handoff
        step — sending SIGINT to the current process lets uvicorn run its
        normal shutdown hooks (`specs/22-onboarding.md` §4.x).
        """
        import asyncio

        loop = asyncio.get_running_loop()
        loop.call_later(0.3, lambda: os.kill(os.getpid(), signal.SIGINT))
        return JSONResponse({"ok": True, "message": "shutdown scheduled"})

    @app.post("/api/run-doctor", response_class=JSONResponse)
    async def api_run_doctor(_: None = Depends(_require_token_union)) -> JSONResponse:
        """Run ``sevn doctor --json`` for the bound workspace."""
        import asyncio

        from sevn.config.loader import load_workspace
        from sevn.security.llmignore import ensure_llmignore_layout

        sj = _resolve_sevn_json()
        if sj.is_file():
            cfg, layout = load_workspace(sevn_json=sj)
            layout.logs_dir.mkdir(parents=True, exist_ok=True)
            ensure_llmignore_layout(layout.content_root, cfg)
        proc = await asyncio.create_subprocess_exec(
            "sevn",
            "doctor",
            "--json",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_b, stderr_b = await proc.communicate()
        out = (stdout_b or b"").decode("utf-8", errors="replace")
        err = (stderr_b or b"").decode("utf-8", errors="replace")
        return JSONResponse(
            {
                "ok": proc.returncode == 0,
                "exit_code": proc.returncode,
                "stdout": _redact_detail(out[:8000]),
                "stderr": _redact_detail(err[:4000]),
            }
        )

    @app.post("/api/run-proxy", response_class=JSONResponse)
    async def api_run_proxy(_: None = Depends(_require_token_union)) -> JSONResponse:
        """Start egress proxy detached with logs under ``<workspace>/logs/proxy.log``."""
        import asyncio

        from sevn.onboarding.proxy_spawn import spawn_proxy_background

        sj = _resolve_sevn_json()
        if not sj.is_file():
            return JSONResponse(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                content={"ok": False, "detail": "promote sevn.json before starting the proxy"},
            )
        try:
            body = await asyncio.to_thread(spawn_proxy_background, sevn_json_path=sj)
        except (OSError, RuntimeError) as exc:
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={"ok": False, "detail": str(exc)},
            )
        return JSONResponse(body)

    @app.post("/api/run-gateway", response_class=JSONResponse)
    async def api_run_gateway(_: None = Depends(_require_token_union)) -> JSONResponse:
        """Start proxy then gateway (handoff order per ``specs/22-onboarding.md`` §4.9)."""
        import asyncio

        from sevn.onboarding.service_restart import restart_services_after_promote

        sj = _resolve_sevn_json()
        if not sj.is_file():
            return JSONResponse(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                content={"ok": False, "detail": "promote sevn.json before starting services"},
            )
        try:
            body = await asyncio.to_thread(restart_services_after_promote, sevn_json_path=sj)
        except (OSError, RuntimeError) as exc:
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={"ok": False, "detail": str(exc)},
            )
        return JSONResponse(body)

    @app.post("/api/quick-boot", response_class=JSONResponse)
    async def api_quick_boot(
        request: Request,
        _: None = Depends(_require_token_union),
    ) -> JSONResponse:
        """Apply a preset profile and promote without the full wizard."""
        data = await request.json()
        if not isinstance(data, dict):
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"ok": False, "detail": "body must be a JSON object"},
            )
        profile_id = data.get("profile_id")
        if not isinstance(profile_id, str) or not profile_id.strip():
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"ok": False, "detail": "profile_id is required"},
            )
        sj = _resolve_sevn_json()
        sj.parent.mkdir(parents=True, exist_ok=True)
        try:
            cred_root, cred_section = _wizard_credentials_context()
            cred = await credentials_status(
                cred_root,
                section=cred_section,
                config_doc=_wizard_config_doc_for_credentials(),
            )
            if not cred.get("ready_for_handoff"):
                return JSONResponse(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    content={
                        "ok": False,
                        "detail": "store required credentials before quick boot",
                    },
                )
            merged = _merge_wizard_payload(
                {"profile_id": profile_id.strip()}, profile_id=profile_id
            )
            normalize_secrets_backend_section(merged)
            validate_workspace_document(merged)
            apply_web_ui_url_for_dashboard(merged)
            write_draft(sj, merged)
            promote_draft(sj, backup_previous=sj.is_file())
            seeded = seed_narrative_templates(sj, merged)
            from sevn.config.workspace_config import parse_workspace_config

            cfg = parse_workspace_config(merged)
            content_root = WorkspaceLayout.from_config(sj, cfg).content_root
            seeded_skill_ids = list_deployed_core_skill_ids(content_root)
            missing_core_skills = verify_core_skills_deployed(content_root)
        except (ValidationError, UnsupportedSchemaVersionError, ValueError, OSError) as exc:
            return _validation_error_response(exc)
        return JSONResponse(
            {
                "ok": True,
                "message": f"Quick boot applied profile {profile_id!r}",
                "sevn_json": str(sj),
                "seeded_files": [str(p) for p in seeded],
                "seeded_skills_count": len(seeded_skill_ids),
                "seeded_skill_ids": seeded_skill_ids,
                "missing_core_skills": missing_core_skills,
            }
        )

    async def _github_token_for_wizard(*, workspace_only: bool = True) -> str | None:
        content_root, section = _wizard_credentials_context()
        return await get_wizard_credential(
            content_root,
            GITHUB_TOKEN_LOGICAL_KEY,
            section=section,
            workspace_only=workspace_only,
        )

    @app.get("/api/github/status", response_class=JSONResponse)
    async def api_github_status(_: None = Depends(_require_token_union)) -> dict[str, Any]:
        """Report workspace GitHub auth status without leaking the token."""
        token = await _github_token_for_wizard(workspace_only=True)
        body: dict[str, Any] = {
            "connected": bool(token),
            "oauth_configured": oauth_configured(),
        }
        if not token:
            return body
        try:
            user = await fetch_github_user(token)
        except Exception as exc:
            body["connected"] = False
            body["detail"] = _redact_detail(str(exc))
            return body
        login = user.get("login")
        if isinstance(login, str) and login.strip():
            body["login"] = login.strip()
        return body

    @app.get("/api/github/host-status", response_class=JSONResponse)
    async def api_github_host_status(_: None = Depends(_require_token_union)) -> dict[str, Any]:
        """Report whether a host-level GitHub token exists (env, Keychain, or gh CLI)."""
        workspace_token = await _github_token_for_wizard(workspace_only=True)
        if workspace_token:
            return {"available": False, "login": None, "source": None}
        token, source = await probe_host_github_token()
        if not token:
            return {"available": False, "login": None, "source": None}
        try:
            user = await fetch_github_user(token)
        except Exception:
            return {"available": False, "login": None, "source": None}
        login = user.get("login")
        login_str = login.strip() if isinstance(login, str) and login.strip() else None
        return {"available": True, "login": login_str, "source": source}

    @app.post("/api/github/use-host", response_class=JSONResponse)
    async def api_github_use_host(_: None = Depends(_require_token_union)) -> JSONResponse:
        """Copy a host-level GitHub token into this workspace's encrypted secrets."""
        if await _github_token_for_wizard(workspace_only=True):
            return JSONResponse(
                status_code=status.HTTP_409_CONFLICT,
                content={"ok": False, "detail": "workspace GitHub token already configured"},
            )
        token, source = await probe_host_github_token()
        if not token:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"ok": False, "detail": "no host GitHub token found"},
            )
        try:
            await fetch_github_user(token)
        except Exception as exc:
            return JSONResponse(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                content={"ok": False, "detail": _redact_detail(str(exc))},
            )
        cred_root, cred_section = _wizard_credentials_context()
        await store_wizard_credentials(
            cred_root,
            github_token=token,
            section=cred_section,
        )
        login: str | None = None
        try:
            user = await fetch_github_user(token)
            raw_login = user.get("login")
            if isinstance(raw_login, str) and raw_login.strip():
                login = raw_login.strip()
        except Exception:
            login = None
        return JSONResponse({"ok": True, "login": login, "source": source})

    @app.post("/api/github/disconnect", response_class=JSONResponse)
    async def api_github_disconnect(_: None = Depends(_require_token_union)) -> JSONResponse:
        """Remove the workspace GitHub token so the operator can connect another account."""
        cred_root, cred_section = _wizard_credentials_context()
        removed = await delete_wizard_credential(
            cred_root,
            GITHUB_TOKEN_LOGICAL_KEY,
            section=cred_section,
        )
        return JSONResponse({"ok": True, "removed": removed})

    @app.post("/api/github/oauth/credentials", response_class=JSONResponse)
    async def api_github_oauth_credentials(
        request: Request,
        _: None = Depends(_require_token_union),
    ) -> JSONResponse:
        """Store GitHub OAuth app credentials for this wizard session (memory only)."""
        data = await request.json()
        if not isinstance(data, dict):
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"ok": False, "detail": "body must be a JSON object"},
            )
        client_id = data.get("client_id")
        client_secret = data.get("client_secret")
        if not isinstance(client_id, str) or not client_id.strip():
            return JSONResponse(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                content={"ok": False, "detail": "client_id is required"},
            )
        if not isinstance(client_secret, str) or not client_secret.strip():
            return JSONResponse(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                content={"ok": False, "detail": "client_secret is required"},
            )
        set_wizard_oauth_credentials(client_id.strip(), client_secret.strip())
        return JSONResponse({"ok": True, "oauth_configured": oauth_configured()})

    @app.get("/api/github/oauth/start", response_class=JSONResponse)
    async def api_github_oauth_start(_: None = Depends(_require_token_union)) -> JSONResponse:
        """Return the GitHub OAuth authorize URL (D6 primary auth)."""
        if not oauth_configured():
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={
                    "ok": False,
                    "detail": (
                        "GitHub OAuth is not configured — enter OAuth app credentials below, "
                        "or use a personal access token."
                    ),
                    "oauth_configured": False,
                },
            )
        client_id, _secret = oauth_client_credentials()
        if client_id is None:
            return JSONResponse(
                {
                    "ok": False,
                    "detail": "GitHub OAuth client id missing after configuration check.",
                    "oauth_configured": False,
                },
                status_code=503,
            )
        state = mint_oauth_state()
        redirect_uri = callback_redirect_uri(port=onboard_port)
        return JSONResponse(
            {
                "ok": True,
                "authorize_url": build_authorize_url(
                    state=state,
                    client_id=client_id,
                    redirect_uri=redirect_uri,
                ),
                "oauth_configured": True,
            }
        )

    @app.get("/api/github/oauth/callback")
    async def api_github_oauth_callback(
        request: Request,
        code: Annotated[str | None, Query()] = None,
        state: Annotated[str | None, Query()] = None,
        session_cookie: Annotated[str | None, Cookie(alias=ONBOARD_SESSION_COOKIE)] = None,
    ) -> RedirectResponse:
        """Exchange OAuth code, store token, redirect back to the My Sevn.bot step."""
        token_for_redirect = session_cookie if session_cookie == onboard_token else onboard_token
        base = f"http://127.0.0.1:{onboard_port}/?onboard_token={token_for_redirect}"
        if not code or not state or not validate_oauth_state(state):
            return RedirectResponse(url=f"{base}&github_error=invalid_state", status_code=302)
        if not oauth_configured():
            return RedirectResponse(
                url=f"{base}&github_error=oauth_not_configured", status_code=302
            )
        client_id, client_secret = oauth_client_credentials()
        if not client_id or not client_secret:
            return RedirectResponse(
                url=f"{base}&github_error=oauth_not_configured", status_code=302
            )
        redirect_uri = callback_redirect_uri(port=onboard_port)
        try:
            access = await exchange_code_for_token(
                code=code,
                client_id=client_id,
                client_secret=client_secret,
                redirect_uri=redirect_uri,
            )
            await fetch_github_user(access)
            cred_root, cred_section = _wizard_credentials_context()
            await store_wizard_credentials(
                cred_root,
                github_token=access,
                section=cred_section,
            )
        except Exception as exc:
            logger.warning("github_oauth_callback_failed err={}", _redact_detail(str(exc)))
            return RedirectResponse(
                url=f"{base}&github_error=exchange_failed",
                status_code=302,
            )
        return RedirectResponse(url=f"{base}&github_connected=1", status_code=302)

    @app.get("/api/openai/oauth/start", response_class=JSONResponse)
    async def api_openai_oauth_start(_: None = Depends(_require_token_union)) -> JSONResponse:
        """Start ChatGPT Codex OAuth for the wizard (W4.3, D6)."""
        cred_root, cred_section = _wizard_credentials_context()
        start = start_wizard_codex_oauth(cred_root, section=cred_section)
        return JSONResponse(
            {
                "ok": True,
                "authorize_url": start.authorize_url,
                "state": start.state,
            }
        )

    @app.get("/api/openai/oauth/poll", response_class=JSONResponse)
    async def api_openai_oauth_poll(
        state: Annotated[str, Query()],
        _: None = Depends(_require_token_union),
    ) -> JSONResponse:
        """Poll ChatGPT Codex OAuth completion for wizard ``state``."""
        body = poll_wizard_codex_oauth(state)
        return JSONResponse({"ok": body.get("status") == "success", **body})

    @app.get("/api/openai/oauth/status", response_class=JSONResponse)
    async def api_openai_oauth_status(_: None = Depends(_require_token_union)) -> JSONResponse:
        """Return whether ``oauth.openai`` is stored for this wizard workspace."""
        from sevn.security.oauth.storage import load_codex_oauth_credential
        from sevn.security.secrets.factory import secrets_chain_from_workspace

        cred_root, cred_section = _wizard_credentials_context()
        chain = secrets_chain_from_workspace(cred_root, cred_section)
        try:
            credential = await load_codex_oauth_credential(chain)
        except ValueError:
            credential = None
        if credential is None:
            return JSONResponse({"ok": True, "connected": False})
        return JSONResponse(
            {
                "ok": True,
                "connected": True,
                "account_id": credential.account_id,
                "expires": credential.expires,
            }
        )

    @app.post("/api/github/token", response_class=JSONResponse)
    async def api_github_token(
        request: Request,
        _: None = Depends(_require_token_union),
    ) -> JSONResponse:
        """Store a GitHub PAT fallback (never written to draft JSON)."""
        data = await request.json()
        if not isinstance(data, dict):
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"ok": False, "detail": "body must be a JSON object"},
            )
        raw = data.get("token")
        if not isinstance(raw, str) or not raw.strip():
            return JSONResponse(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                content={"ok": False, "detail": "token is required"},
            )
        token = raw.strip()
        try:
            await fetch_github_user(token)
        except Exception as exc:
            return JSONResponse(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                content={"ok": False, "detail": _redact_detail(str(exc))},
            )
        cred_root, cred_section = _wizard_credentials_context()
        await store_wizard_credentials(
            cred_root,
            github_token=token,
            section=cred_section,
        )
        status_body = await credentials_status(
            cred_root,
            section=cred_section,
            config_doc=_wizard_config_doc_for_credentials(),
        )
        login: str | None = None
        try:
            user = await fetch_github_user(token)
            raw_login = user.get("login")
            if isinstance(raw_login, str) and raw_login.strip():
                login = raw_login.strip()
        except Exception:
            login = None
        return JSONResponse({"ok": True, "login": login, **status_body})

    @app.get("/api/workspace-backup/default-name", response_class=JSONResponse)
    async def api_workspace_backup_default_name(
        _: None = Depends(_require_token_union),
    ) -> JSONResponse:
        """Return the default ``{login}.mysevnbackup`` slug when GitHub is connected."""
        token = await _github_token_for_wizard()
        if not token:
            return JSONResponse(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                content={"ok": False, "detail": "connect GitHub before creating a backup repo"},
            )
        try:
            name = await resolve_backup_default_name(token)
        except Exception as exc:
            return JSONResponse(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                content={"ok": False, "detail": _redact_detail(str(exc))},
            )
        return JSONResponse({"ok": True, "name": name})

    @app.post("/api/workspace-backup/create", response_class=JSONResponse)
    async def api_workspace_backup_create(
        request: Request,
        _: None = Depends(_require_token_union),
    ) -> JSONResponse:
        """Create a private workspace backup repository on GitHub (D7)."""
        data = await request.json()
        if not isinstance(data, dict):
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"ok": False, "detail": "body must be a JSON object"},
            )
        token = await _github_token_for_wizard()
        if not token:
            return JSONResponse(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                content={"ok": False, "detail": "connect GitHub before creating a backup repo"},
            )
        raw_name = data.get("name")
        if not isinstance(raw_name, str) or not raw_name.strip():
            try:
                name = await resolve_backup_default_name(token)
            except Exception as exc:
                return JSONResponse(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    content={"ok": False, "detail": _redact_detail(str(exc))},
                )
        else:
            try:
                name = sanitize_repo_name(raw_name)
            except ValueError as exc:
                return JSONResponse(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    content={"ok": False, "detail": str(exc)},
                )
        private = data.get("private", True)
        is_private = (
            bool(private)
            if not isinstance(private, str)
            else private.lower()
            in (
                "1",
                "true",
                "yes",
                "on",
            )
        )
        try:
            repo_url = await create_workspace_backup_repo(
                token,
                name,
                private=is_private,
            )
        except Exception as exc:
            return JSONResponse(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                content={"ok": False, "detail": _redact_detail(str(exc))},
            )
        return JSONResponse({"ok": True, "repo_url": repo_url, "name": name})

    return app
