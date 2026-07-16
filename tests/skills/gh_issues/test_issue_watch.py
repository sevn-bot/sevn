"""RED suite for GitHub issue view/watch/track + cron notify (D13; green after W6)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest  # noqa: TC002 — annotations for MonkeyPatch after W6 un-xfail

_REPO_ROOT = Path(__file__).resolve().parents[3]
_GH_ISSUES_ROOT = _REPO_ROOT / "src" / "sevn" / "data" / "bundled_skills" / "core" / "gh-issues"
_SCRIPTS = _GH_ISSUES_ROOT / "scripts"


def _load_script(name: str) -> Any:
    path = _SCRIPTS / name
    assert path.is_file(), f"missing script {path}"
    spec = importlib.util.spec_from_file_location(f"gh_issues_{path.stem}", path)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_d13_issue_view_includes_comment_bodies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D13: ``issue_view`` via ``gh --json`` includes comment bodies."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setenv("SEVN_WORKSPACE", str(workspace))

    gh_json = {
        "number": 21,
        "title": "Demo",
        "state": "OPEN",
        "url": "https://github.com/sevn-bot/sevn/issues/21",
        "updatedAt": "2026-07-15T12:00:00Z",
        "labels": [{"name": "bug"}],
        "assignees": [],
        "comments": [
            {"id": "C_1", "author": {"login": "alice"}, "body": "first comment body"},
            {"id": "C_2", "author": {"login": "bob"}, "body": "second comment body"},
        ],
    }

    def _fake_run(cmd: object, **_kwargs: object) -> Any:
        argv = [str(c) for c in cmd] if isinstance(cmd, (list, tuple)) else [str(cmd)]
        assert "issue" in argv
        assert "view" in argv
        assert "--json" in argv
        return MagicMock(returncode=0, stdout=json.dumps(gh_json), stderr="")

    mod = _load_script("issue_view.py")
    with patch("subprocess.run", side_effect=_fake_run), patch("asyncio.run") as arun:
        # Prefer gh path; if still proxy-only, main will fail → xfail.
        arun.side_effect = RuntimeError("proxy path must not win when gh is available")
        code = mod.main(["sevn-bot/sevn", "21"])
    # When W6 routes through gh, main returns 0 and stdout has comment bodies.
    # Drive via a helper if exposed:
    view_via_gh = getattr(mod, "view_issue_via_gh", None)
    if callable(view_via_gh):
        with patch("subprocess.run", side_effect=_fake_run):
            payload = view_via_gh("sevn-bot/sevn", 21)
        comments = payload.get("comments") or []
        bodies = [c.get("body") if isinstance(c, dict) else None for c in comments]
        assert "first comment body" in bodies
        assert "second comment body" in bodies
    else:
        assert code == 0


def test_d13_issue_watch_emits_only_diff(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """D13: ``issue_watch`` emits only changes vs ``.sevn/gh-watch/.../<n>.json``."""
    workspace = tmp_path / "ws"
    watch_dir = workspace / ".sevn" / "gh-watch" / "sevn-bot" / "sevn"
    watch_dir.mkdir(parents=True)
    state_path = watch_dir / "21.json"
    state_path.write_text(
        json.dumps(
            {
                "state": "OPEN",
                "updatedAt": "2026-07-14T00:00:00Z",
                "comment_count": 1,
                "last_comment_id": "C_1",
                "labels": ["bug"],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("SEVN_WORKSPACE", str(workspace))

    current = {
        "number": 21,
        "state": "CLOSED",
        "updatedAt": "2026-07-15T12:00:00Z",
        "labels": [{"name": "bug"}, {"name": "wontfix"}],
        "comments": [
            {"id": "C_1", "body": "old"},
            {"id": "C_2", "body": "new comment"},
        ],
    }

    mod = _load_script("issue_watch.py")
    with patch(
        "sevn.integrations.github_skill.watch.fetch_issue_state",
        return_value=current,
    ):
        result = mod.watch_issue(workspace, "sevn-bot/sevn", 21)  # type: ignore[attr-defined]

    assert isinstance(result, dict)
    changes = result.get("changes") or result.get("diff") or result
    blob = json.dumps(changes).lower()
    assert "closed" in blob or "state" in blob
    assert "c_2" in blob or "new comment" in blob or "comment" in blob
    assert "wontfix" in blob or "label" in blob

    # Unchanged → empty diff.
    state_path.write_text(
        json.dumps(
            {
                "state": "CLOSED",
                "updatedAt": "2026-07-15T12:00:00Z",
                "comment_count": 2,
                "last_comment_id": "C_2",
                "labels": ["bug", "wontfix"],
            }
        ),
        encoding="utf-8",
    )
    with patch(
        "sevn.integrations.github_skill.watch.fetch_issue_state",
        return_value=current,
    ):
        again = mod.watch_issue(workspace, "sevn-bot/sevn", 21)  # type: ignore[attr-defined]
    again_changes = again.get("changes") if isinstance(again, dict) else again
    assert again_changes in (None, {}, [], {"changes": []}) or again.get("changed") is False


def test_d13_issue_track_add_remove_list(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """D13: ``issue_track --add/--remove/--list`` mutates ``tracked.json``."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setenv("SEVN_WORKSPACE", str(workspace))
    mod = _load_script("issue_track.py")

    assert mod.main(["--add", "21", "--repo", "sevn-bot/sevn"]) == 0
    tracked = workspace / ".sevn" / "gh-watch" / "tracked.json"
    assert tracked.is_file()
    data = json.loads(tracked.read_text(encoding="utf-8"))
    assert "21" in json.dumps(data)

    assert mod.main(["--list"]) == 0
    assert mod.main(["--remove", "21", "--repo", "sevn-bot/sevn"]) == 0
    data2 = json.loads(tracked.read_text(encoding="utf-8"))
    assert "21" not in json.dumps(data2) or data2 in ([], {}, {"issues": []})


def test_d13_cron_scope_registered_and_notifies_on_diff() -> None:
    """D13: cron scope for issue_watch exists; on diff it delivers operator notify."""
    from sevn.triggers import dispatcher as dispatcher_mod
    from sevn.triggers import issue_watch_cron as watch_cron_mod

    assert hasattr(watch_cron_mod, "ISSUE_WATCH_CRON_JOB_ID")
    assert watch_cron_mod.ISSUE_WATCH_CRON_JOB_ID == "gh-issue-watch"
    assert callable(watch_cron_mod.run_issue_watch_cron)

    notify = getattr(dispatcher_mod, "notify_issue_watch_diff", None)
    assert callable(notify), "dispatcher must expose issue-watch notify"

    message_calls: list[object] = []

    def _fake_message(*_a: object, **_k: object) -> None:
        message_calls.append((_a, _k))

    with patch("sevn.triggers.operator_notify.deliver_operator_notify", _fake_message):
        notify(diffs=[{"repo": "sevn-bot/sevn", "number": 21, "changes": {"new_comment": "hi"}}])
    assert message_calls, "on diff, cron must deliver operator notify"
