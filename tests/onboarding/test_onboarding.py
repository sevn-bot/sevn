"""Tests for onboarding package (`specs/22-onboarding.md` §9)."""

from __future__ import annotations

import asyncio
import json
import os
from importlib import resources
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient

from sevn.config.defaults import DEFAULT_TRACING_SINKS
from sevn.config.errors import UnsupportedSchemaVersionError
from sevn.onboarding import web_app as web_app_module
from sevn.onboarding.draft_store import draft_path, write_draft
from sevn.onboarding.live_validate import (
    probe_llm_reachability,
    probe_mcp_reachability,
    probe_secrets_backend,
    run_live_validation,
)
from sevn.onboarding.merge import merge_layers
from sevn.onboarding.migrate import (
    V1_SQLITE_IMPORT_TABLE_KEYS,
    describe_schema_upgrade,
    import_foreign_workspace,
    upgrade_schema_inplace,
)
from sevn.onboarding.profiles import (
    load_profile_catalog,
    load_profile_fragment,
    profile_default_sandbox_mode,
)
from sevn.onboarding.promote import promote_draft
from sevn.onboarding.seed import seed_narrative_templates
from sevn.onboarding.tui import OnboardApp
from sevn.onboarding.validate import validate_workspace_document
from sevn.onboarding.web_app import (
    DEFAULT_ENCRYPTED_FILE_REL_PATH,
    _config_from_fields,
    _merge_wizard_payload,
    apply_model_slot_policy,
    create_onboarding_app,
    normalize_secrets_backend_section,
)
from sevn.security.secrets.chain import SecretsChain


def test_merge_layers_nested_and_list_replace() -> None:
    base = {
        "schema_version": 1,
        "a": {"b": 1},
        "tracing": {"sinks": [1]},
        "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
    }
    layer = {"a": {"c": 2}, "tracing": {"sinks": [2, 3]}}
    got = merge_layers(base, layer)
    assert got["a"] == {"b": 1, "c": 2}
    assert got["tracing"]["sinks"] == [2, 3]


def test_config_from_fields_unified_model_flag() -> None:
    doc = _config_from_fields(
        {
            "providers.use_main_model_for_all": True,
            "providers.tier_default.triager": "minimax/MiniMax-M2.7",
            "providers.tier_default.B": "should-strip",
            "lcm.summary_model": "should-strip",
        },
    )
    merged = merge_layers(
        {"schema_version": 1, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}, doc
    )
    apply_model_slot_policy(merged)
    assert merged["providers"]["use_main_model_for_all"] is True
    assert merged["providers"]["tier_default"] == {"triager": "minimax/MiniMax-M2.7"}
    assert "summary_model" not in merged.get("lcm", {})


def test_apply_model_slot_policy_preserves_slot_on_partial_edit() -> None:
    merged = _merge_wizard_payload(
        {
            "fields": {
                "providers.use_main_model_for_all": False,
                "providers.tier_default.triager": "main-m",
                "providers.tier_default.B": "only-b-changed",
            },
        },
        profile_id=None,
    )
    assert merged["providers"]["use_main_model_for_all"] is False
    assert merged["providers"]["tier_default"]["B"] == "only-b-changed"
    assert merged["providers"]["tier_default"]["C"] == "main-m"


def test_profile_default_sandbox_mode_by_host() -> None:
    assert profile_default_sandbox_mode("good_value_osx") == "pyodide_deno"
    assert profile_default_sandbox_mode("good_value_docker") == "docker"
    assert profile_default_sandbox_mode("full_free") is None


def test_merge_wizard_payload_good_value_applies_sandbox_default() -> None:
    merged = _merge_wizard_payload({"fields": {}}, profile_id="good_value_osx")
    mode = merged.get("sandbox", {}).get("mode")
    assert mode in (None, "pyodide_deno", "docker")


def test_merge_wizard_payload_good_value_unified() -> None:
    merged = _merge_wizard_payload(
        {
            "fields": {
                "providers.tier_default.triager": "minimax/MiniMax-M2.7",
                "wizard.provider_api_key.openai": "sk-test",
            },
        },
        profile_id="good_value_osx",
    )
    assert merged["providers"]["use_main_model_for_all"] is True
    assert merged["providers"]["tier_default"]["triager"] == "minimax/MiniMax-M2.7"


def test_merge_wizard_payload_explicit_triager_wins_over_profile() -> None:
    """An operator-typed triager overrides the preset default (bug fix).

    Previously the profile fragment was force-applied after the field merge, so
    editing the model away from a preset (e.g. to ``minimax/MiniMax-M3``) silently
    saved the preset's model instead. The explicit field value must win.
    """
    merged = _merge_wizard_payload(
        {
            "fields": {
                "providers.tier_default.triager": "minimax/MiniMax-M3",
            },
        },
        profile_id="good_value_osx",
    )
    assert merged["providers"]["tier_default"]["triager"] == "minimax/MiniMax-M3"


def test_merge_wizard_payload_blank_triager_backfills_profile() -> None:
    """When the operator leaves the triager blank, the preset model still back-fills."""
    merged = _merge_wizard_payload(
        {
            "fields": {
                "providers.tier_default.triager": "",
            },
        },
        profile_id="good_value_osx",
    )
    assert merged["providers"]["tier_default"]["triager"] == "minimax/MiniMax-M2.7"


def test_load_profile_catalog_has_minimum_profiles() -> None:
    rows = load_profile_catalog()
    ids = {r["profile_id"] for r in rows}
    for required in (
        "full_free",
        "best_agent",
        "fastest",
        "openai_family",
        "ollama_local",
        "docker_sandbox",
        "good_value_osx",
        "good_value_docker",
    ):
        assert required in ids
    by_id = {r["profile_id"]: r for r in rows}
    assert by_id["full_free"]["model"] == "gpt-4o-mini"
    assert by_id["full_free"]["host"] == "cloud"
    assert by_id["ollama_local"]["host"] == "osx"
    assert by_id["docker_sandbox"]["host"] == "docker"


