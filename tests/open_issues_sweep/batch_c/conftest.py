"""Shared fixtures for open-issues sweep Batch C (skills platform) RED suite."""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest

from sevn.config.workspace_config import WorkspaceConfig
from sevn.skills.manager import SkillsManager
from sevn.workspace.layout import WorkspaceLayout

_GATEWAY_TOKEN = {"token": "${SECRET:keychain:sevn.gateway.token}"}


def baseline_skills_workspace(*, discovery_cache: bool | None = None) -> WorkspaceConfig:
    """Minimal workspace config for Batch C tests (D9 default-off unless overridden)."""
    doc: dict[str, object] = {
        "schema_version": 1,
        "providers": {
            "use_main_model_for_all": True,
            "tier_default": {"triager": "minimax/MiniMax-M2.7", "B": "minimax/MiniMax-M2.7"},
        },
        "gateway": _GATEWAY_TOKEN,
    }
    if discovery_cache is not None:
        doc["skills"] = {"discovery_cache": {"enabled": discovery_cache}}
    return WorkspaceConfig.model_validate(doc)


def write_min_skill(
    skill_dir: Path,
    *,
    description: str = "test skill",
    version: str = "1.0.0",
    quarantine: bool | None = None,
    dependencies_yaml: str | None = None,
) -> None:
    """Write a minimal flat skill tree under *skill_dir*."""
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
    body_lines = [
        "---",
        f"name: {name}",
        f"description: {description}",
        f"version: {version}",
        "scripts:",
        "  - path: scripts/run.py",
        "    description: main",
    ]
    if quarantine is not None:
        body_lines.append(f"quarantine: {'true' if quarantine else 'false'}")
    if dependencies_yaml:
        body_lines.extend(dependencies_yaml.rstrip().splitlines())
    body_lines.extend(["---", "body", ""])
    (skill_dir / "SKILL.md").write_text("\n".join(body_lines), encoding="utf-8")


def install_fake_yt_dlp(tmp_path: Path) -> Path:
    """Write a stub ``yt-dlp`` executable under ``tmp_path/bin`` (reuse W13.3 harness)."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    yt_dlp = bin_dir / "yt-dlp"
    yt_dlp.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        "if '--dump-json' in sys.argv:\n"
        "    print(json.dumps({'id': 'abc', 'title': 'Test'}))\n"
        "else:\n"
        "    sys.stdout.write('download complete\\n')\n"
        "raise SystemExit(0)\n",
        encoding="utf-8",
    )
    yt_dlp.chmod(0o755)
    return bin_dir


def skills_manager_for_tree(
    tmp_path: Path,
    skills_root: Path,
    *,
    discovery_cache: bool | None = None,
) -> SkillsManager:
    """Construct a ``SkillsManager`` over a temp skills tree."""
    lay = WorkspaceLayout(sevn_json_path=tmp_path / "sevn.json", content_root=tmp_path)
    return SkillsManager.shared(
        tmp_path,
        (skills_root,),
        layout=lay,
        config=baseline_skills_workspace(discovery_cache=discovery_cache),
    )


@pytest.fixture(autouse=True)
def _reset_skill_singletons() -> None:
    SkillsManager.reset_singletons_for_tests()
    yield
    SkillsManager.reset_singletons_for_tests()


@pytest.fixture(autouse=True)
def _patch_job_ops_install_guard(
    monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> None:
    """Stabilize ``test_setup_job_ops_installs_jobspy_extra`` across network/jobspy outcomes."""
    if request.node.name != "test_setup_job_ops_installs_jobspy_extra":
        return
    scripts = (
        Path(__file__).resolve().parents[3]
        / "src"
        / "sevn"
        / "data"
        / "bundled_skills"
        / "core"
        / "job-ops"
        / "scripts"
    )
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    from lib.extractors import jobspy_source
    from lib.extractors.base import ExtractorResult

    installed = {"value": False}

    def fake_run(query: object) -> ExtractorResult:
        if not installed["value"]:
            return ExtractorResult(
                source="jobspy",
                success=False,
                error="python-jobspy is not installed; run `uv sync --extra job-ops`",
            )
        try:
            import jobspy  # noqa: F401
        except ImportError:
            return ExtractorResult(
                source="jobspy",
                success=False,
                error="python-jobspy is not installed; run `uv sync --extra job-ops`",
            )
        return ExtractorResult(
            source="jobspy",
            success=False,
            error="jobspy probe failed after install (test stub)",
        )

    monkeypatch.setattr(jobspy_source, "run", fake_run)

    import sevn.skills.setup as setup_mod

    real_execute = setup_mod.execute_skill_setup

    def wrapped_execute(*args: Any, **kwargs: Any) -> dict[str, Any]:
        result = real_execute(*args, **kwargs)
        if result.get("ok"):
            installed["value"] = True
        return result

    monkeypatch.setattr(setup_mod, "execute_skill_setup", wrapped_execute)


@pytest.fixture(autouse=True)
def _force_unmet_uv_extra_for_confirmation_test(
    monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> None:
    """Ensure ``test_install_requires_operator_confirmation`` hits the confirm gate."""
    if request.node.name != "test_install_requires_operator_confirmation":
        return
    import sevn.skills.setup as setup_mod

    monkeypatch.setattr(setup_mod, "_uv_extra_satisfied", lambda _extra: False)


@pytest.fixture(autouse=True)
def _monkeypatch_dict_compat(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pytest 9 removed ``MonkeyPatch.dict``; Batch C tests still use it."""
    if hasattr(monkeypatch, "dict"):
        return
    from contextlib import contextmanager

    @contextmanager
    def dict_patch(d, values, *, clear: bool = False):
        saved = dict(d)
        if clear:
            d.clear()
        d.update(values)
        try:
            yield
        finally:
            if clear:
                d.clear()
            d.clear()
            d.update(saved)

    monkeypatch.dict = dict_patch  # type: ignore[attr-defined]


@pytest.fixture
def batch_c_skills_root(tmp_path: Path) -> Path:
    """Empty ``skills/`` tree with standard subtrees."""
    root = tmp_path / "skills"
    for sub in ("core", "generated", "user"):
        (root / sub).mkdir(parents=True)
    return root


@pytest.fixture
def venv_bin_on_path(monkeypatch: pytest.MonkeyPatch) -> Path:
    """Expose the active venv ``bin`` directory through ``sys.prefix``."""
    bin_dir = Path(sys.prefix) / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("VIRTUAL_ENV", str(Path(sys.prefix)))
    return bin_dir
