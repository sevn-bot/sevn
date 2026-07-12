"""Bundled ``email-management`` skill tests with mock IMAP."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from sevn.config.workspace_config import parse_workspace_config
from sevn.data.bundled_skills import BUNDLED_SKILLS_ROOT
from sevn.skills.email_management import (
    EMAIL_MANAGEMENT_SKILL_ID,
    EmailAccount,
    MessageSummary,
    create_imap_client,
    dry_run_requested,
    load_accounts,
    resolve_account,
    resolve_password,
    send_smtp_message,
    summaries_to_dicts,
)

_SKILL_ROOT = BUNDLED_SKILLS_ROOT / "core" / EMAIL_MANAGEMENT_SKILL_ID
_SCRIPTS = _SKILL_ROOT / "scripts"


class FakeImapClient:
    """In-memory IMAP stub for unit tests."""

    def __init__(
        self,
        *,
        folders: list[str] | None = None,
        messages: list[MessageSummary] | None = None,
    ) -> None:
        self.folders = folders or ["INBOX", "Archive"]
        self.messages = messages or [
            MessageSummary(
                uid="42",
                subject="Hello",
                from_addr="sender@example.com",
                date="Mon, 1 Jan 2024 00:00:00 +0000",
                snippet="Preview text",
            ),
        ]

    def list_folders(self) -> list[str]:
        return list(self.folders)

    def fetch_recent(self, *, folder: str, limit: int) -> list[MessageSummary]:
        _ = folder
        if limit <= 0:
            return []
        return self.messages[-limit:]

    def search_messages(
        self,
        *,
        folder: str,
        criteria: str,
        limit: int,
    ) -> list[MessageSummary]:
        _ = folder, criteria
        if limit <= 0:
            return []
        return self.messages[:limit]


def _sample_config() -> dict[str, object]:
    return {
        "schema_version": 1,
        "skills": {
            "email_management": {
                "accounts": [
                    {
                        "id": "personal",
                        "label": "Personal",
                        "backend": "imap",
                        "host": "imap.example.com",
                        "smtp_host": "smtp.example.com",
                        "username": "me@example.com",
                        "password_env": "EMAIL_PERSONAL_PASSWORD",
                    },
                    {
                        "id": "work-api",
                        "label": "Work Gmail API",
                        "backend": "gmail_api",
                        "username": "me@company.com",
                        "password_env": "GMAIL_WORK_OAUTH_TOKEN",
                    },
                ],
            },
        },
        "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
    }


def _write_workspace(tmp_path: Path) -> None:
    (tmp_path / "sevn.json").write_text(json.dumps(_sample_config()), encoding="utf-8")
    (tmp_path / ".sevn").mkdir(parents=True, exist_ok=True)


def _run_script(
    script_name: str,
    workspace: Path,
    cli_args: list[str] | None = None,
    *,
    extra_env: dict[str, str] | None = None,
) -> tuple[int, dict[str, object]]:
    script = _SCRIPTS / script_name
    env = os.environ.copy()
    env["SEVN_WORKSPACE"] = str(workspace)
    if extra_env:
        env.update(extra_env)
    proc = subprocess.run(
        [sys.executable, str(script), *(cli_args or [])],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    payload = json.loads(proc.stdout.strip() or "{}")
    return proc.returncode, payload


def _run_script_main(
    script_name: str,
    workspace: Path,
    cli_args: list[str],
    *,
    extra_env: dict[str, str] | None = None,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[int, dict[str, object]]:
    """Run a skill script ``main()`` in-process (allows monkeypatching IMAP)."""
    if extra_env:
        for key, value in extra_env.items():
            monkeypatch.setenv(key, value)
    monkeypatch.setenv("SEVN_WORKSPACE", str(workspace))
    import importlib.util
    import io
    from contextlib import redirect_stdout

    path = _SCRIPTS / script_name
    spec = importlib.util.spec_from_file_location(f"email_mgmt_{script_name}", path)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = mod.main(cli_args)
    payload = json.loads(buf.getvalue().strip() or "{}")
    return code, payload


def test_bundled_skill_manifest_exists() -> None:
    """Core tree ships ``email-management`` manifest with explicit abortable rows."""
    skill_md = _SKILL_ROOT / "SKILL.md"
    assert skill_md.is_file()
    text = skill_md.read_text(encoding="utf-8")
    assert "email-management" in text
    assert "abortable: false" in text
    assert "list_accounts.py" in text


def test_load_accounts_from_config() -> None:
    """``load_accounts`` parses multi-account ``skills.email_management`` rows."""
    cfg = parse_workspace_config(_sample_config())
    accounts = load_accounts(cfg)
    assert len(accounts) == 2
    assert accounts[0].backend == "imap"
    assert accounts[1].backend == "gmail_api"


def test_resolve_password_env_precedence() -> None:
    """``resolve_password`` reads configured ``password_env`` values."""
    account = EmailAccount(
        id="personal",
        label="Personal",
        backend="imap",
        username="me@example.com",
        password_env="EMAIL_PERSONAL_PASSWORD",
    )
    assert resolve_password(account, env={"EMAIL_PERSONAL_PASSWORD": "secret"}) == "secret"


def test_dry_run_requested() -> None:
    """Dry-run accepts CLI flag and ``SEVN_EMAIL_DRY_RUN`` env."""
    assert dry_run_requested(cli_flag=True) is True
    assert dry_run_requested(cli_flag=False) is False


def test_summaries_to_dicts() -> None:
    """Message summaries serialise with stable keys."""
    rows = summaries_to_dicts(
        [
            MessageSummary(
                uid="1",
                subject="Subj",
                from_addr="from@example.com",
                date="Today",
                snippet="Body",
            ),
        ],
    )
    assert rows[0]["from"] == "from@example.com"


def test_list_accounts_script(tmp_path: Path) -> None:
    """``list_accounts.py`` returns configured account metadata."""
    _write_workspace(tmp_path)
    code, payload = _run_script("list_accounts.py", tmp_path)
    assert code == 0
    assert payload.get("ok") is True
    data = payload.get("data")
    assert isinstance(data, dict)
    assert data.get("count") == 2


def test_list_folders_mock_imap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``list_folders.py`` uses injected IMAP client for imap backend."""
    _write_workspace(tmp_path)
    fake = FakeImapClient(folders=["INBOX", "Sent"])

    def _factory(account: EmailAccount, password: str) -> FakeImapClient:
        _ = account, password
        return fake

    monkeypatch.setattr(
        "sevn.skills.email_management.create_imap_client",
        _factory,
    )
    code, payload = _run_script_main(
        "list_folders.py",
        tmp_path,
        ["--account", "personal"],
        extra_env={"EMAIL_PERSONAL_PASSWORD": "secret"},
        monkeypatch=monkeypatch,
    )
    assert code == 0
    data = payload.get("data")
    assert isinstance(data, dict)
    assert data.get("folders") == ["INBOX", "Sent"]


