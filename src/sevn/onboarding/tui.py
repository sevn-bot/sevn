"""Textual onboarding TUI (`specs/22-onboarding.md` §4.1 step machine).

Module: sevn.onboarding.tui
Depends: asyncio, pathlib, typing, textual, sevn.onboarding.*, sevn.cli.workspace

Exports:
    OnboardApp — Textual ``App`` driving the comprehensive-setup wizard.
    run_textual_onboarding — blocking entrypoint invoked by ``sevn onboard --cli``.

The wizard walks 13 steps aligned with the web wizard (W11 parity): profile → workspace →
My Sevn.bot → main model → capabilities → channels → secrets → sandbox → personality →
live validation → promote → seed → handoff. Flat ``fields`` ids match the web payload;
``_merge_wizard_payload`` produces the same merged document as ``--web``.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, ScrollableContainer
from textual.reactive import reactive
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    RadioButton,
    RadioSet,
    Static,
    Switch,
)

from sevn.cli.operator_lock import operator_lock
from sevn.cli.workspace import bound_sevn_json_path, bound_workspace_dir, sevn_home_dir
from sevn.gateway.gateway_token import generate_gateway_token
from sevn.onboarding.capabilities_manifest import (
    list_groups,
    load_manifest,
    merged_capability_defaults,
)
from sevn.onboarding.dashboard_url import apply_web_ui_url_for_dashboard
from sevn.onboarding.draft_store import write_draft
from sevn.onboarding.live_validate import run_live_validation
from sevn.onboarding.profiles import load_profile_catalog, load_profile_fragment
from sevn.onboarding.promote import promote_draft
from sevn.onboarding.seed import (
    load_personality_presets,
    seed_narrative_templates,
    seed_personality_from_wizard,
)
from sevn.onboarding.validate import validate_workspace_document
from sevn.onboarding.web_app import (
    _merge_wizard_payload,
    _wizard_gateway_token_plaintext,
    apply_model_slot_policy,
    normalize_secrets_backend_section,
)
from sevn.onboarding.wizard_credentials import store_wizard_credentials

if TYPE_CHECKING:
    from collections.abc import Iterable

_STEP_COUNT = 13

_STEP_LABELS: tuple[str, ...] = tuple(
    f"{idx + 1}/{_STEP_COUNT} {title}"
    for idx, title in enumerate(
        (
            "Profile",
            "Workspace",
            "My Sevn.bot",
            "Main model",
            "Capabilities",
            "Channels",
            "Secrets backend",
            "Sandbox",
            "Personality",
            "Live validation",
            "Promote",
            "Seed templates",
            "Handoff",
        )
    )
)


def _capability_field_id(cap: dict[str, Any]) -> str:
    """Map a manifest capability row to the wizard flat field id.

    Args:
        cap (dict[str, Any]): Capability dict from ``list_groups``.

    Returns:
        str: Dot-path field id (first ``config_paths`` entry).

    Examples:
        >>> _capability_field_id({"config_paths": ["gateway.queue_mode"], "capability_id": "x"})
        'gateway.queue_mode'
    """
    paths = cap.get("config_paths") or []
    if paths:
        return str(paths[0])
    return f"capability.{cap.get('capability_id', 'unknown')}"


def _is_capability_stub(cap: dict[str, Any]) -> bool:
    """Return True when a capability row is a disabled coming-soon stub.

    Args:
        cap (dict[str, Any]): Capability dict from the manifest.

    Returns:
        bool: True for stub rows (not selectable in TUI).

    Examples:
        >>> _is_capability_stub({"capability_id": "channel.discord_stub", "label": "Discord"})
        True
    """
    cid = str(cap.get("capability_id", ""))
    label = str(cap.get("label", ""))
    return cid.endswith("_stub") or "coming soon" in label.lower()


def _capability_switch_id(capability_id: str) -> str:
    """Build a Textual-safe widget id for a capability switch.

    Args:
        capability_id (str): Manifest ``capability_id``.

    Returns:
        str: Widget id prefixed with ``cap__``.

    Examples:
        >>> _capability_switch_id("extra.browser")
        'cap__extra_browser'
    """
    safe = capability_id.replace(".", "_").replace("-", "_")
    return f"cap__{safe}"


def _merged_from_app(app: OnboardApp) -> dict[str, Any]:
    """Build merged preview config using the same path as the web wizard.

    Args:
        app (OnboardApp): Running TUI with accumulated ``fields``.

    Returns:
        dict[str, Any]: Merged workspace document.

    Examples:
        >>> app = OnboardApp()
        >>> app.fields["gateway.port"] = 3002
        >>> _merged_from_app(app)["gateway"]["port"]
        3002
    """
    return _merge_wizard_payload({"fields": app.fields}, profile_id=app.applied_profile)


class OnboardApp(App[int]):
    """Textual driver for the comprehensive onboarding wizard (W11 web parity).

    Examples:
        >>> len(_STEP_LABELS)
        13
    """

    CSS_PATH = Path(__file__).resolve().parent / "onboarding.tcss"

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("ctrl+c", "quit", "Quit", priority=True),
        Binding("escape", "go_back", "Back"),
    ]

    step_idx: reactive[int] = reactive(0, init=False)

    def __init__(self) -> None:
        """Initialise wizard state with empty fields and no applied profile.

        Examples:
            >>> _STEP_LABELS[0].startswith("1/13")
            True
        """
        super().__init__()
        self.fields: dict[str, Any] = {
            "workspace_root": ".",
            "gateway.host": "127.0.0.1",
            "gateway.port": 3001,
        }
        self.applied_profile: str | None = None
        self._promoted: bool = False
        self._validation_failed: bool = False
        self._handoff_lines: list[str] = []
        self._merged_config: dict[str, Any] | None = None
        self._capability_rows: list[tuple[str, dict[str, Any]]] = []

    # ------------------------------------------------------------------ layout

    def compose(self) -> ComposeResult:
        """Yield the static layout (header, title, body, nav bar, footer).

        Returns:
            ComposeResult: Generator of root widgets consumed by Textual.

        Examples:
            >>> _STEP_LABELS[-1].startswith("13/13")
            True
        """
        yield Header(show_clock=False)
        yield Static(_STEP_LABELS[0], id="title")
        yield ScrollableContainer(id="body")
        with Horizontal(id="nav"):
            yield Button("Back", id="back", disabled=True)
            yield Button("Next", id="next", variant="primary")
            yield Button("Quit", id="quit", variant="error")
        yield Footer()

    def on_mount(self) -> None:
        """Render the initial step once the app mounts.

        Examples:
            >>> isinstance(_STEP_LABELS, tuple)
            True
        """
        self._render_step()

    # ------------------------------------------------------------------ nav

    def watch_step_idx(self, _old: int, _new: int) -> None:
        """Re-render whenever ``step_idx`` changes (Textual reactive hook).

        Args:
            _old (int): Previous step index (unused).
            _new (int): New step index (unused; ``self.step_idx`` is authoritative).

        Examples:
            >>> 0 < len(_STEP_LABELS)
            True
        """
        self._render_step()

    def _render_step(self) -> None:
        """Repaint title + body for the current step and toggle nav state.

        Examples:
            >>> _STEP_LABELS[4]
            '5/13 Capabilities'
        """
        title = self.query_one("#title", Static)
        title.update(_STEP_LABELS[self.step_idx])
        body = self.query_one("#body", ScrollableContainer)
        body.remove_children()
        renderers = (
            self._render_profile,
            self._render_workspace,
            self._render_my_sevn,
            self._render_main_model,
            self._render_capabilities,
            self._render_channels,
            self._render_secrets_backend,
            self._render_sandbox,
            self._render_personality,
            self._render_live_validation,
            self._render_promote,
            self._render_seed,
            self._render_handoff,
        )
        renderers[self.step_idx]()
        back = self.query_one("#back", Button)
        nxt = self.query_one("#next", Button)
        back.disabled = self.step_idx == 0 or self._promoted
        nxt.label = "Finish" if self.step_idx == len(_STEP_LABELS) - 1 else "Next"

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Route nav-bar button clicks to back/next/quit handlers.

        Args:
            event (Button.Pressed): Textual event carrying the source ``Button``.

        Examples:
            >>> "back" in {"back", "next", "quit"}
            True
        """
        if event.button.id == "quit":
            self.exit(2)
            return
        if event.button.id == "back":
            self.action_go_back()
            return
        if event.button.id == "next":
            self._advance()

    def action_go_back(self) -> None:
        """Move to the previous step unless the draft has already been promoted.

        Examples:
            >>> _STEP_LABELS[10]
            '11/13 Promote'
        """
        if self.step_idx > 0 and not self._promoted:
            self.step_idx -= 1

    def _advance(self) -> None:
        """Commit the current step and advance, exiting on the final step.

        Examples:
            >>> len(_STEP_LABELS) - 1
            12
        """
        committers = (
            self._commit_profile,
            self._commit_workspace,
            self._commit_my_sevn,
            self._commit_main_model,
            self._commit_capabilities,
            self._commit_channels,
            self._commit_secrets_backend,
            self._commit_sandbox,
            self._commit_personality,
            self._commit_live_validation,
            self._commit_promote,
            self._commit_seed,
            self._commit_handoff,
        )
        try:
            committers[self.step_idx]()
        except (ValueError, OSError) as exc:
            self._show_error(str(exc))
            return
        if self.step_idx >= len(_STEP_LABELS) - 1:
            self.exit(0)
            return
        self.step_idx += 1

    def _show_error(self, msg: str) -> None:
        """Mount a red error line at the bottom of the body container.

        Args:
            msg (str): Human-readable error to display.

        Examples:
            >>> "error" in "[red]error:[/red] x"
            True
        """
        body = self.query_one("#body", ScrollableContainer)
        body.mount(Static(f"[red]error:[/red] {msg}", classes="err"))

    def _field_str(self, field_id: str, default: str = "") -> str:
        """Return a string field value from accumulated wizard fields.

        Args:
            field_id (str): Flat wizard field id.
            default (str): Fallback when unset.

        Returns:
            str: Trimmed field value or ``default``.

        Examples:
            >>> app = OnboardApp()
            >>> app.fields["agent.display_name"] = " Nova "
            >>> app._field_str("agent.display_name")
            'Nova'
        """
        raw = self.fields.get(field_id, default)
        return str(raw).strip() if raw is not None else default

    # ------------------------------------------------------------------ steps

    def _render_profile(self) -> None:
        """Render step 1 — profile radio set populated from the packaged catalog.

        Examples:
            >>> _STEP_LABELS[0]
            '1/13 Profile'
        """
        body = self.query_one("#body", ScrollableContainer)
        body.mount(Static("Pick a starting profile (or skip):", classes="hint"))
        rs = RadioSet(id="profile_radio")
        rs.border_title = "Profiles"
        body.mount(rs)
        skip_selected = self.applied_profile is None
        rs.mount(RadioButton("(skip — custom)", value=skip_selected, id="profile__skip"))
        for row in load_profile_catalog():
            pid = str(row["profile_id"])
            title = str(row.get("title", pid))
            desc = str(row.get("short_description", ""))
            selected = self.applied_profile == pid
            rs.mount(RadioButton(f"{title} — {desc}", value=selected, id=f"profile__{pid}"))

    def _commit_profile(self) -> None:
        """Record selected profile and pre-fill capability defaults (step 1).

        Examples:
            >>> "profile__full_free".removeprefix("profile__")
            'full_free'
        """
        rs = self.query_one("#profile_radio", RadioSet)
        pressed = rs.pressed_button
        if pressed is None or pressed.id == "profile__skip":
            self.applied_profile = None
            self.fields.pop("onboarding.applied_profile", None)
            return
        pid = (pressed.id or "").removeprefix("profile__")
        self.applied_profile = pid
        self.fields["onboarding.applied_profile"] = pid
        fragment = load_profile_fragment(pid)
        defaults = merged_capability_defaults(profile_fragment=fragment)
        manifest = load_manifest()
        for cap in manifest.capabilities:
            if cap.wizard_tab or cap.control == "hidden":
                continue
            cid = cap.capability_id
            if cid not in defaults:
                continue
            field_id = _capability_field_id(cap.model_dump(mode="json"))
            self.fields[field_id] = defaults[cid]

    def _render_workspace(self) -> None:
        """Render step 2 — workspace path and gateway bind settings.

        Examples:
            >>> _STEP_LABELS[1]
            '2/13 Workspace'
        """
        body = self.query_one("#body", ScrollableContainer)
        default_ws = str(bound_workspace_dir())
        body.mount(
            Static(
                "Workspace path — directory that will hold sevn.json, logs, narratives.",
                classes="hint",
            )
        )
        body.mount(Input(value=default_ws, id="workspace_input"))
        body.mount(Label("Gateway host:"))
        body.mount(Input(value=self._field_str("gateway.host", "127.0.0.1"), id="gateway_host"))
        body.mount(Label("Gateway port:"))
        body.mount(Input(value=str(self.fields.get("gateway.port", 3001)), id="gateway_port"))
        body.mount(
            Static(
                "Gateway token is auto-generated and stored in your secrets chain.",
                classes="hint",
            )
        )

    def _commit_workspace(self) -> None:
        """Persist workspace path and gateway fields (step 2).

        Examples:
            >>> _STEP_LABELS[1].endswith("Workspace")
            True
        """
        value = self.query_one("#workspace_input", Input).value.strip()
        if not value:
            msg = "workspace path is required"
            raise ValueError(msg)
        resolved = Path(value).expanduser().resolve()
        resolved.mkdir(parents=True, exist_ok=True)
        self.fields["workspace_root"] = "."
        self.fields["paths.workspace_root_resolved"] = str(resolved)
        self.fields["gateway.host"] = (
            self.query_one("#gateway_host", Input).value.strip() or "127.0.0.1"
        )
        port_text = self.query_one("#gateway_port", Input).value.strip() or "3001"
        try:
            port = int(port_text)
        except ValueError as exc:
            msg = "gateway.port must be an integer"
            raise ValueError(msg) from exc
        if not 1 <= port <= 65535:
            msg = "gateway.port must be between 1 and 65535"
            raise ValueError(msg)
        self.fields["gateway.port"] = port
        if not self.fields.get("wizard.gateway_token"):
            self.fields["wizard.gateway_token"] = generate_gateway_token()

    def _render_my_sevn(self) -> None:
        """Render step 3 — My Sevn.bot repo, sync, self-improve, GitHub PAT.

        Examples:
            >>> _STEP_LABELS[2]
            '3/13 My Sevn.bot'
        """
        body = self.query_one("#body", ScrollableContainer)
        body.mount(Static("Bot name, repo URL, backup, and self-improve defaults.", classes="hint"))
        body.mount(Label("Bot display name:"))
        body.mount(
            Input(
                value=self._field_str("agent.display_name", "sevn"),
                id="agent_name_input",
            )
        )
        body.mount(Label("Repository URL:"))
        body.mount(
            Input(
                value=self._field_str(
                    "my_sevn.repo_url",
                    "https://github.com/sevn-bot/sevn",
                ),
                id="my_sevn_repo",
            )
        )
        body.mount(Label("Workspace backup repo URL (optional):"))
        body.mount(
            Input(
                value=self._field_str("my_sevn.workspace_backup.repo_url"),
                id="my_sevn_backup",
            )
        )
        body.mount(Label("GitHub personal access token (optional, manual entry):"))
        body.mount(Input(password=True, id="github_pat"))
        body.mount(Label("Daily repo sync?"))
        sync_on = self.fields.get("my_sevn.sync.enabled", True)
        body.mount(Switch(value=bool(sync_on), id="my_sevn_sync"))
        body.mount(Label("Self-improve enabled?"))
        si_on = self.fields.get("self_improve.enabled", True)
        body.mount(Switch(value=bool(si_on), id="self_improve_switch"))
        body.mount(Label("Self-improve via GitHub hub?"))
        hub_on = self.fields.get("self_improve.hub.use_github", True)
        body.mount(Switch(value=bool(hub_on), id="self_improve_hub_switch"))

    def _commit_my_sevn(self) -> None:
        """Persist My Sevn.bot fields (step 3).

        Examples:
            >>> _STEP_LABELS[2].endswith("My Sevn.bot")
            True
        """
        name = self.query_one("#agent_name_input", Input).value.strip() or "sevn"
        repo = self.query_one("#my_sevn_repo", Input).value.strip()
        if not repo:
            msg = "repository URL is required"
            raise ValueError(msg)
        self.fields["agent.display_name"] = name
        self.fields["my_sevn.repo_url"] = repo
        backup = self.query_one("#my_sevn_backup", Input).value.strip()
        if backup:
            self.fields["my_sevn.workspace_backup.repo_url"] = backup
        else:
            self.fields.pop("my_sevn.workspace_backup.repo_url", None)
        pat = self.query_one("#github_pat", Input).value.strip()
        if pat:
            self.fields["wizard.github_token"] = pat
        self.fields["my_sevn.sync.enabled"] = bool(self.query_one("#my_sevn_sync", Switch).value)
        self.fields["self_improve.enabled"] = bool(
            self.query_one("#self_improve_switch", Switch).value
        )
        self.fields["self_improve.hub.use_github"] = bool(
            self.query_one("#self_improve_hub_switch", Switch).value
        )

    def _render_main_model(self) -> None:
        """Render step 4 — triager model and provider API key.

        Examples:
            >>> _STEP_LABELS[3]
            '4/13 Main model'
        """
        body = self.query_one("#body", ScrollableContainer)
        body.mount(Static("Main triager model and provider API key.", classes="hint"))
        triager = self._field_str("providers.tier_default.triager", "anthropic/claude-sonnet-4-6")
        body.mount(Label("Triager model (provider/model):"))
        body.mount(Input(value=triager, id="triager_input"))
        body.mount(Label("Provider API key:"))
        body.mount(Input(password=True, id="provider_key_input"))

    def _commit_main_model(self) -> None:
        """Persist triager model and provider key (step 4).

        Examples:
            >>> _STEP_LABELS[3].endswith("model")
            True
        """
        triager = self.query_one("#triager_input", Input).value.strip()
        if not triager:
            msg = "main model (triager) is required"
            raise ValueError(msg)
        key = self.query_one("#provider_key_input", Input).value.strip()
        if not key:
            msg = "provider API key is required"
            raise ValueError(msg)
        self.fields["providers.tier_default.triager"] = triager
        self.fields["providers.use_main_model_for_all"] = True
        provider_name = triager.split("/", 1)[0].strip().lower() if "/" in triager else "openai"
        self.fields[f"wizard.provider_api_key.{provider_name}"] = key

    def _render_capabilities(self) -> None:
        """Render step 5 — grouped capability switches from the manifest.

        Examples:
            >>> _STEP_LABELS[4]
            '5/13 Capabilities'
        """
        body = self.query_one("#body", ScrollableContainer)
        body.mount(
            Static(
                "Capability inventory (profile defaults pre-checked). "
                "Use the web wizard for CDP-assisted browser steps.",
                classes="hint",
            )
        )
        fragment = None
        if self.applied_profile:
            try:
                fragment = load_profile_fragment(self.applied_profile)
            except (FileNotFoundError, ValueError, OSError):
                fragment = None
        defaults = merged_capability_defaults(profile_fragment=fragment)
        self._capability_rows = []
        for group in list_groups():
            visible = [
                cap
                for cap in group.capabilities
                if not cap.get("wizard_tab") and cap.get("control") != "hidden"
            ]
            if not visible:
                continue
            body.mount(Static(f"[bold]{group.label}[/bold]", classes="hint"))
            for cap in visible:
                cid = str(cap["capability_id"])
                field_id = _capability_field_id(cap)
                merged_default = defaults.get(cid, cap.get("default"))
                if cap.get("control") == "select":
                    rs = RadioSet(id=f"cap_select__{_capability_switch_id(cid)}")
                    rs.border_title = str(cap.get("label", cid))
                    body.mount(rs)
                    for opt in cap.get("select_options") or []:
                        current = self.fields.get(field_id, merged_default)
                        rs.mount(
                            RadioButton(
                                str(opt),
                                value=str(current) == str(opt),
                                id=f"capopt__{cid}__{opt}",
                            )
                        )
                    self._capability_rows.append((field_id, cap))
                    continue
                if cap.get("control") == "text":
                    current_val = self.fields.get(field_id, merged_default)
                    body.mount(Label(str(cap.get("label", cid))))
                    if cap.get("description"):
                        body.mount(Static(str(cap["description"]), classes="hint"))
                    body.mount(
                        Input(
                            id=f"cap_text__{_capability_switch_id(cid)}",
                            value="" if current_val in (True, False, None) else str(current_val),
                            placeholder="obsidian/alex_AI",
                        )
                    )
                    self._capability_rows.append((field_id, cap))
                    continue
                if cap.get("control") == "folder_picker":
                    body.mount(
                        Static(
                            f"{cap.get('label', cid)}: use the web wizard to browse folders, "
                            "or enter a workspace-relative path in the vault path field above.",
                            classes="hint",
                        )
                    )
                    continue
                stub = _is_capability_stub(cap)
                current_val = self.fields.get(field_id, merged_default)
                body.mount(Label(str(cap.get("label", cid))))
                body.mount(
                    Switch(
                        value=bool(current_val) and not stub,
                        id=_capability_switch_id(cid),
                        disabled=stub,
                    )
                )
                self._capability_rows.append((field_id, cap))
        body.mount(Static("[bold]OpenWiki[/bold] (optional)", classes="hint"))
        body.mount(
            Static(
                "LLM API key for OpenWiki when enabled. Skip if Main model provider key covers it.",
                classes="hint",
            )
        )
        body.mount(Label("OpenWiki LLM API key:"))
        body.mount(
            Input(
                password=True,
                id="openwiki_key_input",
                value=self._field_str("wizard.openwiki_llm_api_key"),
            )
        )

    def _commit_capabilities(self) -> None:
        """Persist capability checkbox/select values into ``fields`` (step 5).

        Examples:
            >>> _STEP_LABELS[4].endswith("Capabilities")
            True
        """
        for field_id, cap in self._capability_rows:
            cid = str(cap["capability_id"])
            if cap.get("control") == "select":
                rs = self.query_one(f"#cap_select__{_capability_switch_id(cid)}", RadioSet)
                pressed = rs.pressed_button
                if pressed is not None:
                    opt = (pressed.id or "").split("__")[-1]
                    self.fields[field_id] = opt
                continue
            if cap.get("control") == "text":
                inp = self.query_one(f"#cap_text__{_capability_switch_id(cid)}", Input)
                value = inp.value.strip()
                if value:
                    self.fields[field_id] = value
                else:
                    self.fields.pop(field_id, None)
                continue
            if _is_capability_stub(cap):
                self.fields[field_id] = False
                continue
            sw = self.query_one(f"#{_capability_switch_id(cid)}", Switch)
            self.fields[field_id] = bool(sw.value)
        ow = self.query_one("#openwiki_key_input", Input).value.strip()
        if ow:
            self.fields["wizard.openwiki_llm_api_key"] = ow
        else:
            self.fields.pop("wizard.openwiki_llm_api_key", None)
        if "gateway.queue_mode" not in self.fields:
            self.fields["gateway.queue_mode"] = "cancel"

    def _render_channels(self) -> None:
        """Render step 6 — manual Telegram token entry (no browser automation).

        Examples:
            >>> _STEP_LABELS[5]
            '6/13 Channels'
        """
        body = self.query_one("#body", ScrollableContainer)
        body.mount(
            Static(
                "Telegram + Web chat are always enabled. Paste credentials manually "
                "(web wizard offers BotFather automation via system Chrome).",
                classes="hint",
            )
        )
        body.mount(Label("Telegram bot token:"))
        body.mount(Input(password=True, id="telegram_token"))
        body.mount(Label("Your Telegram user id (owner):"))
        body.mount(Input(id="telegram_owner"))
        body.mount(Label("Bot username (optional):"))
        body.mount(Input(value=self._field_str("wizard.telegram_bot_username"), id="telegram_user"))
        body.mount(Label("Use polling mode? (off = webhook)"))
        body.mount(Switch(value=True, id="telegram_polling"))
        body.mount(
            Static(
                "LLM-guard kill-switches for owner messages (recommended: leave off).",
                classes="hint",
            )
        )
        body.mount(Label("Skip guard on owner text?"))
        body.mount(Switch(value=False, id="owner_scanner_text_switch"))
        body.mount(Label("Skip guard on owner links?"))
        body.mount(Switch(value=False, id="owner_scanner_links_switch"))
        body.mount(Label("Skip guard on owner documents?"))
        body.mount(Switch(value=False, id="owner_scanner_docs_switch"))

    def _commit_channels(self) -> None:
        """Persist Telegram channel secrets and hints (step 6).

        Examples:
            >>> _STEP_LABELS[5].endswith("Channels")
            True
        """
        token = self.query_one("#telegram_token", Input).value.strip()
        if not token:
            msg = "Telegram bot token is required"
            raise ValueError(msg)
        owner = self.query_one("#telegram_owner", Input).value.strip()
        if not owner:
            msg = "Telegram owner user id is required"
            raise ValueError(msg)
        try:
            int(owner)
        except ValueError as exc:
            msg = "owner user id must be numeric digits only"
            raise ValueError(msg) from exc
        self.fields["wizard.telegram_bot_token"] = token
        self.fields["wizard.telegram_owner_user_id"] = owner
        username = self.query_one("#telegram_user", Input).value.strip()
        if username:
            self.fields["wizard.telegram_bot_username"] = username.lstrip("@")
        self.fields["channels.telegram.enabled"] = True
        self.fields["channels.webchat.enabled"] = True
        polling = self.query_one("#telegram_polling", Switch).value
        self.fields["channels.telegram.mode"] = "polling" if polling else "webhook"
        self.fields["channels.telegram.owner_scanner_overrides.disable_text"] = bool(
            self.query_one("#owner_scanner_text_switch", Switch).value
        )
        self.fields["channels.telegram.owner_scanner_overrides.disable_links"] = bool(
            self.query_one("#owner_scanner_links_switch", Switch).value
        )
        self.fields["channels.telegram.owner_scanner_overrides.disable_documents"] = bool(
            self.query_one("#owner_scanner_docs_switch", Switch).value
        )

    def _render_secrets_backend(self) -> None:
        """Render step 7 — secrets backend radio (encrypted_file / openbao).

        Examples:
            >>> _STEP_LABELS[6]
            '7/13 Secrets backend'
        """
        body = self.query_one("#body", ScrollableContainer)
        body.mount(
            Static(
                "Secrets backend — provider keys never live in sevn.json; pick storage.",
                classes="hint",
            )
        )
        rs = RadioSet(id="secrets_backend")
        rs.border_title = "Backend"
        body.mount(rs)
        current = self._field_str("secrets_backend.type", "encrypted_file")
        for kind, label in (
            ("encrypted_file", "Encrypted file (default)"),
            ("openbao", "OpenBao (self-hosted vault)"),
        ):
            rs.mount(RadioButton(label, value=(kind == current), id=f"sec__{kind}"))
        body.mount(Label("Passphrase (encrypted_file):"))
        body.mount(Input(password=True, id="secrets_passphrase"))

    def _commit_secrets_backend(self) -> None:
        """Persist secrets backend type and passphrase (step 7).

        Examples:
            >>> "sec__encrypted_file".removeprefix("sec__")
            'encrypted_file'
        """
        rs = self.query_one("#secrets_backend", RadioSet)
        pressed = rs.pressed_button
        pressed_id = pressed.id if pressed is not None else None
        kind = (pressed_id or "sec__encrypted_file").removeprefix("sec__")
        self.fields["secrets_backend.type"] = kind
        passphrase = self.query_one("#secrets_passphrase", Input).value.strip()
        if kind == "encrypted_file" and not passphrase:
            msg = "passphrase is required for encrypted_file backend"
            raise ValueError(msg)
        if passphrase:
            self.fields["wizard.secrets_passphrase"] = passphrase

    def _render_sandbox(self) -> None:
        """Render step 8 — sandbox mode radio.

        Examples:
            >>> _STEP_LABELS[7]
            '8/13 Sandbox'
        """
        body = self.query_one("#body", ScrollableContainer)
        body.mount(Static("Sandbox / network policy.", classes="hint"))
        rs = RadioSet(id="sandbox_radio")
        rs.border_title = "Sandbox mode"
        body.mount(rs)
        current = self._field_str("sandbox.mode", "")
        options = (
            ("", "Use preset default (recommended)"),
            ("docker", "Docker (requires Docker)"),
            ("pyodide_deno", "Pyodide + Deno (no install)"),
        )
        for kind, label in options:
            rs.mount(RadioButton(label, value=(kind == current), id=f"sb__{kind or 'default'}"))

    def _commit_sandbox(self) -> None:
        """Persist sandbox mode selection (step 8).

        Examples:
            >>> "sb__docker".removeprefix("sb__")
            'docker'
        """
        rs = self.query_one("#sandbox_radio", RadioSet)
        pressed = rs.pressed_button
        pressed_id = pressed.id if pressed is not None else None
        kind = (pressed_id or "sb__default").removeprefix("sb__")
        if kind == "default":
            self.fields.pop("sandbox.mode", None)
        else:
            self.fields["sandbox.mode"] = kind

    def _render_personality(self) -> None:
        """Render step 9 — optional personality fast-start fields.

        Examples:
            >>> _STEP_LABELS[8]
            '9/13 Personality'
        """
        body = self.query_one("#body", ScrollableContainer)
        body.mount(
            Static(
                "Optional personality fields — leave blank to skip bootstrap seeding.",
                classes="hint",
            )
        )
        presets = load_personality_presets()
        style_hint = ", ".join(presets["style"][:3]) + ", …"
        body.mount(Label("Your name (optional):"))
        body.mount(Input(value=self._field_str("onboarding.personality.name"), id="p_name"))
        body.mount(Label("Your role (optional):"))
        body.mount(Input(value=self._field_str("onboarding.personality.role"), id="p_role"))
        body.mount(Label("Timezone (optional):"))
        body.mount(Input(value=self._field_str("onboarding.personality.timezone"), id="p_tz"))
        body.mount(Label("Language (optional):"))
        body.mount(Input(value=self._field_str("onboarding.personality.language"), id="p_lang"))
        body.mount(Label(f"Style preset or free text ({style_hint}):"))
        body.mount(Input(value=self._field_str("onboarding.personality.style"), id="p_style"))
        body.mount(Label("Style detail (optional):"))
        body.mount(
            Input(value=self._field_str("onboarding.personality.style_detail"), id="p_style_detail")
        )
        body.mount(Label("Preferences preset or free text (optional):"))
        body.mount(
            Input(value=self._field_str("onboarding.personality.preferences"), id="p_preferences")
        )
        body.mount(Label("Preferences detail (optional):"))
        body.mount(
            Input(
                value=self._field_str("onboarding.personality.preferences_detail"),
                id="p_preferences_detail",
            )
        )
        body.mount(Label("Agent vibe (optional):"))
        body.mount(Input(value=self._field_str("onboarding.personality.vibe"), id="p_vibe"))
        body.mount(Label("Agent emoji (optional):"))
        body.mount(Input(value=self._field_str("onboarding.personality.emoji"), id="p_emoji"))

    def _commit_personality(self) -> None:
        """Persist optional personality fields (step 9); all may be empty.

        Examples:
            >>> _STEP_LABELS[8].endswith("Personality")
            True
        """
        mapping = {
            "p_name": "onboarding.personality.name",
            "p_role": "onboarding.personality.role",
            "p_tz": "onboarding.personality.timezone",
            "p_lang": "onboarding.personality.language",
            "p_style": "onboarding.personality.style",
            "p_style_detail": "onboarding.personality.style_detail",
            "p_preferences": "onboarding.personality.preferences",
            "p_preferences_detail": "onboarding.personality.preferences_detail",
            "p_vibe": "onboarding.personality.vibe",
            "p_emoji": "onboarding.personality.emoji",
        }
        for widget_id, field_id in mapping.items():
            value = self.query_one(f"#{widget_id}", Input).value.strip()
            if value:
                self.fields[field_id] = value
            else:
                self.fields.pop(field_id, None)

    def _render_live_validation(self) -> None:
        """Render step 10 — placeholder before probe sweep.

        Examples:
            >>> _STEP_LABELS[9]
            '10/13 Live validation'
        """
        body = self.query_one("#body", ScrollableContainer)
        body.mount(Static("Running live validation probes…", classes="hint"))
        body.mount(Static("(run_live_validation executes when you press Next.)"))

    def _commit_live_validation(self) -> None:
        """Run live probes on merged preview; block on error severity (step 10).

        Examples:
            >>> _STEP_LABELS[9].endswith("validation")
            True
        """
        body = self.query_one("#body", ScrollableContainer)
        body.remove_children()
        body.mount(Static("Live validation report:", classes="hint"))
        merged = _merged_from_app(self)
        validate_workspace_document(merged)
        report = asyncio.run(
            run_live_validation(
                workspace_root=bound_workspace_dir(),
                merged_preview=merged,
                profile_id=self.applied_profile,
            )
        )
        self._validation_failed = report.has_error()
        for check in report.checks:
            icon = "[green]✓[/green]" if check.ok else "[red]✗[/red]"
            sev = check.severity.upper()
            body.mount(Static(f"{icon} [{sev}] {check.check_id}: {check.detail}"))
        if self._validation_failed:
            msg = "live validation has error-severity failures; fix them or quit"
            raise ValueError(msg)

    def _render_promote(self) -> None:
        """Render step 11 — confirmation banner before atomic promotion.

        Examples:
            >>> _STEP_LABELS[10]
            '11/13 Promote'
        """
        body = self.query_one("#body", ScrollableContainer)
        path = bound_sevn_json_path()
        body.mount(
            Static(
                f"Ready to promote merged config to {path}.\nPress Next to write atomically.",
                classes="hint",
            )
        )

    def _commit_promote(self) -> None:
        """Validate, store secrets, write draft, and promote (step 11).

        Examples:
            >>> _STEP_LABELS[10].endswith("Promote")
            True
        """
        sevn_path = bound_sevn_json_path()
        bound_workspace_dir().mkdir(parents=True, exist_ok=True)
        merged = _merged_from_app(self)
        normalize_secrets_backend_section(merged)
        apply_model_slot_policy(merged)
        from sevn.config.provider_secrets import apply_provider_credential_bindings
        from sevn.onboarding.web_app import _provider_api_keys_from_fields

        apply_provider_credential_bindings(merged)
        validate_workspace_document(merged)
        apply_web_ui_url_for_dashboard(merged)
        self._merged_config = merged

        from sevn.config.workspace_config import parse_workspace_config

        parsed = parse_workspace_config(merged)

        async def _store_creds() -> None:
            await store_wizard_credentials(
                bound_workspace_dir(),
                gateway_token=_wizard_gateway_token_plaintext(self.fields),
                github_token=self._field_str("wizard.github_token") or None,
                openwiki_llm_api_key=self._field_str("wizard.openwiki_llm_api_key") or None,
                bot_token=self._field_str("wizard.telegram_bot_token") or None,
                provider_api_keys=_provider_api_keys_from_fields(self.fields),
                telegram_api_id=self._field_str("wizard.telegram_api_id") or None,
                telegram_api_hash=self._field_str("wizard.telegram_api_hash") or None,
                telegram_phone=self._field_str("wizard.telegram_phone") or None,
                secrets_passphrase=self._field_str("wizard.secrets_passphrase") or None,
                section=parsed.secrets_backend,
            )

        asyncio.run(_store_creds())

        with operator_lock(sevn_home_dir()):
            write_draft(sevn_path, merged)
            promote_draft(sevn_path, backup_previous=sevn_path.is_file())
        self._promoted = True
        self._handoff_lines.append(f"promoted: {sevn_path}")

        from sevn.onboarding.install_orchestrator import (
            build_install_plan,
            collect_install_run,
            selected_capability_ids,
        )
        from sevn.onboarding.seed import opt_in_skill_ids_from_capabilities, seed_bundled_skills

        content_root = bound_workspace_dir()
        selected_caps = selected_capability_ids(merged)
        seed_bundled_skills(
            content_root,
            enabled_opt_in_skill_ids=opt_in_skill_ids_from_capabilities(selected_caps),
        )
        install_plan = build_install_plan(merged)
        install_summary = asyncio.run(
            collect_install_run(
                install_plan,
                merged_config=merged,
                content_root=content_root,
            )
        )
        if install_summary.ok:
            self._handoff_lines.append("capability installs: ok")
        else:
            self._handoff_lines.append(
                f"capability installs: completed with warnings "
                f"(failed_fatal={install_summary.failed_fatal_action_ids})"
            )

        from sevn.cli.install_gate import maybe_install_daemon_after_promote
        from sevn.cli.operator_lock import OperatorLockHeld
        from sevn.cli.service_manager import ServiceManagerError

        try:
            daemon_line = maybe_install_daemon_after_promote()
        except (OperatorLockHeld, ServiceManagerError) as exc:
            self._handoff_lines.append(f"daemon install failed: {exc}")
        else:
            if daemon_line is not None:
                self._handoff_lines.append(daemon_line)

        from sevn.pdf.native_libs import maybe_install_pdf_native_libs_after_promote

        pdf_native_line = maybe_install_pdf_native_libs_after_promote()
        if pdf_native_line is not None:
            self._handoff_lines.append(pdf_native_line)

    def _render_seed(self) -> None:
        """Render step 12 — narrative + personality seeding hint.

        Examples:
            >>> _STEP_LABELS[11]
            '12/13 Seed templates'
        """
        body = self.query_one("#body", ScrollableContainer)
        body.mount(
            Static(
                "Seeding workspace narrative templates and optional personality markdown.",
                classes="hint",
            )
        )

    def _commit_seed(self) -> None:
        """Seed narratives and personality markdown (step 12).

        Examples:
            >>> _STEP_LABELS[11].endswith("templates")
            True
        """
        sevn_path = bound_sevn_json_path()
        merged = self._merged_config or _merged_from_app(self)
        written = seed_narrative_templates(sevn_path, merged)
        written.extend(seed_personality_from_wizard(bound_workspace_dir(), merged))
        body = self.query_one("#body", ScrollableContainer)
        if written:
            for path in written:
                body.mount(Static(f"[green]wrote[/green] {path}"))
                self._handoff_lines.append(f"seeded: {path}")
        else:
            body.mount(Static("(no new files — narratives already present)", classes="hint"))

    def _render_handoff(self) -> None:
        """Render step 13 — handoff summary with next-steps for the operator.

        Examples:
            >>> _STEP_LABELS[12]
            '13/13 Handoff'
        """
        body = self.query_one("#body", ScrollableContainer)
        body.mount(Static("Done. Next steps:", classes="hint"))
        for line in self._handoff_lines:
            body.mount(Static(f"  • {line}"))
        body.mount(Static("  • run `sevn doctor` to verify"))
        body.mount(Static("  • run `sevn gateway start` to bring the gateway up"))
        body.mount(Static("  • see `specs/22-onboarding.md` §4.1 for the full step table"))

    def _commit_handoff(self) -> None:
        """No-op terminal commit; ``_advance`` triggers ``app.exit(0)``.

        Examples:
            >>> _STEP_LABELS[-1] == "13/13 Handoff"
            True
        """


def _all_step_renderers() -> Iterable[str]:
    """Return human-readable step labels (used by tests and ``_render_step``).

    Returns:
        Iterable[str]: Ordered 13-tuple of ``"<n>/13 <Title>"`` strings.

    Examples:
        >>> labels = list(_all_step_renderers())
        >>> len(labels)
        13
    """
    return _STEP_LABELS


def run_textual_onboarding() -> int:
    """Run the wizard; return process exit code.

    Returns:
        int: ``0`` when promotion completed; ``2`` when the operator quit early.

    Examples:
        >>> list(_all_step_renderers())[-1]
        '13/13 Handoff'
    """
    import json

    from sevn.cli.install_gate import parse_reuse_from_env

    app = OnboardApp()
    if parse_reuse_from_env():
        sevn_path = bound_sevn_json_path()
        if sevn_path.is_file():
            raw = json.loads(sevn_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                app._merged_config = raw
                onboarding = raw.get("onboarding")
                if isinstance(onboarding, dict):
                    prof = onboarding.get("applied_profile")
                    if isinstance(prof, str):
                        app.applied_profile = prof
                        app.fields["onboarding.applied_profile"] = prof
                app.step_idx = 9
    rc = app.run()
    if rc is None:
        return 2
    return int(rc)
