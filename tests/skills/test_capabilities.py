"""Tests for load_skill capability rows."""

from __future__ import annotations

from sevn.skills.capabilities import build_skill_capability_rows
from sevn.skills.manifest import RunnableEntry, SkillManifest, SkillScriptEntry


def test_build_rows_mixed() -> None:
    m = SkillManifest(
        name="z",
        description="d",
        version="1.0.0",
        scripts=(SkillScriptEntry(path="scripts/foo.py", description="Foo op"),),
        runnables=(
            RunnableEntry(
                runnable_id="r1",
                description="run",
                language="python",
                parameters=[],
                source_body="print(1)",
            ),
        ),
    )
    rows = build_skill_capability_rows(m)
    assert rows[0]["type"] == "script"
    assert rows[0]["path"] == "scripts/foo.py"
    assert rows[1]["type"] == "runnable"
    assert rows[1]["id"] == "r1"