def test_fetch_recent_mock_imap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``fetch_recent.py`` returns mock message summaries."""
    _write_workspace(tmp_path)

    def _factory(account: EmailAccount, password: str) -> FakeImapClient:
        _ = account, password
        return FakeImapClient()

    monkeypatch.setattr(
        "sevn.skills.email_management.create_imap_client",
        _factory,
    )
    code, payload = _run_script_main(
        "fetch_recent.py",
        tmp_path,
        ["--account", "personal", "--limit", "5"],
        extra_env={"EMAIL_PERSONAL_PASSWORD": "secret"},
        monkeypatch=monkeypatch,
    )
    assert code == 0
    data = payload.get("data")
    assert isinstance(data, dict)
    messages = data.get("messages")
    assert isinstance(messages, list)
    assert messages[0]["subject"] == "Hello"


def test_search_mock_imap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``search.py`` returns mock matches for IMAP accounts."""
    _write_workspace(tmp_path)

    def _factory(account: EmailAccount, password: str) -> FakeImapClient:
        _ = account, password
        return FakeImapClient()

    monkeypatch.setattr(
        "sevn.skills.email_management.create_imap_client",
        _factory,
    )
    code, payload = _run_script_main(
        "search.py",
        tmp_path,
        ["--account", "personal", "--query", "invoice"],
        extra_env={"EMAIL_PERSONAL_PASSWORD": "secret"},
        monkeypatch=monkeypatch,
    )
    assert code == 0
    data = payload.get("data")
    assert isinstance(data, dict)
    assert data.get("query") == "invoice"


def test_gmail_api_backend_dry_run_plan(tmp_path: Path) -> None:
    """Gmail API accounts emit API plan JSON without live HTTP."""
    _write_workspace(tmp_path)
    code, payload = _run_script(
        "fetch_recent.py",
        tmp_path,
        ["--account", "work-api", "--dry-run"],
    )
    assert code == 0
    data = payload.get("data")
    assert isinstance(data, dict)
    assert data.get("backend") == "gmail_api"
    assert data.get("operation") == "fetch_recent"


def test_send_dry_run(tmp_path: Path) -> None:
    """``send.py`` supports dry-run SMTP plan output."""
    _write_workspace(tmp_path)
    code, payload = _run_script(
        "send.py",
        tmp_path,
        [
            "--account",
            "personal",
            "--to",
            "dest@example.com",
            "--subject",
            "Hi",
            "--body",
            "Hello",
            "--dry-run",
        ],
        extra_env={"EMAIL_PERSONAL_PASSWORD": "secret"},
    )
    assert code == 0
    data = payload.get("data")
    assert isinstance(data, dict)
    assert data.get("mode") == "dry_run"
    assert data.get("to") == "dest@example.com"


def test_send_smtp_message_dry_run_unit() -> None:
    """``send_smtp_message`` returns plan metadata without connecting."""
    account = EmailAccount(
        id="personal",
        label="Personal",
        backend="imap",
        username="me@example.com",
        smtp_host="smtp.example.com",
    )
    result = send_smtp_message(
        account,
        "pw",
        to_addr="dest@example.com",
        subject="Hi",
        body="Hello",
        dry_run=True,
    )
    assert result["mode"] == "dry_run"


def test_resolve_account_unknown() -> None:
    """``resolve_account`` rejects unknown ids."""
    account = EmailAccount(
        id="a",
        label="A",
        backend="imap",
        username="u@example.com",
    )
    with pytest.raises(ValueError, match="unknown account"):
        resolve_account([account], "missing")


def test_create_imap_client_returns_stdlib_wrapper() -> None:
    """Default IMAP factory returns a stdlib-backed client object."""
    account = EmailAccount(
        id="a",
        label="A",
        backend="imap",
        username="u@example.com",
        host="imap.example.com",
    )
    client = create_imap_client(account, "pw")
    assert hasattr(client, "list_folders")
