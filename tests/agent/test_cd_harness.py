"""Tier C/D harness shared regression (`specs/21-executor-tier-cd.md` §9).

DSPy and λ-RLM gate tests live in ``test_tier_cd_dspy.py`` and ``test_tier_cd_lambda.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from sevn.config.workspace_config import parse_workspace_config


def test_parse_workspace_lambda_requires_allowlist() -> None:
    with pytest.raises(ValidationError):
        parse_workspace_config(
            {
                "schema_version": 1,
                "rlm": {"c_d_backend": "lambda_rlm", "lambda_tool_allowlist": []},
                "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
            }
        )


def test_lambda_macro_alias_is_same_callable() -> None:
    from sevn.agent.executors.lambda_rlm_runtime import lambda_macro_execute, run_lambda_rlm_turn

    assert run_lambda_rlm_turn is lambda_macro_execute


def test_cd_harness_has_no_channels_import() -> None:
    import sevn.agent.executors.cd_harness as mod

    src = Path(mod.__file__).read_text(encoding="utf-8")
    assert "sevn.channels" not in src
