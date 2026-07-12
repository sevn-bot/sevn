"""Unit tests for SKILL.md parsing."""

from __future__ import annotations

import textwrap

import pytest

from sevn.skills.errors import SKILL_VALIDATION, SkillExecutionError
from sevn.skills.manifest import (
    SkillManifest,
    SkillScriptEntry,
    infer_abortable_for_script,
    parse_skill_markdown,
    required_positional_arg_count,
    validate_script_argv,
)


def test_core_rejects_yaml_runnables() -> None:
    raw = textwrap.dedent(
        """\
        ---
        name: c
        description: d
        version: 1.0.0
        scripts: []
        runnables:
          - id: x
            description: y
            language: python
            parameters: []
        ---

        body
        """
    )
    with pytest.raises(SkillExecutionError) as ei:
        parse_skill_markdown(raw, "core")
    assert ei.value.code == SKILL_VALIDATION


def test_core_rejects_inline_runnable_fence() -> None:
    raw = textwrap.dedent(
        """\
        ---
        name: c
        description: d
        version: 1.0.0
        scripts: []
        ---

        ## Inline runnables

        ```python
        # sevn-runnable: {"schema_version": 1, "id": "r1", "description": "d", "language": "python", "parameters": []}
        print(1)
        ```
        """
    )
    with pytest.raises(SkillExecutionError) as ei:
        parse_skill_markdown(raw, "core")
    assert ei.value.code == SKILL_VALIDATION


def test_user_merges_yaml_and_fence_runnable() -> None:
    raw = textwrap.dedent(
        """\
        ---
        name: u
        description: line
        version: 1.0.0
        scripts: []
        runnables:
          - id: from_yaml
            description: y
            language: python
            parameters: []
        ---

        ## Inline runnables

        ```python
        # sevn-runnable: {"schema_version": 1, "id": "from_fence", "description": "f", "language": "python", "parameters": []}
        pass
        ```
        """
    )
    m = parse_skill_markdown(raw, "user")
    ids = {r.runnable_id for r in m.runnables}
    assert ids == {"from_fence", "from_yaml"}


def test_infer_abortable_heuristic() -> None:
    assert infer_abortable_for_script("scripts/wipe_disk.py", None) is False
    assert infer_abortable_for_script("scripts/helper.py", None) is True
    assert infer_abortable_for_script("scripts/helper.py", False) is False


def test_skill_manifest_quarantine_default_generated() -> None:
    m = SkillManifest(name="x", description="d", version="1.0.0")
    assert m.effective_quarantine("generated") is True
    assert m.effective_quarantine("user") is False


def test_required_positional_arg_count() -> None:
    """Angle-bracket placeholders outside [...] count as required argv slots."""
    assert required_positional_arg_count(None) == 0
    assert required_positional_arg_count("") == 0
    assert required_positional_arg_count("(no args)") == 0
    assert required_positional_arg_count("[--force]") == 0
    assert required_positional_arg_count("[cdp_url]") == 0
    assert required_positional_arg_count("--query STR [--limit N]") == 0
    assert required_positional_arg_count("<url> [path] [--full-page]") == 1
    assert required_positional_arg_count("[--tab <target_id>] <url>") == 1
    assert required_positional_arg_count("[--tab <target_id>] <selector> <text>") == 2


def test_validate_script_argv() -> None:
    """validate_script_argv rejects short argv before subprocess spawn."""
    row = SkillScriptEntry(
        path="scripts/capture.py",
        description="navigate + screenshot",
        args_overview="<url> [path] [--full-page]",
    )
    assert validate_script_argv(row, None) is not None
    assert validate_script_argv(row, []) is not None
    assert validate_script_argv(row, ["https://example.com"]) is None
    assert validate_script_argv(row, ["https://example.com", "out.png"]) is None
