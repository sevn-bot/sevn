"""Multi-account IMAP/API helpers for the bundled ``email-management`` skill.

Module: sevn.skills.email_management
Depends: dataclasses, email, imaplib, smtplib, ssl

Exports:
    EmailAccount — one configured mailbox account (no secret material).
    MessageSummary — redacted message header row for agent consumption.
    ImapClientProtocol — minimal IMAP surface for tests and backends.
    StdlibImapClient — stdlib ``imaplib`` IMAP client.
    dry_run_requested — CLI/env dry-run selector.
    load_accounts — parse ``skills.email_management.accounts`` from workspace config.
    account_public_dict — JSON-safe account metadata without credentials.
    resolve_account — select one account by id.
    resolve_password — read password/token from env for an account.
    create_imap_client — factory for stdlib or injected IMAP clients.
    list_imap_folders — IMAP LIST for one account.
    fetch_recent_messages — recent message summaries from a folder.
    search_imap_messages — IMAP SEARCH + FETCH summaries.
    send_smtp_message — SMTP send with dry-run plan support.
    gmail_api_plan — argv/plan envelope for Gmail API backend dry-runs.
    summaries_to_dicts — convert summaries to JSON dict rows.
"""

from __future__ import annotations

import contextlib
import email
import imaplib
import os
import smtplib
import ssl
from dataclasses import dataclass
from email import header as email_header
from email.message import EmailMessage
from typing import Final, Literal, Protocol

from sevn.config.workspace_config import WorkspaceConfig

EMAIL_MANAGEMENT_SKILL_ID: Final[str] = "email-management"
_DRY_RUN_ENV: Final[str] = "SEVN_EMAIL_DRY_RUN"
_DEFAULT_IMAP_PORT: Final[int] = 993
_DEFAULT_SMTP_PORT: Final[int] = 587
_SNIPPET_CHARS: Final[int] = 500

BackendKind = Literal["imap", "gmail_api"]


@dataclass(frozen=True)
class EmailAccount:
    """One configured mailbox account (credentials resolved separately).

    Attributes:
        id (str): Stable account id referenced by skill scripts.
        label (str): Operator-facing display name.
        backend (BackendKind): ``imap`` or ``gmail_api``.
        username (str): Mailbox login or API identity.
        host (str | None): IMAP host when ``backend`` is ``imap``.
        port (int): IMAP port (default 993).
        use_ssl (bool): Use IMAP SSL/TLS.
        smtp_host (str | None): SMTP host for outbound mail.
        smtp_port (int): SMTP port (default 587).
        password_env (str | None): Environment variable holding password/token.
    """

    id: str
    label: str
    backend: BackendKind
    username: str
    host: str | None = None
    port: int = _DEFAULT_IMAP_PORT
    use_ssl: bool = True
    smtp_host: str | None = None
    smtp_port: int = _DEFAULT_SMTP_PORT
    password_env: str | None = None


@dataclass(frozen=True)
class MessageSummary:
    """Redacted message header row for agent-facing JSON payloads.

    Attributes:
        uid (str): IMAP UID string.
        subject (str): Decoded Subject header.
        from_addr (str): Decoded From header.
        date (str): Decoded Date header.
        snippet (str): Short body preview (may be empty).
    """

    uid: str
    subject: str
    from_addr: str
    date: str
    snippet: str


class ImapClientProtocol(Protocol):
    """Minimal IMAP surface used by email-management scripts."""

    def list_folders(self) -> list[str]:
        """Return mailbox folder names.

        Returns:
            list[str]: Folder names.

        Examples:
            >>> import inspect
            >>> inspect.isfunction(ImapClientProtocol.list_folders)
            True
        """
        ...

    def fetch_recent(self, *, folder: str, limit: int) -> list[MessageSummary]:
        """Return recent messages from ``folder``.

        Args:
            folder (str): IMAP mailbox name.
            limit (int): Maximum number of messages.

        Returns:
            list[MessageSummary]: Recent message summaries.

        Examples:
            >>> import inspect
            >>> inspect.isfunction(ImapClientProtocol.fetch_recent)
            True
        """
        ...

    def search_messages(
        self,
        *,
        folder: str,
        criteria: str,
        limit: int,
    ) -> list[MessageSummary]:
        """Return messages matching ``criteria`` in ``folder``.

        Args:
            folder (str): IMAP mailbox name.
            criteria (str): IMAP SEARCH criteria string.
            limit (int): Maximum number of matches.

        Returns:
            list[MessageSummary]: Matching message summaries.

        Examples:
            >>> import inspect
            >>> inspect.isfunction(ImapClientProtocol.search_messages)
            True
        """
        ...


