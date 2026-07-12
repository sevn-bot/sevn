"""Root workspace config: loader, goldens, production guards, facade contract."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sevn.config import (
    PROCESS_SETTINGS_ENV_VAR_NAMES,
    SUPPORTED_SCHEMA_VERSIONS,
    ProcessSettings,
    SevnJsonNotFoundError,
    UnsupportedSchemaVersionError,
    WorkspaceLayout,
    ensure_schema_supported,
    find_sevn_json,
    load_workspace,
    parse_workspace_config,
)
from sevn.config.workspace_config import (
    GatewayConfig,
    RlmWorkspaceConfig,
    SecretsBackendSectionConfig,
    TelegramChannelConfig,
    WorkspaceConfig,
)


def test_parse_minimal_config() -> None:
    cfg = parse_workspace_config(
        {"schema_version": 1, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}
    )
    assert cfg.schema_version == 1
    assert cfg.workspace_root == "."


def test_parse_schema_version_2() -> None:
    cfg = parse_workspace_config(
        {
            "schema_version": 2,
            "workspace_root": ".",
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        }
    )
    assert cfg.schema_version == 2


def test_parse_preserves_extra_top_level() -> None:
    cfg = parse_workspace_config(
        {
            "schema_version": 1,
            "witchcraft_enabled": True,
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        }
    )
    assert cfg.model_extra is not None
    assert cfg.model_extra.get("witchcraft_enabled") is True


def test_unsupported_schema_version() -> None:
    with pytest.raises(UnsupportedSchemaVersionError):
        ensure_schema_supported(max(SUPPORTED_SCHEMA_VERSIONS) + 99)


def test_load_workspace_explicit(tmp_path: Path) -> None:
    p = tmp_path / "sevn.json"
    p.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "workspace_root": "app",
                "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
            }
        ),
        encoding="utf-8",
    )
    cfg, lay = load_workspace(sevn_json=p)
    assert cfg.workspace_root == "app"
    assert lay.content_root == (tmp_path / "app").resolve()
    assert lay.dot_sevn == lay.content_root / ".sevn"


def test_find_sevn_json_walks_parents(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    nested = root / "a" / "b"
    nested.mkdir(parents=True)
    (root / "sevn.json").write_text(
        '{"schema_version": 1, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
        encoding="utf-8",
    )
    found = find_sevn_json(nested)
    assert found == (root / "sevn.json").resolve()


def test_load_missing_file(tmp_path: Path) -> None:
    with pytest.raises(SevnJsonNotFoundError):
        load_workspace(sevn_json=tmp_path / "missing.json")


def test_load_not_found_search(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEVN_HOME", str(tmp_path / "home"))
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(SevnJsonNotFoundError):
        load_workspace(start_dir=empty)


def test_process_settings_reads_sevn_prefixed_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEVN_GATEWAY_TOKEN", "tok")
    assert ProcessSettings().gateway_token == "tok"


def test_process_settings_env_matches_schema_allowlist() -> None:
    """``PROCESS_SETTINGS_ENV_VAR_NAMES`` ↔ ``infra/sevn.schema.json`` (02 §2.5, 23-cli)."""
    schema_path = Path(__file__).resolve().parents[2] / "infra" / "sevn.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    listed = frozenset(schema["x-sevn-process-settings-env"])
    assert listed == PROCESS_SETTINGS_ENV_VAR_NAMES
    marked = frozenset(
        e["name"] for e in schema["x-sevn-env-allowlist"] if e.get("process_settings") is True
    )
    assert marked == PROCESS_SETTINGS_ENV_VAR_NAMES


def test_golden_schema_v1_fixture_roundtrip(tmp_path: Path) -> None:
    """Regression anchor: committed minimal `sevn.json` matches Pydantic models."""
    fix = Path(__file__).resolve().parent.parent / "fixtures" / "config" / "schema_v1_min.json"
    sevn = tmp_path / "sevn.json"
    sevn.write_text(fix.read_text(encoding="utf-8"), encoding="utf-8")
    cfg, lay = load_workspace(sevn_json=sevn)
    ensure_schema_supported(cfg.schema_version)
    assert cfg.gateway is not None
    assert cfg.gateway.host == "127.0.0.1"
    assert cfg.gateway.queue_mode == "cancel"
    assert cfg.tracing is not None
    assert cfg.tracing.sinks is not None
    assert cfg.tracing.sinks[0].sink_type == "jsonl_file"
    assert lay.traces_dir(cfg) == (lay.content_root / ".sevn" / "traces").resolve()


def test_golden_schema_v2_fixture_roundtrip(tmp_path: Path) -> None:
    """Same shape as v1 golden; ``schema_version`` 2 after migrate (`specs/22-onboarding.md`)."""
    fix = Path(__file__).resolve().parent.parent / "fixtures" / "config" / "schema_v2_min.json"
    sevn = tmp_path / "sevn.json"
    sevn.write_text(fix.read_text(encoding="utf-8"), encoding="utf-8")
    cfg, lay = load_workspace(sevn_json=sevn)
    ensure_schema_supported(cfg.schema_version)
    assert cfg.schema_version == 2
    assert cfg.gateway is not None
    assert cfg.gateway.host == "127.0.0.1"
    assert cfg.gateway.queue_mode == "cancel"
    assert cfg.tracing is not None
    assert cfg.tracing.sinks is not None
    assert cfg.tracing.sinks[0].sink_type == "jsonl_file"
    assert lay.traces_dir(cfg) == (lay.content_root / ".sevn" / "traces").resolve()


def test_workspace_root_tilde_not_literal_under_parent(tmp_path: Path) -> None:
    """``~/.sevn.bot`` must expand to home, not a literal ``~/`` directory under workspace."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    cfg_path = ws / "sevn.json"
    cfg_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "workspace_root": "~/.sevn.bot",
                "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
            }
        ),
        encoding="utf-8",
    )
    cfg = parse_workspace_config(json.loads(cfg_path.read_text(encoding="utf-8")))
    lay = WorkspaceLayout.from_config(cfg_path, cfg)
    assert "~" not in lay.content_root.parts
    assert lay.content_root.name == ".sevn.bot"
    assert lay.content_root.parent == Path.home().resolve()


def test_workspace_root_dot_is_sevn_json_parent(tmp_path: Path) -> None:
    ws = tmp_path / "workspace"
    ws.mkdir()
    cfg_path = ws / "sevn.json"
    cfg_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "workspace_root": ".",
                "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
            }
        ),
        encoding="utf-8",
    )
    cfg = parse_workspace_config(json.loads(cfg_path.read_text(encoding="utf-8")))
    lay = WorkspaceLayout.from_config(cfg_path, cfg)
    assert lay.content_root == ws.resolve()


def test_workspace_config_facade_reexports_section_symbols() -> None:
    """Public import path unchanged after ``sections/`` split (`specs/02` §2.1)."""
    assert WorkspaceConfig is not None
    assert GatewayConfig.__module__.endswith("gateway")
    assert RlmWorkspaceConfig.__module__.endswith("executors")
    assert SecretsBackendSectionConfig.__module__.endswith("secrets")
    assert TelegramChannelConfig.__module__.endswith("channels")
