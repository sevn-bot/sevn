"""Tests for last30days briefing, daily_digest, and filter_raw helpers."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

_SKILL_ROOT = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "sevn"
    / "data"
    / "bundled_skills"
    / "core"
    / "last30days"
)
_BRIEFING_SCRIPT = _SKILL_ROOT / "scripts" / "briefing.py"
_DAILY_DIGEST_SCRIPT = _SKILL_ROOT / "scripts" / "daily_digest.py"
_FILTER_SCRIPT = _SKILL_ROOT / "scripts" / "filter_raw.py"
_STORE_DIR = _SKILL_ROOT / "scripts"


def _run_script(
    script: Path, argv: list[str], *, env: dict[str, str] | None = None
) -> tuple[int, dict]:
    proc = subprocess.run(
        [sys.executable, str(script), *argv],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    payload = json.loads(proc.stdout.strip() or "{}")
    return proc.returncode, payload


def test_briefing_generate_fails_fast_without_topics(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Empty watchlist exits nonzero with a structured NO_TOPICS envelope."""
    db_home = tmp_path / "last30days_home"
    db_home.mkdir()
    monkeypatch.setenv("HOME", str(db_home))
    code, payload = _run_script(_BRIEFING_SCRIPT, ["generate"])
    assert code == 1
    assert payload.get("ok") is False
    assert payload.get("code") == "NO_TOPICS"


def test_filter_raw_extracts_recent_items(tmp_path: Path) -> None:
    """filter_raw.py returns dated rows without shell/grep."""
    raw = tmp_path / "sample-raw.md"
    raw.write_text(
        """### 1. Example cluster
1. [github] feat: agentic AI verification layer
   - 2026-07-11 | Aparnap2/opscore | [1react, 1cmt] | score:39
   - URL: https://github.com/Aparnap2/opscore/pull/3
   - Evidence: summary
1. [hackernews] Older item
   - 2026-06-01 | Hacker News | [3pts] | score:10
   - URL: https://example.com/old
   - Evidence: old
""",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["SEVN_WORKSPACE"] = str(tmp_path)
    code, payload = _run_script(
        _FILTER_SCRIPT,
        ["--path", str(raw), "--since-date", "2026-07-11"],
        env=env,
    )
    assert code == 0
    assert payload.get("ok") is True
    data = payload.get("data")
    assert isinstance(data, dict)
    items = data.get("items")
    assert isinstance(items, list)
    assert len(items) == 1
    assert items[0]["url"] == "https://github.com/Aparnap2/opscore/pull/3"


def test_daily_digest_fails_without_watchlist_topic(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Missing watchlist topic exits NOT_FOUND."""
    db_home = tmp_path / "last30days_home"
    db_home.mkdir()
    monkeypatch.setenv("HOME", str(db_home))
    code, payload = _run_script(
        _DAILY_DIGEST_SCRIPT,
        ["run", "--topic", "missing topic"],
    )
    assert code == 1
    assert payload.get("ok") is False
    assert payload.get("code") == "NOT_FOUND"


def test_get_findings_new_in_run_excludes_prior_urls(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """URL-dedup updates must not appear in new-only run findings."""
    db_home = tmp_path / "last30days_home"
    db_home.mkdir()
    monkeypatch.setenv("HOME", str(db_home))
    for mod in ("lib", "store"):
        sys.modules.pop(mod, None)
    sys.path.insert(0, str(_STORE_DIR))
    import store as last30_store

    last30_store.init_db()
    topic = last30_store.add_topic("Agentic AI eval loops")
    run_one = last30_store.record_run(topic["id"], status="running")
    last30_store.store_findings(
        run_one,
        topic["id"],
        [
            {
                "source": "hackernews",
                "source_url": "https://example.com/old",
                "source_title": "Old item",
                "engagement_score": 10,
            }
        ],
    )
    last30_store.update_run(run_one, status="completed", findings_new=1, findings_updated=0)

    run_two = last30_store.record_run(topic["id"], status="running")
    counts = last30_store.store_findings(
        run_two,
        topic["id"],
        [
            {
                "source": "hackernews",
                "source_url": "https://example.com/old",
                "source_title": "Old item",
                "engagement_score": 20,
            },
            {
                "source": "github",
                "source_url": "https://example.com/new",
                "source_title": "New item",
                "engagement_score": 30,
            },
        ],
    )
    last30_store.update_run(
        run_two,
        status="completed",
        findings_new=counts["new"],
        findings_updated=counts["updated"],
    )

    new_only = last30_store.get_findings_new_in_run(run_two)
    assert len(new_only) == 1
    assert new_only[0]["source_url"] == "https://example.com/new"
