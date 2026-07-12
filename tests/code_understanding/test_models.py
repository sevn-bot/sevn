"""Pydantic validation tests for code-understanding settings."""

from __future__ import annotations

import pytest

from sevn.code_understanding.models import (
    CodeGraphRagSettings,
    CodeReviewGraphSettings,
    CodeUnderstandingSettings,
    GraphifyProfile,
    GraphifySettings,
    MycodeScanDigest,
    MycodeSettings,
    RoamCodeSettings,
)


def test_default_settings_match_spec_defaults() -> None:
    cfg = CodeUnderstandingSettings()
    assert cfg.mycode.enabled is True
    assert cfg.code_graph_rag.enabled is False
    assert cfg.code_review_graph.enabled is False
    assert cfg.code_review_graph.tool_preset == "read_only"
    assert cfg.roam_code.enabled is True
    assert cfg.graphify.enabled is False
    assert cfg.graphify.profiles == []


def test_mycode_settings_round_trip() -> None:
    cfg = MycodeSettings(
        enabled=False, default_root_path="x", output_path="y", ignore_patterns=["*.tmp"]
    )
    assert cfg.enabled is False
    assert cfg.ignore_patterns == ["*.tmp"]


def test_code_graph_rag_defaults_off() -> None:
    cfg = CodeGraphRagSettings()
    assert cfg.enabled is False
    assert cfg.host_ref is None


def test_roam_code_default_on() -> None:
    assert RoamCodeSettings().enabled is True


def test_graphify_profile_requires_root_and_output() -> None:
    p = GraphifyProfile(id="d", root_path="/r", output_dir="/o")
    assert p.label is None
    assert p.cli_flags == []


def test_graphify_profile_validated_flags_pass() -> None:
    p = GraphifyProfile(
        id="d", root_path="/r", output_dir="/o", cli_flags=["--no-viz", "--mode", "deep"]
    )
    assert p.validated_cli_flags() == ["--no-viz", "--mode", "deep"]


def test_graphify_profile_validated_flags_reject_unknown() -> None:
    p = GraphifyProfile(id="d", root_path="/r", output_dir="/o", cli_flags=["--rm-rf"])
    with pytest.raises(ValueError, match="unsupported graphify cli_flag"):
        p.validated_cli_flags()


def test_graphify_settings_carries_profiles() -> None:
    cfg = GraphifySettings(
        enabled=True,
        profiles=[GraphifyProfile(id="x", root_path="/r", output_dir="/o")],
    )
    assert cfg.enabled is True
    assert cfg.profiles[0].id == "x"


def test_code_review_graph_rejects_unknown_tool_preset() -> None:
    with pytest.raises(ValueError, match=r"unsupported code_review_graph\.tool_preset"):
        CodeReviewGraphSettings(tool_preset="mutate_all")


def test_mycode_scan_digest_serialisable() -> None:
    digest = MycodeScanDigest(root="/r", files=[], ignored=[])
    dumped = digest.model_dump()
    assert dumped["root"] == "/r"
    assert dumped["files"] == []
