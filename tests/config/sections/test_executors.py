"""Executors and RLM section config tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from sevn.config.workspace_config import parse_workspace_config, rlm_json_dict


def test_rlm_lambda_backend_requires_non_empty_allowlist() -> None:
    raw = {
        "schema_version": 1,
        "rlm": {"c_d_backend": "lambda_rlm", "lambda_tool_allowlist": []},
        "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
    }
    with pytest.raises(ValidationError, match="lambda_tool_allowlist"):
        parse_workspace_config(raw)


def test_rlm_lambda_backend_with_allowlist_ok() -> None:
    raw = {
        "schema_version": 1,
        "rlm": {"c_d_backend": "lambda_rlm", "lambda_tool_allowlist": ["echo"]},
        "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
    }
    cfg = parse_workspace_config(raw)
    assert cfg.rlm is not None
    assert cfg.rlm.c_d_backend == "lambda_rlm"
    assert cfg.rlm.lambda_tool_allowlist == ["echo"]


def test_plan_approval_section_defaults() -> None:
    cfg = parse_workspace_config(
        {
            "schema_version": 1,
            "plan_approval": {},
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        }
    )
    assert cfg.plan_approval is not None
    assert cfg.plan_approval.enabled is False


def test_rlm_json_dict_helper() -> None:
    cfg = parse_workspace_config(
        {
            "schema_version": 1,
            "rlm": {"docker_image": "x/y:z"},
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        }
    )
    assert rlm_json_dict(cfg).get("docker_image") == "x/y:z"


def test_lambda_rlm_enabled_requires_lambda_backend_ok() -> None:
    cfg = parse_workspace_config(
        {
            "schema_version": 1,
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
            "executors": {"tier_cd": {"lambda_rlm": {"enabled": True}}},
            "rlm": {"c_d_backend": "lambda_rlm", "lambda_tool_allowlist": ["echo"]},
        },
    )
    assert cfg.executors is not None
    assert cfg.executors.tier_cd is not None
    assert cfg.executors.tier_cd.lambda_rlm is not None
    assert cfg.executors.tier_cd.lambda_rlm.enabled is True


def test_lambda_rlm_enabled_without_lambda_backend_fails() -> None:
    with pytest.raises(ValidationError, match=r"rlm\.c_d_backend must be lambda_rlm"):
        parse_workspace_config(
            {
                "schema_version": 1,
                "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
                "executors": {"tier_cd": {"lambda_rlm": {"enabled": True}}},
                "rlm": {"c_d_backend": "dspy", "lambda_tool_allowlist": ["echo"]},
            },
        )


def test_lambda_rlm_enabled_without_allowlist_allows_dspy_backend() -> None:
    cfg = parse_workspace_config(
        {
            "schema_version": 1,
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
            "executors": {"tier_cd": {"lambda_rlm": {"enabled": True}}},
            "rlm": {"c_d_backend": "dspy"},
        },
    )
    assert cfg.rlm is not None
    assert cfg.rlm.c_d_backend == "dspy"