class StdlibImapClient:
    """IMAP client backed by stdlib ``imaplib``."""

    def __init__(self, account: EmailAccount, password: str) -> None:
        """Store account credentials for lazy IMAP connection.

        Args:
            account (EmailAccount): Target mailbox account.
            password (str): Resolved password or app token.

        Examples:
            >>> import inspect
            >>> inspect.isfunction(StdlibImapClient.__init__)
            True
        """
        self._account = account
        self._password = password
        self._conn: imaplib.IMAP4 | imaplib.IMAP4_SSL | None = None

    def _connect(self) -> imaplib.IMAP4 | imaplib.IMAP4_SSL:
        """Open and authenticate the IMAP session when not already connected.

        Returns:
            imaplib.IMAP4 | imaplib.IMAP4_SSL: Authenticated connection.

        Examples:
            >>> import inspect
            >>> inspect.isfunction(StdlibImapClient._connect)
            True
        """
        if self._conn is not None:
            return self._conn
        host = self._account.host or ""
        if not host:
            msg = f"email-management: account {self._account.id!r} missing IMAP host"
            raise ValueError(msg)
        if self._account.use_ssl:
            self._conn = imaplib.IMAP4_SSL(host, self._account.port)
        else:
            self._conn = imaplib.IMAP4(host, self._account.port)
        self._conn.login(self._account.username, self._password)
        return self._conn

    def list_folders(self) -> list[str]:
        """Return sorted unique folder names from the IMAP LIST response.

        Returns:
            list[str]: Folder names.

        Examples:
            >>> import inspect
            >>> inspect.isfunction(StdlibImapClient.list_folders)
            True
        """
        conn = self._connect()
        status, rows = conn.list()
        if status != "OK" or not rows:
            return []
        folders: list[str] = []
        for row in rows:
            if not isinstance(row, bytes):
                continue
            decoded = row.decode("utf-8", errors="replace")
            parts = decoded.rsplit('"', 2)
            if len(parts) >= 2:
                folders.append(parts[-2])
            else:
                folders.append(decoded.strip())
        return sorted(set(folders))

    def fetch_recent(self, *, folder: str, limit: int) -> list[MessageSummary]:
        """Return the most recent ``limit`` messages from ``folder``.

        Args:
            folder (str): IMAP mailbox name.
            limit (int): Maximum number of messages.

        Returns:
            list[MessageSummary]: Recent message summaries.

        Examples:
            >>> import inspect
            >>> inspect.isfunction(StdlibImapClient.fetch_recent)
            True
        """
        conn = self._connect()
        conn.select(folder, readonly=True)
        status, data = conn.uid("search", "", "ALL")
        if status != "OK" or not data or not data[0]:
            return []
        uids = data[0].split()
        selected = uids[-limit:] if limit > 0 else uids
        return self._fetch_uids(conn, selected)

    def search_messages(
        self,
        *,
        folder: str,
        criteria: str,
        limit: int,
    ) -> list[MessageSummary]:
        """Return up to ``limit`` messages matching ``criteria`` in ``folder``.

        Args:
            folder (str): IMAP mailbox name.
            criteria (str): IMAP SEARCH criteria string.
            limit (int): Maximum number of matches.

        Returns:
            list[MessageSummary]: Matching message summaries.

        Examples:
            >>> import inspect
            >>> inspect.isfunction(StdlibImapClient.search_messages)
            True
        """
        conn = self._connect()
        conn.select(folder, readonly=True)
        query = criteria.strip() or "ALL"
        status, data = conn.uid("search", "", query)
        if status != "OK" or not data or not data[0]:
            return []
        uids = data[0].split()
        selected = uids[-limit:] if limit > 0 else uids
        return self._fetch_uids(conn, selected)

    def _fetch_uids(
        self,
        conn: imaplib.IMAP4 | imaplib.IMAP4_SSL,
        uids: list[bytes],
    ) -> list[MessageSummary]:
        """Fetch header fields and body snippets for ``uids``.

        Args:
            conn (imaplib.IMAP4 | imaplib.IMAP4_SSL): Active IMAP connection.
            uids (list[bytes]): UID bytes to fetch.

        Returns:
            list[MessageSummary]: Parsed message summaries.

        Examples:
            >>> import inspect
            >>> inspect.isfunction(StdlibImapClient._fetch_uids)
            True
        """
        summaries: list[MessageSummary] = []
        for uid in uids:
            status, fetched = conn.uid(
                "fetch",
                uid.decode("ascii", errors="replace"),
                "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)] BODY.PEEK[TEXT]<0.500>)",
            )
            if status != "OK" or not fetched:
                continue
            header_bytes = b""
            snippet = ""
            for item in fetched:
                if not isinstance(item, tuple) or len(item) < 2:
                    continue
                payload = item[1]
                if not isinstance(payload, bytes):
                    continue
                marker = item[0]
                if isinstance(marker, bytes) and b"HEADER" in marker:
                    header_bytes = payload
                elif isinstance(marker, bytes) and b"TEXT" in marker:
                    snippet = payload.decode("utf-8", errors="replace")[:_SNIPPET_CHARS]
            if not header_bytes:
                continue
            msg = email.message_from_bytes(header_bytes)
            summaries.append(
                MessageSummary(
                    uid=uid.decode("ascii", errors="replace"),
                    subject=_decode_header(msg.get("Subject", "")),
                    from_addr=_decode_header(msg.get("From", "")),
                    date=_decode_header(msg.get("Date", "")),
                    snippet=snippet.strip(),
                ),
            )
        return summaries

    def close(self) -> None:
        """Logout and release the underlying IMAP connection.

        Examples:
            >>> import inspect
            >>> inspect.isfunction(StdlibImapClient.close)
            True
        """
        if self._conn is not None:
            with contextlib.suppress(Exception):
                self._conn.logout()
            self._conn = None


