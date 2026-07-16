"""Wire Proton services, renderer, and session for one CLI invocation."""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass

from proton_cli import __version__
from proton_cli.account import keys as keyring
from proton_cli.account import session as session_store
from proton_cli.env import env_for_profile, first_non_empty
from proton_cli.proton.client import Client
from proton_cli.render.output import Format, Renderer
from proton_cli.service.calendar.service import CalendarService
from proton_cli.service.contacts.service import ContactsService
from proton_cli.service.drive.service import DriveService
from proton_cli.service.mail.service import MailService
from proton_cli.service.pass_service.service import PassService


@dataclass
class Credentials:
    user: str
    password: str
    totp: str = ""


@dataclass
class App:
    profile: str
    creds: Credentials
    api: Client
    pass_svc: PassService
    mail_svc: MailService
    drive_svc: DriveService
    calendar_svc: CalendarService
    contacts_svc: ContactsService
    renderer: Renderer
    dry_run: bool = False
    full_ids: bool = False
    _cache: keyring.Unlocked | None = None
    _lock: threading.Lock = threading.Lock()

    def authenticate(self) -> None:
        uid, _, _ = self.api.tokens()
        if uid:
            return
        if not self.creds.user:
            raise ValueError("user is required (set --user, PROTON_USER, or configure a profile)")
        if not self.creds.password:
            raise ValueError("password is required (set --password or PROTON_PASSWORD)")
        self.renderer.info(f"Authenticating as {self.creds.user}...")
        self.api.login(self.creds.user, self.creds.password, self.creds.totp)
        self.renderer.success("Authenticated.")
        self._save_session()

    def unlock(self) -> keyring.Unlocked:
        with self._lock:
            if self._cache is not None:
                return self._cache
            unlocked = keyring.unlock(self.api, self.creds.password)
            self._cache = unlocked
            return unlocked

    def _save_session(self) -> None:
        uid, acc, ref = self.api.tokens()
        session_store.save(
            self.profile,
            session_store.from_parts(
                uid,
                acc,
                ref,
                self.api.enc_key_blob(),
                self.api.salted_key_pass(),
                self.api.app_version,
                self.api.base_url,
            ),
        )


@dataclass
class Options:
    profile: str = ""
    user: str = ""
    password: str = ""
    totp: str = ""
    api_url: str = ""
    app_version: str = ""
    output: Format = Format.TEXT
    quiet: bool = False
    dry_run: bool = False
    full_ids: bool = False


def new_app(opts: Options) -> App:
    profile = first_non_empty(opts.profile, os.environ.get("PROTON_PROFILE", ""), "default")
    user = first_non_empty(opts.user, env_for_profile(profile, "USER"))
    password = first_non_empty(opts.password, env_for_profile(profile, "PASSWORD"))
    totp = first_non_empty(opts.totp, env_for_profile(profile, "TOTP"))
    api_url = first_non_empty(opts.api_url, env_for_profile(profile, "API_URL"))
    app_version = first_non_empty(opts.app_version, env_for_profile(profile, "APP_VERSION"))
    user_agent = first_non_empty(
        env_for_profile(profile, "USER_AGENT"),
        f"proton-cli/{__version__}",
    )

    from proton_cli.proton.client import DEFAULT_APP_VERSION, DEFAULT_BASE_URL

    client = Client.new(
        base_url=api_url or DEFAULT_BASE_URL,
        app_version=app_version or DEFAULT_APP_VERSION,
        user_agent=user_agent,
        profile=profile,
    )

    loaded = session_store.load(profile)
    if loaded:
        client.set_tokens(loaded.uid, loaded.access_token, loaded.refresh_token)
        client.set_enc_key_blob(loaded.enc_key_blob)
        if loaded.salted_key_pass:
            client.set_salted_key_pass(loaded.salted_key_pass)

    renderer = Renderer(opts.output, quiet=opts.quiet)
    app = App(
        profile=profile,
        creds=Credentials(user=user, password=password, totp=totp),
        api=client,
        pass_svc=PassService(client),
        mail_svc=MailService(client),
        drive_svc=DriveService(client),
        calendar_svc=CalendarService(client),
        contacts_svc=ContactsService(client),
        renderer=renderer,
        dry_run=opts.dry_run,
        full_ids=opts.full_ids,
    )
    client.set_persist_hook(app._save_session)
    return app
