"""TTL cache tests for Graphify profile resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from sevn.code_understanding.graphify import (
    clear_resolve_active_profiles_cache,
    resolve_active_profiles_cached,
    resolve_profiles,
)
from sevn.code_understanding.models import GraphifyProfile, GraphifySettings


@pytest.fixture(autouse=True)
def _clear_profile_cache() -> None:
    clear_resolve_active_profiles_cache()


def test_cached_resolve_hits_on_same_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"n": 0}
    real_resolve = resolve_profiles

    def _counting_resolve(settings: GraphifySettings, root: Path) -> list[GraphifyProfile]:
        calls["n"] += 1
        return real_resolve(settings, root)

    monkeypatch.setattr(
        "sevn.code_understanding.graphify.resolve_profiles",
        _counting_resolve,
    )
    settings = GraphifySettings(enabled=True)
    resolve_active_profiles_cached(settings, tmp_path)
    resolve_active_profiles_cached(settings, tmp_path)
    assert calls["n"] == 1


def test_cached_resolve_expires_after_ttl(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"n": 0}
    real_resolve = resolve_profiles
    monotonic = {"t": 0.0}

    def _fake_monotonic() -> float:
        return monotonic["t"]

    def _counting_resolve(settings: GraphifySettings, root: Path) -> list[GraphifyProfile]:
        calls["n"] += 1
        return real_resolve(settings, root)

    monkeypatch.setattr(
        "sevn.code_understanding.graphify.resolve_profiles",
        _counting_resolve,
    )
    monkeypatch.setattr("sevn.code_understanding.graphify.time.monotonic", _fake_monotonic)
    settings = GraphifySettings(enabled=True)
    resolve_active_profiles_cached(settings, tmp_path, ttl_s=60.0)
    monotonic["t"] = 61.0
    resolve_active_profiles_cached(settings, tmp_path, ttl_s=60.0)
    assert calls["n"] == 2


def test_cached_resolve_separate_entries_per_settings_fingerprint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"n": 0}
    real_resolve = resolve_profiles

    def _counting_resolve(settings: GraphifySettings, root: Path) -> list[GraphifyProfile]:
        calls["n"] += 1
        return real_resolve(settings, root)

    monkeypatch.setattr(
        "sevn.code_understanding.graphify.resolve_profiles",
        _counting_resolve,
    )
    resolve_active_profiles_cached(GraphifySettings(enabled=True), tmp_path)
    resolve_active_profiles_cached(GraphifySettings(enabled=False), tmp_path)
    assert calls["n"] == 2


def test_cached_resolve_separate_entries_per_profile_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"n": 0}
    real_resolve = resolve_profiles
    other = tmp_path / "other"
    other.mkdir()

    def _counting_resolve(settings: GraphifySettings, root: Path) -> list[GraphifyProfile]:
        calls["n"] += 1
        return real_resolve(settings, root)

    monkeypatch.setattr(
        "sevn.code_understanding.graphify.resolve_profiles",
        _counting_resolve,
    )
    settings = GraphifySettings(enabled=True)
    resolve_active_profiles_cached(settings, tmp_path)
    resolve_active_profiles_cached(settings, other)
    assert calls["n"] == 2
