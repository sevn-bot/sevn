from __future__ import annotations

from sevn.security.sandbox_sweeper import SandboxLabeledContainer, sweep_orphan_labels


class _Registry:
    def __init__(
        self,
        *,
        live_run_ids: frozenset[str],
        missing_since: dict[str, float],
    ) -> None:
        self._live = live_run_ids
        self._since = dict(missing_since)

    def is_live(self, run_id: str) -> bool:
        return run_id in self._live

    def missing_since_unix_s(self, run_id: str) -> float | None:
        if self.is_live(run_id):
            return None
        return self._since.get(run_id)


def test_sweep_selects_ttl_orphans_only() -> None:
    containers = [
        SandboxLabeledContainer(container_id="c-hot", labels={"sevn.run_id": "warm"}),
        SandboxLabeledContainer(container_id="c-old", labels={"sevn.run_id": "cold"}),
    ]
    registry = _Registry(live_run_ids=frozenset({"warm"}), missing_since={"cold": 0.0})
    doomed = sweep_orphan_labels(
        containers=containers,
        now_unix_s=10_000.0,
        sandbox_max_lifetime_s=3600,
        registry=registry,
    )
    assert doomed == ["c-old"]