def test_default_base_workspace_and_telegram() -> None:
    assert web_app_module._DEFAULT_BASE["workspace_root"] == "."
    assert web_app_module._DEFAULT_BASE["channels"]["webchat"]["enabled"] is True
    assert web_app_module._DEFAULT_BASE["channels"]["telegram"]["enabled"] is True
    assert web_app_module._DEFAULT_BASE["channels"]["telegram"]["dm_policy"] == "pairing"
    assert web_app_module._DEFAULT_BASE["agent"]["codemode"]["max_retries"] == 3


def test_merge_wizard_sets_telegram_owner_and_pairing() -> None:
    doc = web_app_module._merge_wizard_payload(
        {"fields": {"wizard.telegram_owner_user_id": "123456789"}},
        profile_id=None,
    )
    tg = doc["channels"]["telegram"]
    assert tg["dm_policy"] == "pairing"
    assert tg["allowed_users"] == [123456789]


@pytest.mark.asyncio
async def test_validate_telegram_owner_user_id() -> None:
    ok, _ = await web_app_module._validate_field("wizard.telegram_owner_user_id", "42", context={})
    assert ok is True
    bad, msg = await web_app_module._validate_field("wizard.telegram_owner_user_id", "", context={})
    assert bad is False
    assert "required" in msg.lower()


def test_web_api_field_help(tmp_path: Path) -> None:
    client = _wizard_client(tmp_path)
    r = client.get("/api/field-help", params={"onboard_token": "tok"})
    assert r.status_code == 200
    fields = r.json()["fields"]
    assert "workspace_root" in fields
    assert fields["workspace_root"]["long_description"]


def test_wizard_html_has_no_spec_refs() -> None:
    html = (resources.files("sevn.onboarding") / "web_wizard" / "index.html").read_text(
        encoding="utf-8"
    )
    assert "specs/" not in html


def test_load_profile_fragment_unknown_raises() -> None:
    with pytest.raises(FileNotFoundError):
        load_profile_fragment("no_such_profile")


def test_validate_workspace_document_bad_schema() -> None:
    with pytest.raises(UnsupportedSchemaVersionError):
        validate_workspace_document(
            {"schema_version": 999, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}
        )


def test_validate_rejects_minimax_chat_completions_override() -> None:
    doc = {
        "schema_version": 1,
        "providers": {
            "models": {
                "minimax/MiniMax-M2.7": {"transport": "chat_completions"},
            },
        },
        "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
    }
    with pytest.raises(ValueError, match="minimax/"):
        validate_workspace_document(doc)


def test_validate_accepts_minimax_with_anthropic_transport() -> None:
    doc = {
        "schema_version": 1,
        "providers": {
            "models": {
                "minimax/MiniMax-M2.7": {"transport": "anthropic"},
            },
        },
        "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
    }
    validate_workspace_document(doc)


def test_promote_atomic_round_trip(tmp_path: Path) -> None:
    sevn_json = tmp_path / "sevn.json"
    draft = {
        "schema_version": 1,
        "workspace_root": ".",
        "gateway": {
            "host": "127.0.0.1",
            "port": 3001,
            "queue_mode": "cancel",
            "token": "${SECRET:keychain:sevn.gateway.token}",
        },
    }
    write_draft(sevn_json, draft)
    promote_draft(sevn_json, backup_previous=False)
    promoted = json.loads(sevn_json.read_text(encoding="utf-8"))
    assert promoted["schema_version"] == 1
    assert not draft_path(sevn_json).is_file()


def test_promote_draft_double_promote_tracing_sinks_idempotent(tmp_path: Path) -> None:
    sevn_json = tmp_path / "sevn.json"
    draft = {
        "schema_version": 1,
        "workspace_root": ".",
        "gateway": {
            "host": "127.0.0.1",
            "port": 3001,
            "queue_mode": "cancel",
            "token": "${SECRET:keychain:sevn.gateway.token}",
        },
    }
    write_draft(sevn_json, draft)
    promote_draft(sevn_json, backup_previous=False)
    after_first = json.loads(sevn_json.read_text(encoding="utf-8"))
    sinks_first = after_first.get("tracing", {}).get("sinks")
    expected = [dict(entry) for entry in DEFAULT_TRACING_SINKS]
    assert sinks_first == expected
    sink_count = len(sinks_first)

    write_draft(sevn_json, after_first)
    promote_draft(sevn_json, backup_previous=False)
    after_second = json.loads(sevn_json.read_text(encoding="utf-8"))
    sinks_second = after_second.get("tracing", {}).get("sinks")
    assert len(sinks_second) == sink_count
    assert sinks_second == sinks_first


def test_promote_enospc_leaves_sevn_json_intact(tmp_path: Path) -> None:
    sevn_json = tmp_path / "sevn.json"
    existing = {
        "schema_version": 1,
        "workspace_root": ".",
        "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
    }
    sevn_json.write_text(json.dumps(existing), encoding="utf-8")
    draft = dict(existing)
    draft["timezone"] = "UTC"
    write_draft(sevn_json, draft)

    real_os_replace = os.replace

    def boom(
        src: str | bytes | Path, dst: str | bytes | Path, *args: object, **kwargs: object
    ) -> None:
        _ = args, kwargs
        if str(dst).endswith("sevn.json"):
            raise OSError(28, "nospc")
        real_os_replace(src, dst)

    with patch("sevn.onboarding.promote.os.replace", boom), pytest.raises(OSError, match="nospc"):
        promote_draft(sevn_json, backup_previous=False)

    assert json.loads(sevn_json.read_text(encoding="utf-8")) == existing
    assert draft_path(sevn_json).is_file()


