"""Operator PATH augmentation for gateway subprocesses."""

from __future__ import annotations

from pathlib import Path

from sevn.runtime.operator_path import (
    augment_macos_dyld_library_path,
    augment_operator_path,
    operator_path_prefixes,
)


def test_operator_path_prefixes_includes_local_bin(tmp_path: Path) -> None:
    local_bin = tmp_path / ".local" / "bin"
    local_bin.mkdir(parents=True)
    prefixes = operator_path_prefixes(home=tmp_path)
    assert local_bin in prefixes


def test_augment_operator_path_prepends_missing_dirs(tmp_path: Path) -> None:
    local_bin = tmp_path / ".local" / "bin"
    local_bin.mkdir(parents=True)
    merged = augment_operator_path({"PATH": "/usr/bin"}, home=tmp_path)
    parts = merged["PATH"].split(":")
    assert str(local_bin) == parts[0]
    assert "/usr/bin" in parts


def test_augment_operator_path_does_not_duplicate_existing_entry(tmp_path: Path) -> None:
    local_bin = tmp_path / ".local" / "bin"
    local_bin.mkdir(parents=True)
    entry = str(local_bin)
    merged = augment_operator_path({"PATH": entry}, home=tmp_path)
    assert merged["PATH"].count(entry) == 1


def test_augment_operator_path_seeds_system_dirs_when_path_absent(tmp_path: Path) -> None:
    local_bin = tmp_path / ".local" / "bin"
    local_bin.mkdir(parents=True)
    merged = augment_operator_path({"SEVN_PROXY_URL": "http://127.0.0.1:8787"}, home=tmp_path)
    parts = merged["PATH"].split(":")
    assert str(local_bin) == parts[0]
    assert "/usr/bin" in parts
    assert "/bin" in parts


def test_dyld_augment_noop_off_macos() -> None:
    assert augment_macos_dyld_library_path({}, system="Linux") == {}
    assert augment_macos_dyld_library_path({"X": "1"}, system="Linux") == {"X": "1"}


def test_dyld_augment_prepends_homebrew_lib(tmp_path: Path) -> None:
    out = augment_macos_dyld_library_path(
        {}, system="Darwin", home=tmp_path, lib_dirs=["/opt/homebrew/lib"]
    )
    parts = out["DYLD_FALLBACK_LIBRARY_PATH"].split(":")
    assert parts[0] == "/opt/homebrew/lib"
    # macOS defaults appended so system libs are not shadowed
    assert str(tmp_path / "lib") in parts
    assert "/usr/lib" in parts


def test_dyld_augment_preserves_existing_and_dedupes(tmp_path: Path) -> None:
    out = augment_macos_dyld_library_path(
        {"DYLD_FALLBACK_LIBRARY_PATH": "/custom/lib"},
        system="Darwin",
        home=tmp_path,
        lib_dirs=["/opt/homebrew/lib"],
    )
    parts = out["DYLD_FALLBACK_LIBRARY_PATH"].split(":")
    assert parts[:2] == ["/opt/homebrew/lib", "/custom/lib"]
    assert parts.count("/opt/homebrew/lib") == 1


def test_dyld_augment_noop_when_already_present(tmp_path: Path) -> None:
    env = {"DYLD_FALLBACK_LIBRARY_PATH": "/opt/homebrew/lib:/usr/lib"}
    out = augment_macos_dyld_library_path(
        env, system="Darwin", home=tmp_path, lib_dirs=["/opt/homebrew/lib"]
    )
    # brew dir already listed -> unchanged
    assert out["DYLD_FALLBACK_LIBRARY_PATH"] == env["DYLD_FALLBACK_LIBRARY_PATH"]


def test_dyld_augment_noop_when_no_brew_dir(tmp_path: Path) -> None:
    out = augment_macos_dyld_library_path({}, system="Darwin", home=tmp_path, lib_dirs=[])
    assert "DYLD_FALLBACK_LIBRARY_PATH" not in out
