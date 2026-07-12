"""SkillsManager integration-style tests with temp workspace trees."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from sevn.config.workspace_config import parse_workspace_config
from sevn.skills.errors import (
    SKILL_INVALID_JSON,
    SKILL_QUARANTINED,
    SKILL_RUNNABLE_UNSUPPORTED,
    SKILL_SCRIPT_ARGS,
    SkillExecutionError,
)
from sevn.skills.manager import SkillsManager, did_you_mean_skill_script
from sevn.workspace.layout import WorkspaceLayout


@pytest.fixture(autouse=True)
def _reset_skill_singletons() -> None:
    SkillsManager.reset_singletons_for_tests()
    yield
    SkillsManager.reset_singletons_for_tests()


def _write_min_skill(skill_dir: Path, *, description: str, version: str = "1.0.0") -> None:
    skill_dir.mkdir(parents=True, exist_ok=True)
    scripts = skill_dir / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    (scripts / "run.py").write_text(
        textwrap.dedent(
            """\
            import json, sys
            print(json.dumps({"ok": True, "data": {}, "message": None}), flush=True)
            """
        ),
        encoding="utf-8",
    )
    name = skill_dir.name
    (skill_dir / "SKILL.md").write_text(
        textwrap.dedent(
            f"""\
            ---
            name: {name}
            description: {description}
            version: {version}
            scripts:
              - path: scripts/run.py
                description: main
            ---
            body
            """
        ),
        encoding="utf-8",
    )


def test_collision_user_over_generated_over_core(tmp_path: Path) -> None:
    skills = tmp_path / "skills"
    for tree, desc in (
        ("core", "coredesc"),
        ("generated", "gendesc"),
        ("user", "userdesc"),
    ):
        _write_min_skill(skills / tree / "dupskill", description=desc)
    lay = WorkspaceLayout(sevn_json_path=tmp_path / "sevn.json", content_root=tmp_path)
    man = SkillsManager.shared(
        tmp_path,
        (skills,),
        layout=lay,
        config=parse_workspace_config(
            {"schema_version": 1, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}
        ),
    )
    assert man.index.lines["dupskill"].endswith("— userdesc")
    rec = man.get_record("dupskill")
    assert rec.provenance == "user"


def test_generated_draft_not_indexed(tmp_path: Path) -> None:
    skills = tmp_path / "skills"
    draft = skills / "generated" / "draft" / "d123"
    _write_min_skill(draft, description="draft only")
    _write_min_skill(skills / "generated" / "live", description="live")
    lay = WorkspaceLayout(sevn_json_path=tmp_path / "sevn.json", content_root=tmp_path)
    man = SkillsManager.shared(
        tmp_path,
        (skills,),
        layout=lay,
        config=parse_workspace_config(
            {"schema_version": 1, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}
        ),
    )
    assert "d123" not in man.index.lines
    assert "live" in man.index.lines


@pytest.mark.asyncio
async def test_generated_quarantine_blocks_run_script(tmp_path: Path) -> None:
    skills = tmp_path / "skills"
    d = skills / "generated" / "g1"
    d.mkdir(parents=True)
    scripts = d / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "run.py").write_text("print('x')\n", encoding="utf-8")
    (d / "SKILL.md").write_text(
        textwrap.dedent(
            """\
            ---
            name: g1
            description: q
            version: 1.0.0
            scripts:
              - path: scripts/run.py
                description: main
            quarantine: true
            ---
            body
            """
        ),
        encoding="utf-8",
    )
    lay = WorkspaceLayout(sevn_json_path=tmp_path / "sevn.json", content_root=tmp_path)
    man = SkillsManager.shared(
        tmp_path,
        (skills,),
        layout=lay,
        config=parse_workspace_config(
            {"schema_version": 1, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}
        ),
    )
    out = await man.run_script("g1", "scripts/run.py")
    assert out["ok"] is False
    assert out["code"] == SKILL_QUARANTINED


@pytest.mark.asyncio
async def test_run_script_happy_roundtrip(tmp_path: Path) -> None:
    skills = tmp_path / "skills"
    _write_min_skill(skills / "user" / "runner", description="runs")
    (tmp_path / ".llmignore" / "secret").mkdir(parents=True)
    secret = tmp_path / ".llmignore" / "secret" / "key.txt"
    secret.write_text("do-not-show", encoding="utf-8")
    lay = WorkspaceLayout(sevn_json_path=tmp_path / "sevn.json", content_root=tmp_path)
    man = SkillsManager.shared(
        tmp_path,
        (skills,),
        layout=lay,
        config=parse_workspace_config(
            {"schema_version": 1, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}
        ),
    )
    out = await man.run_script("runner", "scripts/run.py")
    assert out["ok"] is True


@pytest.mark.asyncio
async def test_run_script_rejects_missing_required_argv(tmp_path: Path) -> None:
    """run_script fails fast with SKILL_SCRIPT_ARGS when argv is too short."""
    skills = tmp_path / "skills"
    skill_dir = skills / "user" / "needs_url"
    skill_dir.mkdir(parents=True)
    scripts = skill_dir / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "capture.py").write_text("raise SystemExit(2)\n", encoding="utf-8")
    (skill_dir / "SKILL.md").write_text(
        textwrap.dedent(
            """\
            ---
            name: needs_url
            description: needs url
            version: 1.0.0
            scripts:
              - path: scripts/capture.py
                description: capture
                args_overview: "<url> [path] [--full-page]"
            ---
            body
            """
        ),
        encoding="utf-8",
    )
    lay = WorkspaceLayout(sevn_json_path=tmp_path / "sevn.json", content_root=tmp_path)
    man = SkillsManager.shared(
        tmp_path,
        (skills,),
        layout=lay,
        config=parse_workspace_config(
            {"schema_version": 1, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}
        ),
    )
    out = await man.run_script("needs_url", "scripts/capture.py", args=())
    assert out["ok"] is False
    assert out["code"] == SKILL_SCRIPT_ARGS
    assert "requires at least 1 positional argv" in str(out["error"])
    assert out["data"]["required_argv_count"] == 1
    assert out["data"]["argv_count"] == 0


@pytest.mark.asyncio
async def test_run_script_invalid_stdout_json(tmp_path: Path) -> None:
    skills = tmp_path / "skills"
    d = skills / "user" / "badout"
    d.mkdir(parents=True)
    scripts = d / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "run.py").write_text("print('not json')\n", encoding="utf-8")
    (d / "SKILL.md").write_text(
        textwrap.dedent(
            """\
            ---
            name: badout
            description: bad
            version: 1.0.0
            scripts:
              - path: scripts/run.py
                description: main
            ---
            body
            """
        ),
        encoding="utf-8",
    )
    lay = WorkspaceLayout(sevn_json_path=tmp_path / "sevn.json", content_root=tmp_path)
    man = SkillsManager.shared(
        tmp_path,
        (skills,),
        layout=lay,
        config=parse_workspace_config(
            {"schema_version": 1, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}
        ),
    )
    out = await man.run_script("badout", "scripts/run.py")
    assert out["ok"] is False
    assert out["code"] == SKILL_INVALID_JSON


@pytest.mark.asyncio
async def test_run_runnable_non_python_rejected(tmp_path: Path) -> None:
    skills = tmp_path / "skills"
    d = skills / "user" / "poly"
    d.mkdir(parents=True)
    scripts = d / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "stub.py").write_text("pass\n", encoding="utf-8")
    md = textwrap.dedent(
        """\
        ---
        name: poly
        description: p
        version: 1.0.0
        scripts:
          - path: scripts/stub.py
            description: st
        runnables:
          - id: go
            description: golang
            language: go
            parameters: []
        ---
        ## Inline runnables

        body
        """
    )
    (d / "SKILL.md").write_text(md, encoding="utf-8")
    lay = WorkspaceLayout(sevn_json_path=tmp_path / "sevn.json", content_root=tmp_path)
    man = SkillsManager.shared(
        tmp_path,
        (skills,),
        layout=lay,
        config=parse_workspace_config(
            {"schema_version": 1, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}
        ),
    )
    out = await man.run_runnable("poly", "go", {})
    assert out["ok"] is False
    assert out["code"] == SKILL_RUNNABLE_UNSUPPORTED


def test_duplicate_plugin_id_two_roots_raises(tmp_path: Path) -> None:
    skills_a = tmp_path / "skills_a"
    skills_b = tmp_path / "skills_b"
    for root in (skills_a, skills_b):
        plug = root / "plugins" / "p1" / "s1"
        plug.mkdir(parents=True)
        (plug / "SKILL.md").write_text(
            textwrap.dedent(
                """\
                ---
                name: s1
                description: plug
                version: 1.0.0
                scripts: []
                ---
                body
                """
            ),
            encoding="utf-8",
        )
    cfg = parse_workspace_config(
        {
            "schema_version": 1,
            "skills": {"p1": {"enabled": True}},
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        },
    )
    lay = WorkspaceLayout(sevn_json_path=tmp_path / "sevn.json", content_root=tmp_path)
    with pytest.raises(SkillExecutionError) as ei:
        SkillsManager.shared(
            tmp_path,
            (skills_a, skills_b),
            layout=lay,
            config=cfg,
        )
    assert "duplicate plugin skill id" in str(ei.value).lower()


def test_promote_clears_quarantine_frontmatter(tmp_path: Path) -> None:
    skills = tmp_path / "skills"
    g = skills / "generated" / "mvme"
    g.mkdir(parents=True)
    sg = g / "scripts"
    sg.mkdir(parents=True)
    (sg / "run.py").write_text("pass\n", encoding="utf-8")
    (g / "SKILL.md").write_text(
        textwrap.dedent(
            """\
            ---
            name: mvme
            description: mv
            version: 2.1.0
            quarantine: true
            scripts:
              - path: scripts/run.py
                description: main
            ---
            body
            """
        ),
        encoding="utf-8",
    )
    lay = WorkspaceLayout(sevn_json_path=tmp_path / "sevn.json", content_root=tmp_path)
    man = SkillsManager.shared(
        tmp_path,
        (skills,),
        layout=lay,
        config=parse_workspace_config(
            {"schema_version": 1, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}
        ),
    )
    man.promote_generated_to_user("mvme")
    u = skills / "user" / "mvme" / "SKILL.md"
    assert "quarantine: false" in u.read_text(encoding="utf-8")


def test_did_you_mean_skill_script_suggests_workspace_source_path(tmp_path: Path) -> None:
    """Declared script misses include the on-disk ``skills/core/…`` source path."""
    skills = tmp_path / "skills"
    pdf_dir = skills / "core" / "pdf"
    pdf_dir.mkdir(parents=True)
    scripts = pdf_dir / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "pdf.py").write_text("print('x')", encoding="utf-8")
    (pdf_dir / "SKILL.md").write_text(
        textwrap.dedent(
            """\
            ---
            name: pdf
            description: pdf helpers
            version: "1.0.0"
            scripts:
              - path: scripts/pdf.py
                description: render
            ---
            """
        ),
        encoding="utf-8",
    )
    lay = WorkspaceLayout(sevn_json_path=tmp_path / "sevn.json", content_root=tmp_path)
    SkillsManager.shared(
        tmp_path,
        (skills,),
        layout=lay,
        config=parse_workspace_config(
            {"schema_version": 1, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}
        ),
    )
    suggestions = did_you_mean_skill_script(tmp_path, "pdf", "scripts/pdf")
    assert "skills/core/pdf/scripts/pdf.py" in suggestions
    assert "scripts/pdf.py" in suggestions