def _decode_header(value: str | email_header.Header) -> str:
    """Decode an RFC 2047 email header value to plain text.

    Args:
        value (str | email.header.Header): Raw header value.

    Returns:
        str: Decoded plain-text header.

    Examples:
        >>> _decode_header("Plain subject")
        'Plain subject'
    """
    if not value:
        return ""
    if isinstance(value, str):
        return value.strip()
    decoded = email_header.decode_header(str(value))
    parts: list[str] = []
    for fragment, charset in decoded:
        if isinstance(fragment, bytes):
            parts.append(fragment.decode(charset or "utf-8", errors="replace"))
        else:
            parts.append(fragment)
    return " ".join(parts).strip()


def dry_run_requested(*, cli_flag: bool) -> bool:
    """Return True when dry-run mode is selected via CLI or environment.

    Args:
        cli_flag (bool): Whether ``--dry-run`` was passed on the CLI.

    Returns:
        bool: True when scripts should emit plan JSON only.

    Examples:
        >>> dry_run_requested(cli_flag=True)
        True
    """
    if cli_flag:
        return True
    return os.environ.get(_DRY_RUN_ENV, "").strip().lower() in {"1", "true", "yes"}


def load_accounts(cfg: WorkspaceConfig | None) -> list[EmailAccount]:
    """Parse configured mailbox accounts from ``skills.email_management``.

    Args:
        cfg (WorkspaceConfig | None): Parsed workspace config.

    Returns:
        list[EmailAccount]: Normalised account rows (may be empty).

    Examples:
        >>> load_accounts(None)
        []
    """
    if cfg is None or not isinstance(cfg.skills, dict):
        return []
    section = cfg.skills.get("email_management")
    if not isinstance(section, dict):
        return []
    raw_accounts = section.get("accounts")
    if not isinstance(raw_accounts, list):
        return []
    accounts: list[EmailAccount] = []
    for row in raw_accounts:
        if not isinstance(row, dict):
            continue
        account_id = str(row.get("id", "")).strip()
        username = str(row.get("username", "")).strip()
        if not account_id or not username:
            continue
        backend_raw = str(row.get("backend", "imap")).strip().lower()
        backend: BackendKind = "gmail_api" if backend_raw == "gmail_api" else "imap"
        label = str(row.get("label", account_id)).strip() or account_id
        host_raw = row.get("host")
        host = str(host_raw).strip() if isinstance(host_raw, str) and host_raw.strip() else None
        smtp_host_raw = row.get("smtp_host")
        smtp_host = (
            str(smtp_host_raw).strip()
            if isinstance(smtp_host_raw, str) and smtp_host_raw.strip()
            else None
        )
        password_env_raw = row.get("password_env")
        password_env = (
            str(password_env_raw).strip()
            if isinstance(password_env_raw, str) and password_env_raw.strip()
            else None
        )
        port = int(row.get("port", _DEFAULT_IMAP_PORT))
        smtp_port = int(row.get("smtp_port", _DEFAULT_SMTP_PORT))
        use_ssl = bool(row.get("use_ssl", True))
        accounts.append(
            EmailAccount(
                id=account_id,
                label=label,
                backend=backend,
                username=username,
                host=host,
                port=port,
                use_ssl=use_ssl,
                smtp_host=smtp_host,
                smtp_port=smtp_port,
                password_env=password_env,
            ),
        )
    return accounts


