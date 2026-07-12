"""Bundled ``yt-dlp`` skill subprocess tests."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from sevn.media.yt_dlp_skill import (
    EGRESS_DOWNLOAD_DOMAINS,
    build_download_argv,
    build_metadata_argv,
    host_allowed,
    validate_media_url,
)

_SKILL_ROOT = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "sevn"
    / "data"
    / "bundled_skills"
    / "core"
    / "yt-dlp"
)
_DOWNLOAD_SCRIPT = _SKILL_ROOT / "scripts" / "download.py"
_METADATA_SCRIPT = _SKILL_ROOT / "scripts" / "metadata.py"


def _install_fake_yt_dlp(tmp_path: Path) -> Path:
    """Write a stub ``yt-dlp`` executable under ``tmp_path/bin`` for subprocess tests."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    yt_dlp = bin_dir / "yt-dlp"
    yt_dlp.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        "if '--dump-json' in sys.argv:\n"
        "    print(json.dumps({\n"
        '        "id": "abc",\n'
        '        "title": "Test Video",\n'
        '        "uploader": "tester",\n'
        '        "duration": 42,\n'
        '        "view_count": 7,\n'
        '        "upload_date": "20260101",\n'
        '        "webpage_url": "https://www.youtube.com/watch?v=abc",\n'
        '        "description": "hello",\n'
        "    }))\n"
        "else:\n"
        '    sys.stdout.write("download complete\\n")\n'
        "raise SystemExit(0)\n",
        encoding="utf-8",
    )
    yt_dlp.chmod(0o755)
    return bin_dir


def _run_script(
    script: Path,
    workspace: Path,
    cli_args: list[str],
    *,
    path_prefix: Path | None = None,
    extra_env: dict[str, str] | None = None,
) -> tuple[int, dict[str, object]]:
    """Run one yt-dlp skill script and parse its JSON stdout envelope."""
    env = os.environ.copy()
    env["SEVN_WORKSPACE"] = str(workspace)
    env.pop("SEVN_YT_DLP_DRY_RUN", None)
    if path_prefix is not None:
        env["PATH"] = f"{path_prefix}{os.pathsep}{env.get('PATH', '')}"
    if extra_env:
        env.update(extra_env)
    proc = subprocess.run(
        [sys.executable, str(script), *cli_args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    payload = json.loads(proc.stdout.strip() or "{}")
    return proc.returncode, payload


def test_host_allowed_matches_youtube_subdomains() -> None:
    """``host_allowed`` accepts common YouTube hostnames."""
    assert host_allowed("www.youtube.com")
    assert host_allowed("m.youtube.com")
    assert host_allowed("youtu.be")


def test_validate_media_url_rejects_unknown_host() -> None:
    """``validate_media_url`` rejects hosts outside the egress allowlist."""
    with pytest.raises(ValueError, match="egress allowlist"):
        validate_media_url("https://evil.example/video")


def test_build_metadata_argv_is_allowlisted() -> None:
    """Metadata argv uses fixed flags only."""
    argv = build_metadata_argv("https://www.youtube.com/watch?v=abc")
    assert argv[:4] == ["yt-dlp", "--no-playlist", "--skip-download", "--dump-json"]


def test_build_download_argv_audio_only() -> None:
    """Download argv includes audio extraction flags when requested."""
    out_dir = Path("/tmp/out")
    argv = build_download_argv(
        "https://www.youtube.com/watch?v=abc",
        out_dir,
        audio_only=True,
        audio_format="mp3",
    )
    assert "-x" in argv
    assert "--audio-format" in argv
    assert argv[argv.index("--audio-format") + 1] == "mp3"


def test_metadata_dry_run_returns_argv_plan(tmp_path: Path) -> None:
    """``metadata.py --dry-run`` returns argv plan without invoking yt-dlp."""
    code, payload = _run_script(
        _METADATA_SCRIPT,
        tmp_path,
        ["--dry-run", "--url", "https://www.youtube.com/watch?v=abc"],
    )
    assert code == 0
    assert payload.get("ok") is True
    data = payload.get("data")
    assert isinstance(data, dict)
    assert data.get("mode") == "dry_run"
    argv = data.get("argv")
    assert isinstance(argv, list)
    assert argv == build_metadata_argv("https://www.youtube.com/watch?v=abc")


def test_download_rejects_disallowed_url(tmp_path: Path) -> None:
    """``download.py`` rejects URLs outside the egress allowlist."""
    code, payload = _run_script(
        _DOWNLOAD_SCRIPT,
        tmp_path,
        ["--url", "https://not-allowed.example/v", "--dry-run"],
    )
    assert code == 1
    assert payload.get("ok") is False
    assert payload.get("code") == "VALIDATION_ERROR"


def test_metadata_live_with_fake_yt_dlp(tmp_path: Path) -> None:
    """Live metadata mode runs stub ``yt-dlp`` when present on PATH."""
    bin_dir = _install_fake_yt_dlp(tmp_path)
    code, payload = _run_script(
        _METADATA_SCRIPT,
        tmp_path,
        ["--url", "https://www.youtube.com/watch?v=abc"],
        path_prefix=bin_dir,
    )
    assert code == 0
    assert payload.get("ok") is True
    data = payload.get("data")
    assert isinstance(data, dict)
    metadata = data.get("metadata")
    assert isinstance(metadata, dict)
    assert metadata.get("title") == "Test Video"


def test_download_live_with_fake_yt_dlp(tmp_path: Path) -> None:
    """Live download mode runs stub ``yt-dlp`` when present on PATH."""
    bin_dir = _install_fake_yt_dlp(tmp_path)
    code, payload = _run_script(
        _DOWNLOAD_SCRIPT,
        tmp_path,
        [
            "--url",
            "https://youtu.be/abc",
            "--out",
            "media",
            "--audio-only",
            "--audio-format",
            "mp3",
        ],
        path_prefix=bin_dir,
    )
    assert code == 0
    assert payload.get("ok") is True
    data = payload.get("data")
    assert isinstance(data, dict)
    assert data.get("mode") == "live"
    out_rel = data.get("out_dir")
    assert isinstance(out_rel, str)
    assert (tmp_path / out_rel).is_dir()


def test_egress_domains_match_skill_frontmatter_count() -> None:
    """Python allowlist stays aligned with bundled SKILL.md ``egress:`` rows."""
    skill_md = (_SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    frontmatter = skill_md.split("---", 2)[1]
    egress_block = frontmatter.split("egress:", 1)[1].split("scripts:", 1)[0]
    yaml_domains = [
        line.strip().lstrip("- ").strip()
        for line in egress_block.splitlines()
        if line.strip().startswith("- ")
    ]
    assert tuple(yaml_domains) == EGRESS_DOWNLOAD_DOMAINS