def test_seed_skips_existing_files(tmp_path: Path) -> None:
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "workspace_root": ".",
                "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
            }
        ),
        encoding="utf-8",
    )
    root = tmp_path
    (root / "MEMORY.md").write_text("keep", encoding="utf-8")
    written = seed_narrative_templates(
        sevn_json,
        {
            "schema_version": 1,
            "workspace_root": ".",
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        },
    )
    assert all(p.name != "MEMORY.md" for p in written)
    assert (root / "MEMORY.md").read_text(encoding="utf-8") == "keep"


def test_web_app_bad_token_401() -> None:
    app = create_onboarding_app("good")
    client = TestClient(app)
    r = client.get("/api/meta")
    assert r.status_code == 401


def test_web_app_good_token_200() -> None:
    app = create_onboarding_app("good")
    client = TestClient(app)
    r = client.get("/api/meta", params={"onboard_token": "good"})
    assert r.status_code == 200
    assert "profiles" in r.json()


def test_web_meta_fresh_install_when_no_sevn_json(tmp_path: Path) -> None:
    sevn_json = tmp_path / "sevn.json"
    sevn_json.parent.mkdir(parents=True, exist_ok=True)
    app = create_onboarding_app("tok", sevn_json_path=sevn_json)
    client = TestClient(app)
    r = client.get("/api/meta", params={"onboard_token": "tok"})
    assert r.status_code == 200
    assert r.json()["fresh_install"] is True


def test_web_meta_not_fresh_when_sevn_json_exists(tmp_path: Path) -> None:
    sevn_json = tmp_path / "sevn.json"
    sevn_json.parent.mkdir(parents=True, exist_ok=True)
    sevn_json.write_text(
        '{"schema_version": 1, "workspace_root": ".", "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
        encoding="utf-8",
    )
    app = create_onboarding_app("tok", sevn_json_path=sevn_json)
    client = TestClient(app)
    r = client.get("/api/meta", params={"onboard_token": "tok"})
    assert r.json()["fresh_install"] is False