def account_public_dict(account: EmailAccount) -> dict[str, object]:
    """Return JSON-safe account metadata without secret fields.

    Args:
        account (EmailAccount): Configured mailbox account.

    Returns:
        dict[str, object]: Public account descriptor.

    Examples:
        >>> account_public_dict(
        ...     EmailAccount(
        ...         id="personal",
        ...         label="Personal",
        ...         backend="imap",
        ...         username="me@example.com",
        ...         host="imap.example.com",
        ...     ),
        ... )["backend"]
        'imap'
    """
    return {
        "id": account.id,
        "label": account.label,
        "backend": account.backend,
        "username": account.username,
        "host": account.host,
        "port": account.port,
        "use_ssl": account.use_ssl,
        "smtp_host": account.smtp_host,
        "smtp_port": account.smtp_port,
        "password_env": account.password_env,
    }


def resolve_account(accounts: list[EmailAccount], account_id: str) -> EmailAccount:
    """Return the account matching ``account_id``.

    Args:
        accounts (list[EmailAccount]): Loaded account list.
        account_id (str): Requested account id.

    Returns:
        EmailAccount: Matching account row.

    Raises:
        ValueError: When no account matches.

    Examples:
        >>> acct = EmailAccount(
        ...     id="a",
        ...     label="A",
        ...     backend="imap",
        ...     username="u@example.com",
        ... )
        >>> resolve_account([acct], "a").id
        'a'
    """
    needle = account_id.strip()
    for account in accounts:
        if account.id == needle:
            return account
    msg = f"email-management: unknown account id {account_id!r}"
    raise ValueError(msg)


