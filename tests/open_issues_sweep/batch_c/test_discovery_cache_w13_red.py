"""W13.5-W13.6 - signature-based skill discovery cache (-> W15, #84)."""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Any

import pytest
from tests.open_issues_sweep.batch_c.conftest import (
    skills_manager_for_tree,
    write_min_skill,
)

from sevn.skills.errors import SKILL_QUARANTINED
from sevn.skills.manager import SkillsManager, _scan_skills_tree


def _reload_with_discovery_cache(
    manager: SkillsManager,
    *,
    enabled: bool,
) -> dict[str, int]:
    """Reload through the W15 discovery-cache seam (lazy import)."""
    from sevn.skills.discovery_cache import reload_skills_with_cache

    return reload_skills_with_cache(manager, enabled=enabled)


def _discovery_cache_path(content_root: Path) -> Path:
    """Return the on-disk cache file path for a workspace."""
    from sevn.skills.discovery_cache import discovery_cache_file

    return discovery_cache_file(content_root)


@pytest.mark.xfail(
    reason="green after W15: warm discovery cache skips tree scan (#84)", strict=False
)
def test_warm_discovery_cache_skips_rescan(
    tmp_path: Path,
    batch_c_skills_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A warm cache skips the filesystem tree scan on subsequent reloads."""
    write_min_skill(batch_c_skills_root / "user" / "alpha", description="alpha")
    man = skills_manager_for_tree(tmp_path, batch_c_skills_root, discovery_cache=True)
    calls: list[int] = []

    def _counting_scan(*args: Any, **kwargs: Any) -> list[tuple[int, Any]]:
        calls.append(1)
        return _scan_skills_tree(*args, **kwargs)

    monkeypatch.setattr("sevn.skills.discovery_cache._scan_skills_tree", _counting_scan)
    _reload_with_discovery_cache(man, enabled=True)
    assert calls == [1]
    _reload_with_discovery_cache(man, enabled=True)
    assert calls == [1], "second reload must hit cache without rescanning"


@pytest.mark.parametrize(
    ("trigger", "mutator"),
    [
        pytest.param(
            "manifest_edit",
            lambda skill_dir: (skill_dir / "SKILL.md").write_text(
                textwrap.dedent(
                    """\
                    ---
                    name: cacheme
                    description: edited
                    version: 2.0.0
                    scripts:
                      - path: scripts/run.py
                        description: main
                    ---
                    body
                    """
                ),
                encoding="utf-8",
            ),
            id="manifest_edit",
        ),
        pytest.param(
            "script_edit",
            lambda skill_dir: (skill_dir / "scripts" / "run.py").write_text(
                "print('mutated')\n",
                encoding="utf-8",
            ),
            id="script_edit",
        ),
    ],
)
@pytest.mark.xfail(reason="green after W15: discovery cache invalidation (#84)", strict=False)
def test_discovery_cache_invalidates_on_content_change(
    tmp_path: Path,
    batch_c_skills_root: Path,
    trigger: str,
    mutator: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Manifest or script edits invalidate the cached discovery snapshot."""
    _ = trigger
    skill_dir = batch_c_skills_root / "user" / "cacheme"
    write_min_skill(skill_dir, description="v1", version="1.0.0")
    man = skills_manager_for_tree(tmp_path, batch_c_skills_root, discovery_cache=True)
    calls: list[int] = []

    def _counting_scan(*args: Any, **kwargs: Any) -> list[tuple[int, Any]]:
        calls.append(1)
        return _scan_skills_tree(*args, **kwargs)

    monkeypatch.setattr("sevn.skills.discovery_cache._scan_skills_tree", _counting_scan)
    _reload_with_discovery_cache(man, enabled=True)
    mutator(skill_dir)
    _reload_with_discovery_cache(man, enabled=True)
    assert len(calls) == 2


@pytest.mark.xfail(reason="green after W15: registry version bump invalidates cache", strict=False)
def test_discovery_cache_invalidates_on_registry_version_bump(
    tmp_path: Path,
    batch_c_skills_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A global registry/tool version bump invalidates the discovery cache."""
    write_min_skill(batch_c_skills_root / "user" / "stable", description="stable")
    man = skills_manager_for_tree(tmp_path, batch_c_skills_root, discovery_cache=True)
    calls: list[int] = []

    def _counting_scan(*args: Any, **kwargs: Any) -> list[tuple[int, Any]]:
        calls.append(1)
        return _scan_skills_tree(*args, **kwargs)

    monkeypatch.setattr("sevn.skills.discovery_cache._scan_skills_tree", _counting_scan)
    _reload_with_discovery_cache(man, enabled=True)
    man.bump_registry_version()
    _reload_with_discovery_cache(man, enabled=True)
    assert len(calls) == 2


@pytest.mark.xfail(reason="green after W15: corrupt cache falls back to full scan", strict=False)
def test_corrupt_discovery_cache_falls_back_to_full_scan(
    tmp_path: Path,
    batch_c_skills_root: Path,
) -> None:
    """Missing or corrupt cache files degrade to a correct full scan."""
    write_min_skill(batch_c_skills_root / "user" / "recover", description="recover")
    cache_file = _discovery_cache_path(tmp_path)
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text("{not-json", encoding="utf-8")
    man = skills_manager_for_tree(tmp_path, batch_c_skills_root, discovery_cache=True)
    stats = _reload_with_discovery_cache(man, enabled=True)
    assert stats["new_count"] >= 1
    assert "recover" in man.index.lines


@pytest.mark.xfail(reason="green after W15: quarantine preserved on cache hit", strict=False)
@pytest.mark.asyncio
async def test_quarantine_preserved_across_discovery_cache_hit(
    tmp_path: Path,
    batch_c_skills_root: Path,
) -> None:
    """Quarantine state survives a warm discovery-cache reload."""
    write_min_skill(
        batch_c_skills_root / "generated" / "qskill",
        description="quarantined",
        quarantine=True,
    )
    man = skills_manager_for_tree(tmp_path, batch_c_skills_root, discovery_cache=True)
    _reload_with_discovery_cache(man, enabled=True)
    rec = man.get_record("qskill")
    assert rec.manifest.effective_quarantine("generated") is True
    _reload_with_discovery_cache(man, enabled=True)
    rec2 = man.get_record("qskill")
    assert rec2.manifest.effective_quarantine("generated") is True
    out = await man.run_script("qskill", "scripts/run.py")
    assert out["ok"] is False
    assert out["code"] == SKILL_QUARANTINED


@pytest.mark.xfail(reason="green after W15: parse-failure quarantine survives cache", strict=False)
def test_parse_failure_quarantine_preserved_on_cache_hit(
    tmp_path: Path,
    batch_c_skills_root: Path,
) -> None:
    """User skills that fail parse downgrade to quarantine and stay quarantined on cache hit."""
    broken = batch_c_skills_root / "user" / "broken"
    broken.mkdir(parents=True)
    man = skills_manager_for_tree(tmp_path, batch_c_skills_root, discovery_cache=True)
    _reload_with_discovery_cache(man, enabled=True)
    assert "broken" in man._records
    rec = man.get_record("broken")
    assert rec.manifest.effective_quarantine("user") is True
    assert rec.validation_errors
    _reload_with_discovery_cache(man, enabled=True)
    rec2 = man.get_record("broken")
    assert rec2.manifest.effective_quarantine("user") is True


def test_discovery_cache_default_off_is_noop(
    tmp_path: Path,
    batch_c_skills_root: Path,
) -> None:
    """With the default-off flag unset, reload behaviour matches today's full scan (D9)."""
    write_min_skill(batch_c_skills_root / "user" / "plain", description="plain")
    man = skills_manager_for_tree(tmp_path, batch_c_skills_root, discovery_cache=None)
    stats = man.reload()
    assert stats["new_count"] >= 1
    assert "plain" in man.index.lines