def test_web_existing_config_omits_secrets_on_fresh_install(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sevn_json = tmp_path / "sevn.json"
    sevn_json.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("SEVN_TELEGRAM_BOT_TOKEN", "from-env-should-not-prefill")
    monkeypatch.setenv("SEVN_ONBOARD_REUSE", "0")
    app = create_onboarding_app("tok", sevn_json_path=sevn_json)
    client = TestClient(app)
    r = client.get("/api/existing-config", params={"onboard_token": "tok"})
    assert r.status_code == 200
    body = r.json()
    assert body["exists"] is False
    assert body["should_prefill_secrets"] is False
    assert body["wizard_secrets"] == {}


def test_web_app_expired_token_403(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(web_app_module, "ONBOARDING_TOKEN_TTL_SECONDS", 0)
    app = create_onboarding_app("good")
    client = TestClient(app)
    r = client.get("/api/meta", params={"onboard_token": "good"})
    assert r.status_code == 403


def test_web_app_sets_session_cookie_and_allows_refresh() -> None:
    app = create_onboarding_app("good")
    client = TestClient(app)
    first = client.get("/", params={"onboard_token": "good"})
    assert first.status_code == 200
    assert web_app_module.ONBOARD_SESSION_COOKIE in client.cookies
    refresh = client.get("/")
    assert refresh.status_code == 200


def test_packaged_profiles_readable() -> None:
    ref = resources.files("sevn.data.onboarding_profiles") / "onboarding_profiles.json"
    assert ref.is_file()


def test_packaged_web_wizard_readable() -> None:
    root = resources.files("sevn.onboarding") / "web_wizard"
    assert (root / "index.html").is_file()
    assert (root / "style.css").is_file()
    assert (root / "app.js").is_file()


def _wizard_client(tmp_path: Path) -> TestClient:
    sevn_json = tmp_path / "sevn.json"
    sevn_json.parent.mkdir(parents=True, exist_ok=True)
    app = create_onboarding_app("tok", sevn_json_path=sevn_json)
    return TestClient(app)


def _valid_wizard_payload() -> dict[str, object]:
    return {
        "profile_id": "full_free",
        "fields": {
            "schema_version": 1,
            "workspace_root": ".",
            "agent.display_name": "TestBot",
            "providers.tier_default.triager": "gpt-4o-mini",
            "gateway.host": "127.0.0.1",
            "gateway.port": 3001,
            "gateway.queue_mode": "cancel",
            "gateway.token": "${SECRET:keychain:sevn.gateway.token}",
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        },
    }


def _store_test_credentials(client: TestClient) -> None:
    # A passphrase seals the encrypted-file store. The host macOS Keychain backend is
    # disabled in tests (no access prompts), so the encrypted-file backend is the write
    # target and needs an unlock credential — previously the keychain accepted writes
    # with none.
    r = client.post(
        "/api/credentials",
        params={"onboard_token": "tok"},
        json={
            "bot_token": "123456789:AAFakeTokenForTestsOnly",
            "provider_api_keys": {"openai": "sk-test-key"},
            "gateway_token": "c" * 64,
            "secrets_passphrase": "wizard-test-passphrase",
        },
    )
    assert r.status_code == 200
    assert r.json()["ready_for_handoff"] is True


def _store_test_credentials_with_passphrase(client: TestClient) -> None:
    r = client.post(
        "/api/credentials",
        params={"onboard_token": "tok"},
        json={
            "bot_token": "123456789:AAFakeTokenForTestsOnly",
            "provider_api_keys": {"openai": "sk-test-key"},
            "secrets_passphrase": "wizard-test-passphrase",
            "gateway_token": "c" * 64,
        },
    )
    assert r.status_code == 200
    assert r.json()["ready_for_handoff"] is True


def test_web_credentials_land_in_encrypted_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _noop_mirror(**kwargs: object) -> None:
        _ = kwargs

    monkeypatch.setattr(
        "sevn.onboarding.wizard_credentials._mirror_unlock_secret_to_keychain",
        _noop_mirror,
    )
    client = _wizard_client(tmp_path)
    _store_test_credentials_with_passphrase(client)
    store = tmp_path / ".sevn" / "secrets" / "store.enc"
    assert store.is_file()


def test_web_post_validate_field_ok(tmp_path: Path) -> None:
    client = _wizard_client(tmp_path)
    r = client.post(
        "/api/validate-field",
        params={"onboard_token": "tok"},
        json={"field_id": "gateway.port", "value": 3001},
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_web_post_validate_field_invalid(tmp_path: Path) -> None:
    client = _wizard_client(tmp_path)
    r = client.post(
        "/api/validate-field",
        params={"onboard_token": "tok"},
        json={"field_id": "gateway.port", "value": 99999},
    )
    assert r.status_code == 422
    assert r.json()["ok"] is False


def test_web_post_validate_all_ok(tmp_path: Path) -> None:
    client = _wizard_client(tmp_path)
    _store_test_credentials(client)
    r = client.post(
        "/api/validate-all",
        params={"onboard_token": "tok"},
        json=_valid_wizard_payload(),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["schema_ok"] is True
    assert isinstance(body.get("live_validation"), list)
    telegram_rows = [c for c in body["live_validation"] if c["check_id"] == "telegram_get_me"]
    assert telegram_rows
    assert "skipped" not in telegram_rows[0]["detail"].lower()


def test_web_post_validate_all_invalid(tmp_path: Path) -> None:
    client = _wizard_client(tmp_path)
    bad = _valid_wizard_payload()
    bad["fields"] = {
        "schema_version": 999,
        "workspace_root": ".",
        "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
    }
    r = client.post(
        "/api/validate-all",
        params={"onboard_token": "tok"},
        json=bad,
    )
    assert r.status_code == 422
    assert r.json()["ok"] is False


def test_web_api_meta_steps_no_seed() -> None:
    app = create_onboarding_app("good")
    client = TestClient(app)
    r = client.get("/api/meta", params={"onboard_token": "good"})
    ids = [s["id"] for s in r.json()["steps"]]
    assert "seed" not in ids
    assert "tunnel" in ids
    assert "personality" in ids
    assert len(ids) == 13


def test_web_post_save_ok(tmp_path: Path) -> None:
    client = _wizard_client(tmp_path)
    sevn_json = tmp_path / "sevn.json"
    _store_test_credentials(client)
    payload = _valid_wizard_payload()
    fields = dict(payload["fields"])  # type: ignore[arg-type]
    fields["secrets_backend.type"] = "encrypted_file"
    payload["fields"] = fields
    r = client.post(
        "/api/save",
        params={"onboard_token": "tok"},
        json=payload,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert sevn_json.is_file()
    seeded = body.get("seeded_files") or []
    assert any("IDENTITY.md" in str(p) for p in seeded)
    identity_path = tmp_path / "IDENTITY.md"
    assert identity_path.is_file()
    assert "TestBot" in identity_path.read_text(encoding="utf-8")
    promoted = json.loads(sevn_json.read_text(encoding="utf-8"))
    assert promoted["schema_version"] == 1
    sb = promoted["secrets_backend"]
    assert sb["encrypted_file"]["path"] == DEFAULT_ENCRYPTED_FILE_REL_PATH
    chain_paths = [
        entry["path"]
        for entry in sb["chain"]
        if isinstance(entry, dict) and entry.get("type") == "encrypted_file"
    ]
    assert chain_paths == [DEFAULT_ENCRYPTED_FILE_REL_PATH]
    assert (tmp_path / ".llmignore" / "blocked").is_dir()
    assert (tmp_path / "logs").is_dir()


def test_web_post_save_invalid(tmp_path: Path) -> None:
    client = _wizard_client(tmp_path)
    bad = _valid_wizard_payload()
    bad["fields"] = {
        "schema_version": 999,
        "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
    }
    r = client.post(
        "/api/save",
        params={"onboard_token": "tok"},
        json=bad,
    )
    assert r.status_code == 422
    assert not (tmp_path / "sevn.json").is_file()


def test_web_post_quick_boot_ok(tmp_path: Path) -> None:
    client = _wizard_client(tmp_path)
    _store_test_credentials(client)
    r = client.post(
        "/api/quick-boot",
        params={"onboard_token": "tok"},
        json={"profile_id": "full_free"},
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert (tmp_path / "sevn.json").is_file()


def test_import_foreign_workspace_detects_sevn(tmp_path: Path) -> None:
    (tmp_path / "sevn.json").write_text("{}", encoding="utf-8")
    plan = import_foreign_workspace(tmp_path, dry_run=True)
    assert plan.source_kind == "sevn"
    assert plan.sqlite_subset_keys == list(V1_SQLITE_IMPORT_TABLE_KEYS)


def test_import_foreign_workspace_unknown_has_no_sqlite_subset(tmp_path: Path) -> None:
    plan = import_foreign_workspace(tmp_path, dry_run=True)
    assert plan.source_kind == "unknown"
    assert plan.sqlite_subset_keys == []


def test_upgrade_schema_inplace_noop(tmp_path: Path) -> None:
    p = tmp_path / "sevn.json"
    p.write_text(
        json.dumps(
            {"schema_version": 2, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}
        ),
        encoding="utf-8",
    )
    summary = upgrade_schema_inplace(tmp_path, consent=True)
    assert summary["changed"] is False


def test_fixture_v1_workspace_upgradeable() -> None:
    root = (
        Path(__file__).resolve().parents[1] / "fixtures" / "onboarding" / "migrate" / "v1_workspace"
    )
    desc = describe_schema_upgrade(root)
    assert desc["changed"] is True
    assert desc["current"] == 1
    assert desc["target"] == 2


def test_fixture_v2_workspace_no_upgrade() -> None:
    root = (
        Path(__file__).resolve().parents[1] / "fixtures" / "onboarding" / "migrate" / "v2_workspace"
    )
    desc = describe_schema_upgrade(root)
    assert desc["changed"] is False
    assert desc["current"] == 2


def test_upgrade_schema_inplace_v1_to_v2_backup_and_validate(tmp_path: Path) -> None:
    draft = {
        "schema_version": 1,
        "workspace_root": ".",
        "gateway": {
            "host": "127.0.0.1",
            "port": 3001,
            "queue_mode": "cancel",
            "token": "${SECRET:keychain:sevn.gateway.token}",
        },
    }
    p = tmp_path / "sevn.json"
    p.write_text(json.dumps(draft), encoding="utf-8")
    desc = describe_schema_upgrade(tmp_path)
    assert desc["changed"] is True
    assert "schema_version" in desc["diff"]
    summary = upgrade_schema_inplace(tmp_path, consent=True)
    assert summary["changed"] is True
    assert summary["backup"] is not None
    assert Path(summary["backup"]).name.startswith("sevn.json.v1")
    upgraded = json.loads(p.read_text(encoding="utf-8"))
    assert upgraded["schema_version"] == 2
    validate_workspace_document(upgraded)


def test_promote_with_backup_renames_prior_sevn_json(tmp_path: Path) -> None:
    sevn_json = tmp_path / "sevn.json"
    prior = {
        "schema_version": 1,
        "workspace_root": ".",
        "gateway": {
            "host": "127.0.0.1",
            "port": 3001,
            "queue_mode": "cancel",
            "token": "${SECRET:keychain:sevn.gateway.token}",
        },
    }
    sevn_json.write_text(json.dumps(prior), encoding="utf-8")
    new_draft = dict(prior)
    new_draft["timezone"] = "UTC"
    write_draft(sevn_json, new_draft)
    promote_draft(sevn_json, backup_previous=True)
    backup = tmp_path / "sevn.json.v1"
    assert backup.is_file()
    assert json.loads(backup.read_text(encoding="utf-8")) == prior
    assert json.loads(sevn_json.read_text(encoding="utf-8"))["timezone"] == "UTC"


class _MemorySecretsBackend:
    def __init__(self, data: dict[str, str] | None = None) -> None:
        self._data = dict(data or {})

    async def get(self, key: str) -> str | None:
        return self._data.get(key)

    async def set(self, key: str, value: str) -> None:
        self._data[key] = value

    async def delete(self, key: str) -> None:
        self._data.pop(key, None)


@pytest.mark.anyio
async def test_probe_secrets_sentinel_hit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain = SecretsChain(
        [_MemorySecretsBackend({"_sevn_probe": "ok"})],
        backend_labels=["mem"],
    )
    monkeypatch.setattr(
        "sevn.onboarding.live_validate.resolve_backend",
        lambda *_a, **_k: chain,
    )
    check = await probe_secrets_backend(content_root=tmp_path, section=None)
    assert check.ok is True
    assert check.severity == "info"
    assert "read ok" in check.detail


@pytest.mark.anyio
async def test_probe_secrets_sentinel_miss(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain = SecretsChain([_MemorySecretsBackend()], backend_labels=["mem"])
    monkeypatch.setattr(
        "sevn.onboarding.live_validate.resolve_backend",
        lambda *_a, **_k: chain,
    )
    check = await probe_secrets_backend(content_root=tmp_path, section=None)
    assert check.ok is True
    assert check.severity == "warn"
    assert "not set" in check.detail


@pytest.mark.anyio
async def test_probe_secrets_backend_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(*_a: object, **_k: object) -> SecretsChain:
        msg = "chain build failed"
        raise RuntimeError(msg)

    monkeypatch.setattr("sevn.onboarding.live_validate.resolve_backend", _boom)
    check = await probe_secrets_backend(content_root=tmp_path, section=None)
    assert check.ok is False
    assert check.severity == "warn"
    assert "backend error" in check.detail


def test_normalize_secrets_backend_section_custom_path() -> None:
    custom = "custom/secrets/store.enc"
    doc = {
        "secrets_backend": {
            "chain": [{"type": "encrypted_file"}],
            "encrypted_file": {"path": custom},
        }
    }
    normalize_secrets_backend_section(doc)
    assert doc["secrets_backend"]["encrypted_file"]["path"] == custom
    assert doc["secrets_backend"]["chain"][0]["path"] == custom


@pytest.mark.anyio
async def test_run_live_validation_missing_required_creds_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _missing_creds(_content_root: Path, **_kwargs: object) -> dict[str, object]:
        _ = _content_root
        return {
            "present": {
                "SEVN_TELEGRAM_BOT_TOKEN": False,
                "SEVN_SECRET_OPENAI": False,
            },
            "ready_for_handoff": False,
        }

    monkeypatch.setattr(
        "sevn.onboarding.live_validate.credentials_status",
        _missing_creds,
    )
    report = await run_live_validation(
        workspace_root=tmp_path,
        merged_preview={
            "schema_version": 1,
            "workspace_root": ".",
            "gateway": {
                "host": "127.0.0.1",
                "port": 3001,
                "queue_mode": "cancel",
                "token": "${SECRET:keychain:sevn.gateway.token}",
            },
            "channels": {"telegram": {"enabled": True}},
            "providers": {"tier_default": {"triager": "openai/gpt-test"}},
        },
        profile_id="full_free",
    )
    assert report.has_error()
    by_id = {c.check_id: c for c in report.checks}
    assert by_id["telegram_get_me"].ok is False
    assert by_id["telegram_get_me"].severity == "error"
    assert "missing from secrets chain" in by_id["telegram_get_me"].detail
    assert by_id["llm_reachability"].ok is False
    assert by_id["llm_reachability"].severity == "error"
    assert "missing provider credentials" in by_id["llm_reachability"].detail


@pytest.mark.anyio
async def test_run_live_validation_stored_credentials_no_telegram_skip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sevn.onboarding.wizard_credentials import store_wizard_credentials

    await store_wizard_credentials(
        tmp_path,
        bot_token="123456789:AAFakeTokenForTestsOnly",
        provider_api_keys={"openai": "sk-test-key"},
        secrets_passphrase="wizard-test-passphrase",
    )

    async def _fake_get_me(self: object, url: str, **kwargs: object) -> object:
        _ = self, url, kwargs

        class _Resp:
            status_code = 200

            @staticmethod
            def json() -> dict[str, bool]:
                return {"ok": True}

        return _Resp()

    monkeypatch.setattr("sevn.onboarding.live_validate.httpx.AsyncClient.get", _fake_get_me)
    report = await run_live_validation(
        workspace_root=tmp_path,
        merged_preview={
            "schema_version": 1,
            "workspace_root": ".",
            "gateway": {
                "host": "127.0.0.1",
                "port": 3001,
                "queue_mode": "cancel",
                "token": "${SECRET:keychain:sevn.gateway.token}",
            },
            "channels": {"telegram": {"enabled": True}},
            "llm": {"main_model": "openai/gpt-test"},
        },
        profile_id="full_free",
    )
    telegram = next(c for c in report.checks if c.check_id == "telegram_get_me")
    assert "skipped" not in telegram.detail.lower()
    assert telegram.ok is True
    assert telegram.severity == "info"


@pytest.mark.anyio
async def test_get_wizard_credential_stops_at_first_backend_hit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sevn.onboarding import wizard_credentials as wc

    calls: list[str] = []

    async def _fake_get(_chain: object, key: str) -> str | None:
        calls.append(key)
        return "token-from-configured-section" if len(calls) == 1 else "fallback-token"

    monkeypatch.setattr(wc, "_secrets_chain", lambda _root, _sec: object())
    monkeypatch.setattr(wc, "_get_key_resilient", _fake_get)
    monkeypatch.setattr(
        wc, "_sections_for_read", lambda _section, workspace_only=False: [object(), None]
    )

    val = await wc.get_wizard_credential(
        tmp_path,
        "SEVN_TELEGRAM_BOT_TOKEN",
        section=object(),  # type: ignore[arg-type]
    )
    assert val == "token-from-configured-section"
    assert len(calls) == 1


def test_web_post_validate_all_persists_field_credentials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _wizard_client(tmp_path)
    payload = _valid_wizard_payload()
    fields = dict(payload["fields"])  # type: ignore[arg-type]
    fields["wizard.telegram_bot_token"] = "123456789:AAFakeTokenForTestsOnly"
    fields["wizard.provider_api_key.openai"] = "sk-test-key"
    fields["wizard.secrets_passphrase"] = "wizard-test-passphrase"
    payload["fields"] = fields

    async def _fake_get_me(self: object, url: str, **kwargs: object) -> object:
        _ = self, url, kwargs

        class _Resp:
            status_code = 200

            @staticmethod
            def json() -> dict[str, bool]:
                return {"ok": True}

        return _Resp()

    monkeypatch.setattr("sevn.onboarding.live_validate.httpx.AsyncClient.get", _fake_get_me)
    r = client.post(
        "/api/validate-all",
        params={"onboard_token": "tok"},
        json=payload,
    )
    assert r.status_code == 200
    telegram_rows = [c for c in r.json()["live_validation"] if c["check_id"] == "telegram_get_me"]
    assert telegram_rows
    assert telegram_rows[0]["ok"] is True


@pytest.mark.anyio
async def test_probe_llm_skipped_without_proxy() -> None:
    check = await probe_llm_reachability(
        merged_preview={"llm": {"main_model": "m"}}, cfg_proxy=None
    )
    assert check.severity == "info"
    assert "skipped" in check.detail


@pytest.mark.anyio
async def test_probe_llm_ping_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _ok(self: object, request: dict[str, object]) -> dict[str, object]:
        _ = self
        assert request["max_tokens"] == 1
        return {"usage": {"prompt_tokens": 1, "completion_tokens": 1}}

    monkeypatch.setattr(
        "sevn.agent.providers.transport.ChatCompletionsTransport.complete",
        _ok,
    )
    check = await probe_llm_reachability(
        merged_preview={
            "llm": {"main_model": "openai/gpt-test"},
            "proxy": {"url": "http://proxy.test"},
        },
        cfg_proxy=None,
    )
    assert check.ok is True
    assert check.severity == "info"
    assert "proxy ping ok" in check.detail


@pytest.mark.anyio
async def test_probe_llm_ping_connect_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _connect_fail(self: object, request: dict[str, object]) -> dict[str, object]:
        _ = self, request
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(
        "sevn.agent.providers.transport.ChatCompletionsTransport.complete",
        _connect_fail,
    )
    check = await probe_llm_reachability(
        merged_preview={
            "llm": {"main_model": "openai/gpt-test"},
            "proxy": {"url": "http://127.0.0.1:8787"},
        },
        cfg_proxy=None,
    )
    assert check.ok is False
    assert check.severity == "warn"
    assert "connection refused" in check.detail


@pytest.mark.anyio
async def test_probe_llm_ping_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fail(self: object, request: dict[str, object]) -> dict[str, object]:
        _ = self, request
        msg = "upstream 502"
        raise RuntimeError(msg)

    monkeypatch.setattr(
        "sevn.agent.providers.transport.ChatCompletionsTransport.complete",
        _fail,
    )
    check = await probe_llm_reachability(
        merged_preview={
            "llm": {"main_model": "openai/gpt-test"},
            "proxy": {"url": "http://proxy.test"},
        },
        cfg_proxy=None,
    )
    assert check.ok is False
    assert check.severity == "warn"
    assert "502" in check.detail


@pytest.mark.anyio
async def test_probe_llm_ping_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _slow(self: object, request: dict[str, object]) -> dict[str, object]:
        _ = self, request
        await asyncio.sleep(2.0)
        return {}

    monkeypatch.setattr(
        "sevn.agent.providers.transport.ChatCompletionsTransport.complete",
        _slow,
    )
    monkeypatch.setattr("sevn.onboarding.live_validate._LLM_PING_TIMEOUT_S", 0.05)
    check = await probe_llm_reachability(
        merged_preview={
            "llm": {"main_model": "openai/gpt-test"},
            "proxy": {"url": "http://proxy.test"},
        },
        cfg_proxy=None,
    )
    assert check.ok is False
    assert "timed out" in check.detail


@pytest.mark.anyio
async def test_probe_llm_ping_minimax_uses_anthropic_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}

    async def _capture(self: object, request: dict[str, object]) -> dict[str, object]:
        _ = self
        seen["model"] = request.get("model")
        seen["has_system_role"] = any(
            isinstance(m, dict) and m.get("role") == "system"
            for m in (request.get("messages") or [])  # type: ignore[union-attr]
        )
        return {"usage": {"input_tokens": 1, "output_tokens": 1}}

    monkeypatch.setattr(
        "sevn.agent.providers.transport._ProxyTransport.complete",
        _capture,
    )
    check = await probe_llm_reachability(
        merged_preview={
            "llm": {"main_model": "minimax/MiniMax-M2.7"},
            "proxy": {"url": "http://proxy.test"},
        },
        cfg_proxy=None,
    )
    assert check.ok is True
    assert seen["model"] == "MiniMax-M2.7"
    assert seen["has_system_role"] is False


@pytest.mark.anyio
async def test_probe_mcp_skipped_when_undeclared() -> None:
    check = await probe_mcp_reachability(
        merged_preview={
            "schema_version": 1,
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        }
    )
    assert check.severity == "info"
    assert "skipped" in check.detail


@pytest.mark.anyio
async def test_probe_mcp_stdio_success(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, list[str]]] = []

    async def _fake_init(command: str, args: list[str]) -> None:
        calls.append((command, args))

    monkeypatch.setattr("sevn.onboarding.live_validate._mcp_stdio_initialize", _fake_init)
    check = await probe_mcp_reachability(
        merged_preview={
            "mcp_servers": {
                "a": {"command": "echo", "args": ["mcp"]},
                "b": {"command": "true", "args": []},
            },
        },
    )
    assert check.ok is True
    assert calls == [("echo", ["mcp"]), ("true", [])]
    assert "a:ok" in check.detail
    assert "b:ok" in check.detail


@pytest.mark.anyio
async def test_onboard_tui_mounts_profile_step_without_duplicate_ids() -> None:
    """Regression: ``on_mount`` + reactive init must not double-mount ``profile_radio``."""
    app = OnboardApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        app.query_one("#profile_radio")
        await pilot.click("#next")
        await pilot.pause()
        assert app.step_idx == 1


@pytest.mark.anyio
async def test_probe_mcp_stdio_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fail(command: str, args: list[str]) -> None:
        _ = command, args
        msg = "handshake failed"
        raise RuntimeError(msg)

    monkeypatch.setattr("sevn.onboarding.live_validate._mcp_stdio_initialize", _fail)
    check = await probe_mcp_reachability(
        merged_preview={"mcp_servers": {"bad": {"command": "missing-bin", "args": []}}},
    )
    assert check.ok is False
    assert check.severity == "warn"
    assert "bad:error" in check.detail


def test_spawn_gateway_background_already_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.onboarding.gateway_spawn import spawn_gateway_background

    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "workspace_root": ".",
                "gateway": {
                    "host": "127.0.0.1",
                    "port": 3001,
                    "queue_mode": "cancel",
                    "token": "${SECRET:keychain:sevn.gateway.token}",
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sevn.onboarding.gateway_spawn.probe_gateway_listen_state",
        lambda **_: "running",
    )

    body = spawn_gateway_background(sevn_json_path=sevn_json)
    assert body["ok"] is True
    assert body["message"] == "gateway already running"
    assert (tmp_path / ".llmignore" / "blocked").is_dir()


def test_web_post_run_gateway_ok(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _wizard_client(tmp_path)
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "workspace_root": ".",
                "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
            }
        ),
        encoding="utf-8",
    )

    def _fake_proxy(*, sevn_json_path: Path) -> dict[str, object]:
        assert sevn_json_path == sevn_json
        return {
            "ok": True,
            "message": "proxy started",
            "pid": 1111,
            "log_path": str(tmp_path / "logs" / "proxy.log"),
        }

    def _fake_gateway(*, sevn_json_path: Path) -> dict[str, object]:
        assert sevn_json_path == sevn_json
        return {
            "ok": True,
            "message": "gateway started",
            "pid": 4242,
            "log_path": str(tmp_path / "logs" / "gateway.log"),
        }

    monkeypatch.setattr("sevn.onboarding.service_restart.unit_file_exists", lambda **_: False)
    monkeypatch.setattr("sevn.onboarding.proxy_spawn.spawn_proxy_background", _fake_proxy)
    monkeypatch.setattr("sevn.onboarding.gateway_spawn.spawn_gateway_background", _fake_gateway)
    r = client.post("/api/run-gateway", params={"onboard_token": "tok"}, json={})
    assert r.status_code == 200
    body = r.json()
    assert body["proxy"]["pid"] == 1111
    assert body["gateway"]["pid"] == 4242


@pytest.mark.anyio
async def test_credentials_status_locked_keystore_without_passphrase(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sevn.onboarding.wizard_credentials import credentials_status

    async def _locked(*_a: object, **_k: object) -> bool:
        return True

    monkeypatch.setattr(
        "sevn.onboarding.wizard_credentials._encrypted_store_needs_passphrase",
        _locked,
    )
    status = await credentials_status(tmp_path)
    assert status["needs_passphrase"] is True
    assert status["keystore_locked"] is True


@pytest.mark.anyio
async def test_unlock_wizard_keystore_wrong_passphrase(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sevn.onboarding.wizard_credentials import unlock_wizard_keystore

    async def _locked_status(*_a: object, **_k: object) -> dict[str, object]:
        return {"needs_passphrase": True, "ready_for_handoff": False}

    monkeypatch.setattr(
        "sevn.onboarding.wizard_credentials.credentials_status",
        _locked_status,
    )
    out = await unlock_wizard_keystore(tmp_path, "bad-pass")
    assert out["ok"] is False
    assert "Incorrect passphrase" in out["detail"]
    assert "SEVN_SECRETS_PASSPHRASE" not in os.environ


def test_web_existing_config_locked_keystore(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _wizard_client(tmp_path)
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "workspace_root": ".",
                "secrets_backend": {
                    "chain": [{"type": "encrypted_file", "path": ".sevn/secrets/store.enc"}],
                },
                "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
            }
        ),
        encoding="utf-8",
    )
    store = tmp_path / ".sevn" / "secrets"
    store.mkdir(parents=True)
    (store / "store.enc").write_bytes(b"encrypted")

    async def _locked(*_a: object, **_k: object) -> dict[str, object]:
        return {
            "present": {},
            "ready_for_handoff": False,
            "keystore_locked": True,
            "needs_passphrase": True,
        }

    monkeypatch.setattr("sevn.onboarding.web_app.credentials_status", _locked)
    monkeypatch.setenv("SEVN_ONBOARD_REUSE", "1")
    monkeypatch.setenv("SEVN_ONBOARD_GATE_RESOLVED", "1")
    r = client.get("/api/existing-config", params={"onboard_token": "tok"})
    assert r.status_code == 200
    body = r.json()
    assert body["needs_passphrase"] is True
    assert body["keystore_locked"] is True


@pytest.mark.anyio
async def test_credentials_status_wrong_passphrase_in_env_returns_locked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sevn.config.workspace_config import EncryptedFileBackendEntry, SecretsBackendSectionConfig
    from sevn.onboarding.github_oauth import GITHUB_TOKEN_LOGICAL_KEY
    from sevn.onboarding.wizard_credentials import credentials_status, get_wizard_credential
    from sevn.security.secrets.backends.encrypted_file import EncryptedFileBackend

    store = tmp_path / ".sevn" / "secrets" / "store.enc"
    store.parent.mkdir(parents=True)
    writer = EncryptedFileBackend(store, passphrase="correct horse battery staple")
    await writer.set(GITHUB_TOKEN_LOGICAL_KEY, "ghp_test")

    section = SecretsBackendSectionConfig(
        chain=[EncryptedFileBackendEntry(path=".sevn/secrets/store.enc")]
    )
    monkeypatch.setenv("SEVN_SECRETS_PASSPHRASE", "wrong-passphrase")

    status = await credentials_status(tmp_path, section=section)
    assert status["keystore_locked"] is True
    assert status["needs_passphrase"] is True
    assert "SEVN_SECRETS_PASSPHRASE" not in os.environ

    token = await get_wizard_credential(
        tmp_path,
        GITHUB_TOKEN_LOGICAL_KEY,
        section=section,
    )
    assert token is None


def test_web_existing_config_wrong_passphrase_returns_locked_not_500(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sevn.security.secrets.backends.encrypted_file import EncryptedFileBackend

    client = _wizard_client(tmp_path)
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "workspace_root": ".",
                "secrets_backend": {
                    "chain": [{"type": "encrypted_file", "path": ".sevn/secrets/store.enc"}],
                },
                "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
            }
        ),
        encoding="utf-8",
    )
    store = tmp_path / ".sevn" / "secrets" / "store.enc"
    store.parent.mkdir(parents=True)
    asyncio.run(
        EncryptedFileBackend(store, passphrase="correct horse battery staple").set(
            "integration.github.token",
            "ghp_test",
        )
    )
    monkeypatch.setenv("SEVN_SECRETS_PASSPHRASE", "wrong-passphrase")
    monkeypatch.setenv("SEVN_ONBOARD_REUSE", "1")
    monkeypatch.setenv("SEVN_ONBOARD_GATE_RESOLVED", "1")

    r = client.get("/api/existing-config", params={"onboard_token": "tok"})
    assert r.status_code == 200
    body = r.json()
    assert body["needs_passphrase"] is True
    assert body["keystore_locked"] is True

    r2 = client.get("/api/credentials-status", params={"onboard_token": "tok"})
    assert r2.status_code == 200
    assert r2.json()["needs_passphrase"] is True

    r3 = client.get("/api/github/status", params={"onboard_token": "tok"})
    assert r3.status_code == 200
    assert r3.json()["connected"] is False


@pytest.mark.anyio
async def test_run_live_validation_includes_pdf_weasyprint_probe(tmp_path: Path) -> None:
    report = await run_live_validation(
        workspace_root=tmp_path,
        merged_preview={
            "schema_version": 1,
            "workspace_root": ".",
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        },
        profile_id="good_value_osx",
    )
    by_id = {c.check_id: c for c in report.checks}
    assert "pdf_weasyprint" in by_id
    row = by_id["pdf_weasyprint"]
    assert isinstance(row.ok, bool)
    assert row.detail
    assert row.severity in ("info", "warn")
