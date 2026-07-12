"""Golden routing accuracy replay (`plan/full-tracing-eval-wave-plan.md` Wave E-2)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from sevn.self_improve.eval.replay import (
    DEFAULT_INTENT_MATCH_THRESHOLD,
    golden_routing_fixture_path,
    run_golden_routing_replay,
)

if TYPE_CHECKING:
    import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _write_min_corpus(repo_root: Path, *, rows: int = 200) -> None:
    corpus = golden_routing_fixture_path(repo_root=repo_root)
    corpus.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for idx in range(rows):
        lines.append(
            json.dumps(
                {
                    "id": f"gr-{idx:04d}",
                    "message": f"[en] schedule task {idx} for tomorrow",
                    "locale": "en",
                    "labels": {
                        "intent": "NEW_REQUEST",
                        "complexity": "B",
                        "disregard": False,
                        "tools": [],
                        "skills": [],
                        "mcp_servers_required": [],
                    },
                },
            ),
        )
    corpus.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_golden_routing_accuracy_passes_with_label_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEVN_TRIAGER_STUB", "1")
    result = run_golden_routing_replay(
        repo_root=_REPO_ROOT,
        sample_size=20,
        intent_threshold=DEFAULT_INTENT_MATCH_THRESHOLD,
    )
    assert result.segment.status == "passed"
    assert result.metrics.intent_match_rate >= DEFAULT_INTENT_MATCH_THRESHOLD
    assert result.metrics.sampled == 20


def test_golden_routing_accuracy_fails_on_wrong_stub_intent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sevn.self_improve.eval.replay as replay_mod

    _write_min_corpus(tmp_path, rows=200)
    monkeypatch.setenv("SEVN_TRIAGER_STUB", "1")

    def _wrong_stub(labels: dict[str, object]) -> str:
        payload = replay_mod._labels_to_triage_payload(labels)
        payload["first_message"] = "Replay stub reply."
        payload["intent"] = "GREETING"
        return json.dumps(payload)

    monkeypatch.setattr(replay_mod, "_labels_to_stub_json", _wrong_stub)
    result = run_golden_routing_replay(
        repo_root=tmp_path,
        sample_size=10,
        intent_threshold=DEFAULT_INTENT_MATCH_THRESHOLD,
    )
    assert result.segment.status == "failed"
    assert result.metrics.intent_match_rate < DEFAULT_INTENT_MATCH_THRESHOLD