def resolve_password(
    account: EmailAccount,
    *,
    env: dict[str, str] | None = None,
) -> str:
    """Resolve the password or OAuth token for ``account`` from environment.

    Precedence: explicit ``password_env`` → ``SEVN_EMAIL_<ID>_PASSWORD`` (uppercase id).

    Args:
        account (EmailAccount): Configured mailbox account.
        env (dict[str, str] | None, optional): Environment mapping; defaults to ``os.environ``.

    Returns:
        str: Secret material for IMAP/SMTP/API auth.

    Raises:
        ValueError: When no credential env var is configured or set.

    Examples:
        >>> acct = EmailAccount(
        ...     id="personal",
        ...     label="P",
        ...     backend="imap",
        ...     username="u@example.com",
        ...     password_env="EMAIL_PERSONAL_PASSWORD",
        ... )
        >>> resolve_password(acct, env={"EMAIL_PERSONAL_PASSWORD": "secret"})
        'secret'
    """
    mapping = env if env is not None else os.environ
    candidates: list[str] = []
    if account.password_env:
        candidates.append(account.password_env)
    candidates.append(f"SEVN_EMAIL_{account.id.upper().replace('-', '_')}_PASSWORD")
    for key in candidates:
        value = mapping.get(key, "").strip()
        if value:
            return value
    msg = (
        f"email-management: missing credential for account {account.id!r}; "
        f"set one of {candidates!r}"
    )
    raise ValueError(msg)


def create_imap_client(account: EmailAccount, password: str) -> ImapClientProtocol:
    """Create an IMAP client for ``account`` (stdlib by default).

    Args:
        account (EmailAccount): Target mailbox account.
        password (str): Resolved password or app token.

    Returns:
        ImapClientProtocol: Connected-capable IMAP client.

    Examples:
        >>> client = create_imap_client(
        ...     EmailAccount(
        ...         id="a",
        ...         label="A",
        ...         backend="imap",
        ...         username="u@example.com",
        ...         host="imap.example.com",
        ...     ),
        ...     "pw",
        ... )
        >>> hasattr(client, "list_folders")
        True
    """
    return StdlibImapClient(account, password)


def list_imap_folders(account: EmailAccount, password: str) -> list[str]:
    """Return IMAP folder names for ``account``.

    Args:
        account (EmailAccount): Target mailbox account.
        password (str): Resolved password or app token.

    Returns:
        list[str]: Folder names reported by the server.

    Examples:
        >>> isinstance(list_imap_folders.__name__, str)
        True
    """
    client = create_imap_client(account, password)
    try:
        return client.list_folders()
    finally:
        if isinstance(client, StdlibImapClient):
            client.close()


def fetch_recent_messages(
    account: EmailAccount,
    password: str,
    *,
    folder: str,
    limit: int,
) -> list[MessageSummary]:
    """Fetch recent message summaries from ``folder``.

    Args:
        account (EmailAccount): Target mailbox account.
        password (str): Resolved password or app token.
        folder (str): IMAP mailbox name (for example ``INBOX``).
        limit (int): Maximum number of messages to return.

    Returns:
        list[MessageSummary]: Recent messages oldest-to-newest within the slice.

    Examples:
        >>> isinstance(fetch_recent_messages.__name__, str)
        True
    """
    client = create_imap_client(account, password)
    try:
        return client.fetch_recent(folder=folder, limit=limit)
    finally:
        if isinstance(client, StdlibImapClient):
            client.close()


def search_imap_messages(
    account: EmailAccount,
    password: str,
    *,
    folder: str,
    query: str,
    limit: int,
) -> list[MessageSummary]:
    """Search ``folder`` with an IMAP criteria string derived from ``query``.

    Args:
        account (EmailAccount): Target mailbox account.
        password (str): Resolved password or app token.
        folder (str): IMAP mailbox name.
        query (str): Free-text query mapped to ``TEXT`` criteria when non-empty.
        limit (int): Maximum number of matches to return.

    Returns:
        list[MessageSummary]: Matching message summaries.

    Examples:
        >>> isinstance(search_imap_messages.__name__, str)
        True
    """
    criteria = "ALL" if not query.strip() else f'TEXT "{query.strip()}"'
    client = create_imap_client(account, password)
    try:
        return client.search_messages(folder=folder, criteria=criteria, limit=limit)
    finally:
        if isinstance(client, StdlibImapClient):
            client.close()


