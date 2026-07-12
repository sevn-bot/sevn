"""Bundled ``scheduling`` skill script subprocess tests."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from sevn.skills.manager import SkillsManager, _canonicalise_script_name
from sevn.triggers.cron import format_next_fire_at_iso

_SKILL_ROOT = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "sevn"
    / "data"
    / "bundled_skills"
    / "core"
    / "scheduling"
)
_SCRIPTS = _SKILL_ROOT / "scripts"


@pytest.fixture(autouse=True)
def _reset_skill_singletons() -> None:
    SkillsManager.reset_singletons_for_tests()
    yield
    SkillsManager.reset_singletons_for_tests()


@pytest.fixture
def scheduling_workspace(tmp_path: Path) -> Path:
    """Empty migrated workspace for scheduling scripts."""
    dot_sevn = tmp_path / ".sevn"
    dot_sevn.mkdir(parents=True)
    return tmp_path


def _run_script(
    script_name: str,
    workspace: Path,
    cli_args: list[str] | None = None,
) -> dict[str, object]:
    script = _SCRIPTS / script_name
    env = os.environ.copy()
    env["SEVN_WORKSPACE"] = str(workspace)
    proc = subprocess.run(
        [sys.executable, str(script), *(cli_args or [])],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    payload = json.loads(proc.stdout.strip())
    assert payload.get("ok") is True
    return payload


def test_format_next_fire_at_iso_june_2026() -> None:
    """Regression: ns→date must not be mis-read by the model (session 2026-06-02)."""
    assert format_next_fire_at_iso(1780455600000000000).startswith("2026-06-03")


def test_scheduling_script_stem_and_cron_status_alias(tmp_path: Path) -> None:
    """Bare stems and ``cron_status`` resolve to declared manifest paths."""
    man = SkillsManager.shared(tmp_path)
    rec = man.get_record("scheduling")
    assert _canonicalise_script_name(rec, "cron_list") == "scripts/cron_list.py"
    assert _canonicalise_script_name(rec, "cron_status") == "scripts/cron_list.py"


def test_cron_list_envelope_includes_next_fire_at_iso(scheduling_workspace: Path) -> None:
    """``cron_list`` returns ISO ``next_fire_at`` alongside ``next_fire_at_ns``."""
    job_id = "iso_field_job"
    _run_script(
        "cron_add.py",
        scheduling_workspace,
        [
            "--job-id",
            job_id,
            "--cron-expr",
            "0 9 * * *",
            "--payload-template",
            "check iso",
        ],
    )
    list_payload = _run_script("cron_list.py", scheduling_workspace)
    list_data = list_payload["data"]
    assert isinstance(list_data, dict)
    jobs = list_data.get("jobs")
    assert isinstance(jobs, list)
    row = next(j for j in jobs if str(j["job_id"]) == job_id)
    assert isinstance(row.get("next_fire_at_ns"), int)
    next_fire = row.get("next_fire_at")
    assert isinstance(next_fire, str)
    assert "T" in next_fire
    assert next_fire.startswith(format_next_fire_at_iso(int(row["next_fire_at_ns"]))[:10])


def test_cron_crud_round_trip(scheduling_workspace: Path) -> None:
    """Add, list, edit, and delete a cron job via bundled scripts."""
    job_id = "wave11_test_job"
    add_payload = _run_script(
        "cron_add.py",
        scheduling_workspace,
        [
            "--job-id",
            job_id,
            "--cron-expr",
            "0 9 * * *",
            "--payload-template",
            "Morning standup",
        ],
    )
    add_data = add_payload["data"]
    assert isinstance(add_data, dict)
    job = add_data.get("job")
    assert isinstance(job, dict)
    assert job["job_id"] == job_id
    assert job["cron_expr"] == "0 9 * * *"

    list_payload = _run_script("cron_list.py", scheduling_workspace)
    list_data = list_payload["data"]
    assert isinstance(list_data, dict)
    jobs = list_data.get("jobs")
    assert isinstance(jobs, list)
    assert any(str(row["job_id"]) == job_id for row in jobs)

    edit_payload = _run_script(
        "cron_edit.py",
        scheduling_workspace,
        [
            "--job-id",
            job_id,
            "--payload-template",
            "Updated standup",
            "--disabled",
        ],
    )
    edit_data = edit_payload["data"]
    assert isinstance(edit_data, dict)
    edited = edit_data.get("job")
    assert isinstance(edited, dict)
    assert edited["payload_template"] == "Updated standup"
    assert edited["enabled"] is False

    delete_payload = _run_script(
        "cron_delete.py",
        scheduling_workspace,
        ["--job-id", job_id],
    )
    delete_data = delete_payload["data"]
    assert isinstance(delete_data, dict)
    assert delete_data.get("deleted") is True

    final_list = _run_script("cron_list.py", scheduling_workspace)
    final_data = final_list["data"]
    assert isinstance(final_data, dict)
    remaining = final_data.get("jobs")
    assert isinstance(remaining, list)
    assert not any(str(row["job_id"]) == job_id for row in remaining)


def test_reminder_script_creates_job(scheduling_workspace: Path) -> None:
    """Reminder script inserts a future one-shot row."""
    reminder_id = "reminder_wave11"
    payload = _run_script(
        "reminder.py",
        scheduling_workspace,
        [
            "--job-id",
            reminder_id,
            "--at",
            "2030-06-15T14:30:00",
            "--prompt",
            "Take a break",
            "--timezone",
            "UTC",
        ],
    )
    data = payload["data"]
    assert isinstance(data, dict)
    assert data.get("reminder") is True
    job = data.get("job")
    assert isinstance(job, dict)
    assert job["job_id"] == reminder_id
    assert job["payload_template"] == "Take a break"
