"""Schema and long-description contracts for cua computer-use skills (W0.3 / W1.3)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import jsonschema
import pytest

REPO = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO / "infra" / "sevn.schema.json"
LONG_DESC_PATH = REPO / "infra" / "sevn_config_long_description.json"
DATA_LONG_DESC_PATH = REPO / "src" / "sevn" / "data" / "sevn_config_long_description.json"


def _load_schema() -> dict[str, object]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _skills_properties() -> dict[str, object]:
    schema = _load_schema()
    skills = schema.get("properties", {})
    assert isinstance(skills, dict)
    skills_obj = skills.get("skills")
    assert isinstance(skills_obj, dict)
    props = skills_obj.get("properties")
    assert isinstance(props, dict)
    return props


def _block_props(block_key: str) -> dict[str, object]:
    props = _skills_properties()
    block = props.get(block_key)
    assert isinstance(block, dict)
    inner = block.get("properties")
    assert isinstance(inner, dict)
    return inner


def test_computer_use_schema_enabled_default_false() -> None:
    """Existing ``skills.computer_use.enabled`` stays default false."""
    enabled = _block_props("computer_use").get("enabled")
    assert isinstance(enabled, dict)
    assert enabled.get("default") is False


def test_computer_use_schema_target_enum_and_default() -> None:
    target = _block_props("computer_use").get("target")
    assert isinstance(target, dict)
    assert target.get("default") == "host"
    assert set(target.get("enum", [])) == {"host", "docker", "cloud", "lume"}


def test_computer_use_schema_snapshot_block() -> None:
    snapshot = _block_props("computer_use").get("snapshot")
    assert isinstance(snapshot, dict)
    annotate = snapshot.get("properties", {}).get("annotate")
    assert isinstance(annotate, dict)
    assert annotate.get("default") is False


def test_computer_use_schema_trajectory_block() -> None:
    trajectory = _block_props("computer_use").get("trajectory")
    assert isinstance(trajectory, dict)
    props = trajectory.get("properties")
    assert isinstance(props, dict)
    assert props.get("enabled", {}).get("default") is True
    assert props.get("share", {}).get("default") is True


def test_cua_agent_schema_block() -> None:
    props = _block_props("cua_agent")
    assert props.get("enabled", {}).get("default") is False
    assert props.get("require_computer_use", {}).get("default") is True
    approval = props.get("approval")
    assert isinstance(approval, dict)
    assert approval.get("default") == "per_run"
    assert approval.get("enum") == ["per_run"]


def test_lume_schema_block() -> None:
    props = _block_props("lume")
    assert props.get("enabled", {}).get("default") is False


@pytest.mark.parametrize(
    "key",
    [
        "skills.computer_use.target",
        "skills.computer_use.snapshot.annotate",
        "skills.computer_use.trajectory",
        "skills.cua_agent.enabled",
        "skills.cua_agent.approval",
        "skills.lume.enabled",
    ],
)
def test_long_description_keys_present(key: str) -> None:
    doc = json.loads(LONG_DESC_PATH.read_text(encoding="utf-8"))
    assert key in doc


def test_long_description_data_matches_infra() -> None:
    """Packaged copy mirrors ``infra/sevn_config_long_description.json`` after regen."""
    infra = json.loads(LONG_DESC_PATH.read_text(encoding="utf-8"))
    data = json.loads(DATA_LONG_DESC_PATH.read_text(encoding="utf-8"))
    assert data == infra


@pytest.mark.parametrize(
    ("fixture_name", "extra_skills"),
    [
        ("schema_v1_min.json", {}),
        (
            "schema_v2_min.json",
            {
                "computer_use": {
                    "enabled": True,
                    "target": "host",
                    "snapshot": {"annotate": False},
                    "trajectory": {"enabled": True, "share": True},
                },
                "cua_agent": {
                    "enabled": False,
                    "require_computer_use": True,
                    "approval": "per_run",
                },
                "lume": {"enabled": False},
            },
        ),
    ],
)
def test_golden_fixtures_validate_extended_skill_blocks(
    fixture_name: str,
    extra_skills: dict[str, object],
) -> None:
    golden_path = REPO / "tests" / "fixtures" / "config" / fixture_name
    doc = json.loads(golden_path.read_text(encoding="utf-8"))
    if extra_skills:
        skills = doc.setdefault("skills", {})
        assert isinstance(skills, dict)
        skills.update(extra_skills)
    schema = _load_schema()
    jsonschema.Draft202012Validator(schema).validate(doc)


def test_config_schema_gate_passes_today() -> None:
    """``make config-schema`` gate stays green on the current tree."""
    proc = subprocess.run(
        ["make", "config-schema"],
        cwd=REPO,
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