def send_smtp_message(
    account: EmailAccount,
    password: str,
    *,
    to_addr: str,
    subject: str,
    body: str,
    dry_run: bool,
) -> dict[str, object]:
    """Send a plain-text email via SMTP for ``account``.

    Args:
        account (EmailAccount): Source mailbox account.
        password (str): Resolved SMTP password or app token.
        to_addr (str): Recipient email address.
        subject (str): Message subject line.
        body (str): Plain-text body.
        dry_run (bool): When true, return argv/plan JSON without connecting.

    Returns:
        dict[str, object]: Result envelope with ``mode`` and delivery metadata.

    Raises:
        ValueError: When SMTP host is missing or recipient is empty.

    Examples:
        >>> acct = EmailAccount(
        ...     id="a",
        ...     label="A",
        ...     backend="imap",
        ...     username="u@example.com",
        ...     smtp_host="smtp.example.com",
        ... )
        >>> send_smtp_message(
        ...     acct,
        ...     "pw",
        ...     to_addr="dest@example.com",
        ...     subject="Hi",
        ...     body="Hello",
        ...     dry_run=True,
        ... )["mode"]
        'dry_run'
    """
    recipient = to_addr.strip()
    if not recipient:
        msg = "email-management: --to is required"
        raise ValueError(msg)
    smtp_host = account.smtp_host or (
        account.host.replace("imap.", "smtp.") if account.host else ""
    )
    if not smtp_host:
        msg = f"email-management: account {account.id!r} missing SMTP host"
        raise ValueError(msg)
    plan = {
        "mode": "dry_run",
        "account_id": account.id,
        "smtp_host": smtp_host,
        "smtp_port": account.smtp_port,
        "from": account.username,
        "to": recipient,
        "subject": subject,
        "body_chars": len(body),
    }
    if dry_run:
        return plan

    email_msg = EmailMessage()
    email_msg["From"] = account.username
    email_msg["To"] = recipient
    email_msg["Subject"] = subject
    email_msg.set_content(body)
    context = ssl.create_default_context()
    with smtplib.SMTP(smtp_host, account.smtp_port, timeout=30) as smtp:
        smtp.starttls(context=context)
        smtp.login(account.username, password)
        smtp.send_message(email_msg)
    return {
        "mode": "live",
        "account_id": account.id,
        "to": recipient,
        "subject": subject,
    }


def gmail_api_plan(
    account: EmailAccount,
    *,
    operation: str,
    folder: str = "INBOX",
    limit: int = 10,
    query: str = "",
) -> dict[str, object]:
    """Return a dry-run plan envelope for Gmail API backend operations.

    Args:
        account (EmailAccount): Gmail API account row.
        operation (str): One of ``list_labels``, ``fetch_recent``, ``search``.
        folder (str): Gmail label id (default ``INBOX``).
        limit (int): Max messages for fetch/search operations.
        query (str): Gmail search query string.

    Returns:
        dict[str, object]: Plan JSON safe for agent logs (no secrets).

    Examples:
        >>> gmail_api_plan(
        ...     EmailAccount(
        ...         id="g",
        ...         label="G",
        ...         backend="gmail_api",
        ...         username="me@gmail.com",
        ...     ),
        ...     operation="fetch_recent",
        ... )["backend"]
        'gmail_api'
    """
    return {
        "mode": "dry_run",
        "backend": "gmail_api",
        "account_id": account.id,
        "operation": operation,
        "user_id": "me",
        "label": folder,
        "limit": limit,
        "query": query,
        "api_base": "https://gmail.googleapis.com/gmail/v1",
    }


def summaries_to_dicts(rows: list[MessageSummary]) -> list[dict[str, str]]:
    """Convert message summaries to JSON-serialisable dict rows.

    Args:
        rows (list[MessageSummary]): Message summaries.

    Returns:
        list[dict[str, str]]: Plain dict rows.

    Examples:
        >>> summaries_to_dicts(
        ...     [
        ...         MessageSummary(
        ...             uid="1",
        ...             subject="Hi",
        ...             from_addr="a@b.com",
        ...             date="Mon",
        ...             snippet="text",
        ...         ),
        ...     ],
        ... )[0]["uid"]
        '1'
    """
    return [
        {
            "uid": row.uid,
            "subject": row.subject,
            "from": row.from_addr,
            "date": row.date,
            "snippet": row.snippet,
        }
        for row in rows
    ]
