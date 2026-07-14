"""Workspace narrative templates (`specs/22-onboarding.md` §2.1, §4.8).

Module: sevn.onboarding.seed
Depends: importlib.resources, pathlib, sevn.config.workspace_config, sevn.workspace.layout

Exports:
    load_template — read a packaged ``.md`` template by filename.
    resolve_agent_display_name — bot name from promoted ``sevn.json`` draft.
    render_template — substitute ``{{AGENT_NAME}}`` placeholders.
    seed_tracing_defaults — merge default ``tracing.sinks`` when absent from a document.
    seed_narrative_templates — write default markdown files when missing.
    seed_personality_from_wizard — merge onboarding personality draft into markdown.
    load_personality_presets — packaged style/preferences dropdown options.
    seed_llm_params — copy ``LLM_params_config.json`` into the workspace when absent.
    seed_bundled_skills — copy missing ``skills/core`` packages from packaged tree.
    opt_in_skill_ids_from_capabilities — map manifest opt-in capabilities to skill ids.
    ensure_skills_user_dir — create ``skills/user/`` for operator and agent skill installs.
    refresh_bundled_core_skills — replace deployed ``skills/core`` packages from bundled tree.
    expected_core_skill_ids — bundled core skill ids required after seed.
    list_deployed_core_skill_ids — list deployed core skill ids under workspace.
    verify_core_skills_deployed — list missing core skill dirs under workspace.

Examples:
    >>> from pathlib import Path
    >>> from sevn.onboarding.seed import seed_narrative_templates
    >>> # exercised in tests/onboarding/
"""

from __future__ import annotations

import json
import re
import shutil
from importlib import resources
from typing import TYPE_CHECKING, Any, Final

from sevn.config.defaults import DEFAULT_TRACING_SINKS
from sevn.config.workspace_config import parse_workspace_config
from sevn.data.bundled_skills import BUNDLED_SKILLS_ROOT
from sevn.data.skills_index import ensure_workspace_index
from sevn.security.llmignore import ensure_llmignore_layout
from sevn.workspace.layout import WorkspaceLayout
from sevn.workspace.safe_root import reject_package_checkout_content_root

if TYPE_CHECKING:
    from pathlib import Path

_AGENT_PLACEHOLDER: Final[str] = "{{AGENT_NAME}}"
_DEFAULT_AGENT_NAME: Final[str] = "Sevn"
_USER_INCOMPLETE_MARKER: Final[str] = "<!-- sevn-bootstrap:user-incomplete -->"
_PLACEHOLDER_VALUE: Final[re.Pattern[str]] = re.compile(r"^_\(.*\)_$")
_PERSONALITY_FIELD_KEYS: Final[tuple[str, ...]] = (
    "name",
    "role",
    "timezone",
    "style",
    "style_detail",
    "language",
    "preferences",
    "preferences_detail",
    "vibe",
    "emoji",
)

# Bundled core skills that require explicit operator opt-in (not required after seed).
_OPT_IN_CORE_SKILL_IDS: Final[frozenset[str]] = frozenset(
    {"computer-use", "cursor_cloud", "cua-agent", "lume"}
)
_CAPABILITY_OPT_IN_SKILL_IDS: Final[dict[str, str]] = {
    "skill.computer_use": "computer-use",
    "skill.cursor_cloud": "cursor_cloud",
    "skill.cua_agent": "cua-agent",
    "skill.lume": "lume",
}

NARRATIVE_TEMPLATE_NAMES: Final[tuple[str, ...]] = (
    "AGENTS.md",
    "AGENTS-detail.md",
    "sevn.bot.md",
    "BOOTSTRAP.md",
    "IDENTITY.md",
    "MEMORY.md",
    "SESSIONS.md",
    "SEVN-ARCHITECTURE.md",
    "SOUL.md",
    "TOOLS.md",
    "USER.md",
    "WORKSPACE.md",
)


def load_template(name: str) -> str:
    """Load a packaged workspace narrative template from ``sevn.data.workspace_templates``.

    Args:
        name (str): Filename (e.g. ``IDENTITY.md``).

    Returns:
        str: Raw template body (may contain ``{{AGENT_NAME}}``).

    Raises:
        FileNotFoundError: When ``name`` is not packaged.

    Examples:
        >>> "IDENTITY" in load_template("IDENTITY.md") or "Name" in load_template("IDENTITY.md")
        True
    """
    ref = resources.files("sevn.data.workspace_templates") / name
    if not ref.is_file():
        msg = f"workspace template not found: {name}"
        raise FileNotFoundError(msg)
    return ref.read_text(encoding="utf-8")


def resolve_agent_display_name(merged: dict[str, Any]) -> str:
    """Resolve wizard bot name from a merged or promoted workspace document.

    Args:
        merged (dict[str, Any]): Workspace JSON (draft or promoted).

    Returns:
        str: ``agent.display_name`` when set, else ``Sevn``.

    Examples:
        >>> resolve_agent_display_name({"agent": {"display_name": "  Nova  "}})
        'Nova'
        >>> resolve_agent_display_name({})
        'Sevn'
    """
    agent = merged.get("agent")
    if isinstance(agent, dict):
        raw = agent.get("display_name")
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    return _DEFAULT_AGENT_NAME


def seed_tracing_defaults(merged: dict[str, Any]) -> bool:
    """Merge default ``tracing.sinks`` when the key is absent from ``merged``.

    An explicit ``tracing.sinks`` list — including ``[]`` for operator opt-out —
    is never overwritten. A ``tracing`` object without a ``sinks`` key is treated
    as unconfigured and receives :data:`sevn.config.defaults.DEFAULT_TRACING_SINKS`.

    Args:
        merged (dict[str, Any]): Workspace JSON draft or promoted document.

    Returns:
        bool: ``True`` when defaults were written.

    Examples:
        >>> seed_tracing_defaults({"schema_version": 1})
        True
        >>> doc: dict[str, object] = {
        ...     "schema_version": 1,
        ...     "tracing": {"sinks": []},
        ... }
        >>> seed_tracing_defaults(doc)
        False
        >>> doc["tracing"]
        {'sinks': []}
    """
    tracing = merged.get("tracing")
    if isinstance(tracing, dict) and "sinks" in tracing:
        return False
    sinks = [dict(entry) for entry in DEFAULT_TRACING_SINKS]
    if tracing is None:
        merged["tracing"] = {"sinks": sinks}
        return True
    if isinstance(tracing, dict):
        tracing["sinks"] = sinks
        return True
    return False


def render_template(body: str, agent_name: str) -> str:
    """Substitute ``{{AGENT_NAME}}`` in a template body.

    Args:
        body (str): Packaged template text.
        agent_name (str): Operator-chosen bot name.

    Returns:
        str: Rendered markdown.

    Examples:
        >>> render_template("Hello {{AGENT_NAME}}", "Nova")
        'Hello Nova'
    """
    return body.replace(_AGENT_PLACEHOLDER, agent_name)


def _append_user_incomplete_marker(body: str, *, fresh_template_body: str) -> str:
    """Append bootstrap incomplete marker when ``body`` is still the packaged template.

    Args:
        body (str): Rendered USER.md body about to be written.
        fresh_template_body (str): Expected rendered template for the same agent name.

    Returns:
        str: ``body`` with marker appended once when pristine; unchanged otherwise.

    Examples:
        >>> from sevn.onboarding.seed import _append_user_incomplete_marker, load_template, render_template
        >>> fresh = render_template(load_template("USER.md"), "Nova")
        >>> marked = _append_user_incomplete_marker(fresh, fresh_template_body=fresh)
        >>> marked.endswith("<!-- sevn-bootstrap:user-incomplete -->\\n")
        True
        >>> _append_user_incomplete_marker(
        ...     "operator edited",
        ...     fresh_template_body=fresh,
        ... )
        'operator edited'
    """
    if body != fresh_template_body or _USER_INCOMPLETE_MARKER in body:
        return body
    return f"{body.rstrip()}\n\n{_USER_INCOMPLETE_MARKER}\n"


def seed_narrative_templates(
    sevn_json_path: Path,
    merged: dict[str, Any],
    *,
    overwrite: bool = False,
) -> list[Path]:
    """Write narrative templates under ``content_root`` when files are missing.

    Args:
        sevn_json_path (Path): Path to ``sevn.json``.
        merged (dict[str, Any]): Promoted workspace document (parsed context).
        overwrite (bool): When True, replace existing files (**migration consent only**).

    Returns:
        list[Path]: Files written (empty when nothing created).

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> from sevn.onboarding.seed import seed_narrative_templates
        >>> td = Path(tempfile.mkdtemp())
        >>> sj = td / "sevn.json"
        >>> sj.parent.mkdir(parents=True, exist_ok=True)
        >>> _ = sj.write_text(
        ...     '{"schema_version": 1, "workspace_root": ".",'
        ...     ' "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
        ...     encoding="utf-8",
        ... )
        >>> paths = seed_narrative_templates(
        ...     sj,
        ...     {
        ...         "schema_version": 1,
        ...         "workspace_root": ".",
        ...         "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        ...         "agent": {"display_name": "Nova"},
        ...     },
        ... )
        >>> any(p.name == "IDENTITY.md" for p in paths)
        True
    """
    cfg = parse_workspace_config(merged)
    layout = WorkspaceLayout.from_config(sevn_json_path, cfg)
    root = layout.content_root
    reject_package_checkout_content_root(root)
    root.mkdir(parents=True, exist_ok=True)
    layout.logs_dir.mkdir(parents=True, exist_ok=True)
    ensure_llmignore_layout(root, cfg)
    agent_name = resolve_agent_display_name(merged)
    written: list[Path] = []
    for name in NARRATIVE_TEMPLATE_NAMES:
        target = root / name
        if target.exists() and not overwrite:
            continue
        template_body = load_template(name)
        body = render_template(template_body, agent_name)
        if name == "USER.md":
            body = _append_user_incomplete_marker(
                body,
                fresh_template_body=body,
            )
        target.write_text(body, encoding="utf-8")
        written.append(target)
    seed_bundled_skills(root)
    seed_llm_params(layout)
    from sevn.workspace.tools_md import sync_tools_md_for_config

    sync_tools_md_for_config(sevn_json_path, cfg, layout=layout, agent_name=agent_name)
    return written


def seed_llm_params(layout: WorkspaceLayout) -> Path | None:
    """Copy ``LLM_params_config.json`` into the workspace when absent (D2/W7.2).

    Mirrors :func:`seed_narrative_templates`' copy-if-absent contract for the
    per-agent sampling-params file. The packaged ``sevn.data/LLM_params_config.json``
    is the seed source; an existing workspace copy is never overwritten so
    operator edits survive a (re)start. Agents read the workspace copy at runtime
    via :func:`sevn.config.llm_params.resolve_llm_params`.

    Args:
        layout (WorkspaceLayout): Resolved workspace layout; ``content_root`` is
            the destination directory.

    Returns:
        Path | None: The written path when seeded, or ``None`` when the file was
        already present.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> from sevn.workspace.layout import WorkspaceLayout
        >>> td = Path(tempfile.mkdtemp())
        >>> lay = WorkspaceLayout(sevn_json_path=td / "sevn.json", content_root=td)
        >>> p = seed_llm_params(lay)
        >>> p is not None and p.name == "LLM_params_config.json"
        True
        >>> seed_llm_params(lay) is None  # idempotent: already present
        True
    """
    from sevn.config.llm_params import (
        LLM_PARAMS_FILENAME,
        builtin_llm_params_doc,
        validate_llm_params_doc,
    )

    root = layout.content_root
    root.mkdir(parents=True, exist_ok=True)
    target = root / LLM_PARAMS_FILENAME
    if target.exists():
        return None
    ref = resources.files("sevn.data") / LLM_PARAMS_FILENAME
    if ref.is_file():
        body = ref.read_text(encoding="utf-8")
        # Defensive: never seed a malformed packaged file.
        validate_llm_params_doc(json.loads(body))
    else:  # pragma: no cover - packaged resource always ships
        body = json.dumps(builtin_llm_params_doc(), indent=2, sort_keys=True) + "\n"
    target.write_text(body, encoding="utf-8")
    return target


def expected_core_skill_ids() -> tuple[str, ...]:
    """Return bundled core skill directory names required on disk after onboarding seed.

    Returns:
        tuple[str, ...]: Sorted skill ids excluding opt-in-only packages.

    Examples:
        >>> ids = expected_core_skill_ids()
        >>> "lcm" in ids and "computer-use" not in ids
        True
    """
    bundled_core = BUNDLED_SKILLS_ROOT / "core"
    if not bundled_core.is_dir():
        return ()
    names = sorted(
        p.name
        for p in bundled_core.iterdir()
        if p.is_dir() and p.name not in _OPT_IN_CORE_SKILL_IDS
    )
    return tuple(names)


def verify_core_skills_deployed(content_root: Path) -> list[str]:
    """List bundled core skill ids missing under ``workspace/skills/core/``.

    Args:
        content_root (Path): Resolved workspace content root.

    Returns:
        list[str]: Missing required skill directory names (empty when complete).

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> from sevn.onboarding.seed import seed_bundled_skills, verify_core_skills_deployed
        >>> td = Path(tempfile.mkdtemp())
        >>> _ = seed_bundled_skills(td)
        >>> verify_core_skills_deployed(td)
        []
    """
    reject_package_checkout_content_root(content_root)
    core_root = content_root / "skills" / "core"
    missing: list[str] = []
    for skill_id in expected_core_skill_ids():
        skill_md = core_root / skill_id / "SKILL.md"
        if not skill_md.is_file():
            missing.append(skill_id)
    return missing


def list_deployed_core_skill_ids(content_root: Path) -> list[str]:
    """Return skill ids under ``workspace/skills/core/`` that have ``SKILL.md``.

    Args:
        content_root (Path): Resolved workspace content root.

    Returns:
        list[str]: Sorted deployed core skill directory names (may be empty).

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> list_deployed_core_skill_ids(Path(tempfile.mkdtemp()))
        []
    """
    reject_package_checkout_content_root(content_root)
    core_root = content_root / "skills" / "core"
    if not core_root.is_dir():
        return []
    return sorted(p.name for p in core_root.iterdir() if p.is_dir() and (p / "SKILL.md").is_file())


def ensure_skills_user_dir(content_root: Path) -> Path:
    """Ensure ``workspace/skills/user/`` exists for operator and agent skill installs.

    Idempotent: creates the directory when absent; never removes existing content.
    New skill packages target ``skills/user/`` only; ``skills/core/`` remains
    write-forbidden across sevn surfaces (MC W0 Q7).

    Args:
        content_root (Path): Resolved workspace content root.

    Returns:
        Path: ``<content_root>/skills/user``.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> from sevn.onboarding.seed import ensure_skills_user_dir
        >>> td = Path(tempfile.mkdtemp())
        >>> p = ensure_skills_user_dir(td)
        >>> p.is_dir() and p.name == "user"
        True
    """
    reject_package_checkout_content_root(content_root)
    target = content_root / "skills" / "user"
    target.mkdir(parents=True, exist_ok=True)
    return target


def opt_in_skill_ids_from_capabilities(capability_ids: set[str]) -> set[str]:
    """Map enabled opt-in manifest capabilities to bundled core skill package ids.

    Args:
        capability_ids (set[str]): Selected onboarding capability ids.

    Returns:
        set[str]: Bundled ``skills/core`` directory names to seed.

    Examples:
        >>> opt_in_skill_ids_from_capabilities({"skill.computer_use"})
        {'computer-use'}
    """
    out: set[str] = set()
    for cap_id, skill_id in _CAPABILITY_OPT_IN_SKILL_IDS.items():
        if cap_id in capability_ids:
            out.add(skill_id)
    return out


def seed_bundled_skills(
    content_root: Path,
    *,
    enabled_opt_in_skill_ids: set[str] | None = None,
) -> list[Path]:
    """Copy missing bundled core skill packages into ``workspace/skills/core/``.

    Idempotent: existing package directories are never overwritten.

    Args:
        content_root (Path): Resolved workspace content root.
        enabled_opt_in_skill_ids (set[str] | None): Opt-in core skills to copy when enabled.

    Returns:
        list[Path]: ``SKILL.md`` paths written (one per newly copied package).

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> from sevn.onboarding.seed import seed_bundled_skills
        >>> td = Path(tempfile.mkdtemp())
        >>> paths = seed_bundled_skills(td)
        >>> any(p.name == "SKILL.md" for p in paths)
        True
    """
    reject_package_checkout_content_root(content_root)
    opt_in = enabled_opt_in_skill_ids or set()
    bundled_core = BUNDLED_SKILLS_ROOT / "core"
    core_root = content_root / "skills" / "core"
    core_root.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    if not bundled_core.is_dir():
        index_target = content_root / "skills" / "INDEX.md"
        had_index = index_target.is_file()
        index_path = ensure_workspace_index(content_root)
        if index_path.is_file() and not had_index:
            written.append(index_path)
        return written
    dest_root = core_root
    for src_pkg in sorted(bundled_core.iterdir()):
        if not src_pkg.is_dir():
            continue
        skill_id = src_pkg.name
        if skill_id in _OPT_IN_CORE_SKILL_IDS and skill_id not in opt_in:
            continue
        dest_pkg = dest_root / skill_id
        if dest_pkg.exists():
            continue
        shutil.copytree(
            src_pkg,
            dest_pkg,
            ignore=lambda _dir, names: {name for name in names if name == "__pycache__"},
        )
        skill_md = dest_pkg / "SKILL.md"
        if skill_md.is_file():
            written.append(skill_md)
    # Seed the workspace-authoritative ``skills/INDEX.md`` alongside the core
    # packages so ``read_skills_index`` resolves to a real file from day one.
    # Reference: operator chat 2026-05-27 — onboarding shipped the core
    # packages but never copied INDEX.md.
    index_target = content_root / "skills" / "INDEX.md"
    had_index = index_target.is_file()
    index_path = ensure_workspace_index(content_root)
    if index_path.is_file() and not had_index and index_path not in written:
        written.append(index_path)
    ensure_skills_user_dir(content_root)
    return written


def load_personality_presets() -> dict[str, list[str]]:
    """Load packaged onboarding personality dropdown presets (W8).

    Returns:
        dict[str, list[str]]: ``style``, ``preferences``, and optional ``languages``,
        ``vibes``, and ``emojis`` option lists.

    Raises:
        FileNotFoundError: When the packaged JSON is missing.
        json.JSONDecodeError: When the file is not valid JSON.

    Examples:
        >>> presets = load_personality_presets()
        >>> len(presets["style"]) == 10 and len(presets["preferences"]) == 10
        True
    """
    ref = resources.files("sevn.data") / "onboarding_personality_presets.json"
    if not ref.is_file():
        msg = "onboarding personality presets not found"
        raise FileNotFoundError(msg)
    raw = json.loads(ref.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        msg = "onboarding personality presets must be a JSON object"
        raise TypeError(msg)
    out: dict[str, list[str]] = {}
    for key in ("style", "preferences", "languages", "vibes", "emojis"):
        values = raw.get(key)
        if key in ("style", "preferences"):
            if not isinstance(values, list):
                msg = f"onboarding personality presets missing list key {key!r}"
                raise TypeError(msg)
            out[key] = [str(v) for v in values]
        elif isinstance(values, list):
            out[key] = [str(v) for v in values]
    return out


def _personality_draft_from_merged(merged: dict[str, Any]) -> dict[str, str]:
    """Extract non-empty wizard personality strings from a merged workspace doc.

    Args:
        merged (dict[str, Any]): Promoted or draft ``sevn.json`` tree.

    Returns:
        dict[str, str]: Trimmed personality field values.

    Examples:
        >>> _personality_draft_from_merged(
        ...     {"onboarding": {"personality": {"name": " Alex ", "role": ""}}}
        ... )
        {'name': 'Alex'}
    """
    onboarding = merged.get("onboarding")
    if not isinstance(onboarding, dict):
        return {}
    personality = onboarding.get("personality")
    if not isinstance(personality, dict):
        return {}
    out: dict[str, str] = {}
    for key in _PERSONALITY_FIELD_KEYS:
        raw = personality.get(key)
        if isinstance(raw, str) and raw.strip():
            out[key] = raw.strip()
    return out


def _combined_personality_text(primary: str | None, detail: str | None) -> str | None:
    """Join a dropdown preset with optional free-text detail.

    Args:
        primary (str | None): Preset label from the wizard dropdown.
        detail (str | None): Optional free-text detail.

    Returns:
        str | None: Combined text when either side is non-empty.

    Examples:
        >>> _combined_personality_text("Brief", "no fluff")
        'Brief. no fluff'
        >>> _combined_personality_text(None, "only detail")
        'only detail'
    """
    left = (primary or "").strip()
    right = (detail or "").strip()
    if left and right:
        return f"{left}. {right}"
    return left or right or None


def _is_markdown_placeholder(value: str) -> bool:
    """Return True when a markdown field value is still the template placeholder.

    Args:
        value (str): Current field value text.

    Returns:
        bool: True for italicised ``_(placeholder)_`` values.

    Examples:
        >>> _is_markdown_placeholder("_(your name)_")
        True
        >>> _is_markdown_placeholder("Alex")
        False
    """
    return bool(_PLACEHOLDER_VALUE.fullmatch(value.strip()))


def _replace_user_md_field(lines: list[str], field_label: str, value: str) -> bool:
    """Replace one ``- **Field:**`` bullet when its value is still a placeholder.

    Args:
        lines (list[str]): ``USER.md`` lines mutated in place.
        field_label (str): Label between ``**`` markers.
        value (str): Replacement value.

    Returns:
        bool: True when a placeholder line was replaced.

    Examples:
        >>> body = ["- **Name:** _(your name)_"]
        >>> _replace_user_md_field(body, "Name", "Alex")
        True
        >>> body[0]
        '- **Name:** Alex'
    """
    needle = f"**{field_label}:**"
    for idx, line in enumerate(lines):
        if needle not in line:
            continue
        _, _, tail = line.partition(needle)
        current = tail.strip()
        if not _is_markdown_placeholder(current):
            return False
        lines[idx] = f"- **{field_label}:** {value}"
        return True
    return False


def _replace_user_md_preferences(lines: list[str], pref_value: str) -> bool:
    """Replace the placeholder bullet under ``## Preferences`` when present.

    Args:
        lines (list[str]): ``USER.md`` lines mutated in place.
        pref_value (str): Preference text.

    Returns:
        bool: True when a placeholder line was replaced.

    Examples:
        >>> body = ["## Preferences", "- _(tools you prefer)_"]
        >>> _replace_user_md_preferences(body, "open source")
        True
    """
    pref_heading = next(
        (i for i, line in enumerate(lines) if line.strip() == "## Preferences"),
        None,
    )
    if pref_heading is None:
        return False
    for idx in range(pref_heading + 1, len(lines)):
        stripped = lines[idx].strip()
        if not stripped:
            continue
        if stripped.startswith("- "):
            bullet_value = stripped[2:].strip()
            if _is_markdown_placeholder(bullet_value):
                lines[idx] = f"- {pref_value}"
                return True
            break
    return False


def _patch_user_md_from_personality(
    content_root: Path,
    *,
    fields: dict[str, str],
) -> str:
    """Build ``USER.md`` with wizard personality fields applied.

    Args:
        content_root (Path): Workspace content root.
        fields (dict[str, str]): ``USER.md`` labels mapped to values.

    Returns:
        str: Patched markdown body.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> from sevn.onboarding.seed import seed_narrative_templates
        >>> with tempfile.TemporaryDirectory() as td:
        ...     root = Path(td)
        ...     sj = root / "sevn.json"
        ...     _ = sj.write_text(
        ...         '{"schema_version":1,"workspace_root":".",'
        ...         '"gateway":{"token":"${SECRET:keychain:sevn.gateway.token}"}}',
        ...         encoding="utf-8",
        ...     )
        ...     _ = seed_narrative_templates(
        ...         sj,
        ...         {
        ...             "schema_version": 1,
        ...             "workspace_root": ".",
        ...             "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        ...         },
        ...     )
        ...     body = _patch_user_md_from_personality(root, fields={"Name": "Alex"})
        ...     "Alex" in body
        True
    """
    path = content_root / "USER.md"
    text = path.read_text(encoding="utf-8") if path.is_file() else load_template("USER.md")
    lines: list[str] = []
    for line in text.splitlines():
        if _USER_INCOMPLETE_MARKER in line:
            continue
        lines.append(line)
    user_fields = {
        "Name": fields.get("Name"),
        "Role": fields.get("Role"),
        "Timezone": fields.get("Timezone"),
        "Style": fields.get("Style"),
        "Language": fields.get("Language"),
    }
    for label, value in user_fields.items():
        if not value:
            continue
        if not _replace_user_md_field(lines, label, value):
            needle = f"**{label}:**"
            if not any(needle in line for line in lines):
                lines.append(f"- **{label}:** {value}")
    preferences = fields.get("Preferences")
    if (
        preferences
        and not _replace_user_md_preferences(lines, preferences)
        and not any(line.strip() == "## Preferences" for line in lines)
    ):
        lines.append("## Preferences")
        lines.append(f"- {preferences}")
    body = "\n".join(lines).strip() + "\n"
    if fields.get("Name"):
        return body
    if _USER_INCOMPLETE_MARKER in body:
        return body
    return f"{body.rstrip()}\n\n{_USER_INCOMPLETE_MARKER}\n"


def _replace_identity_section(lines: list[str], heading: str, value: str) -> bool:
    """Replace placeholder text under a ``##`` heading in ``IDENTITY.md``.

    Args:
        lines (list[str]): Markdown lines mutated in place.
        heading (str): Section heading without ``##`` (e.g. ``Vibe``).
        value (str): Replacement body text.

    Returns:
        bool: True when a placeholder line was replaced.

    Examples:
        >>> body = ["## Vibe", "_(calm)_"]
        >>> _replace_identity_section(body, "Vibe", "calm co-pilot")
        True
    """
    target = f"## {heading}"
    start = next((i for i, line in enumerate(lines) if line.strip() == target), None)
    if start is None:
        return False
    for idx in range(start + 1, len(lines)):
        stripped = lines[idx].strip()
        if stripped.startswith("## "):
            break
        if not stripped:
            continue
        if _is_markdown_placeholder(stripped):
            lines[idx] = value
            return True
        break
    return False


def _patch_identity_md_from_personality(
    content_root: Path, *, vibe: str | None, emoji: str | None
) -> str:
    """Apply wizard vibe/emoji fields to ``IDENTITY.md``.

    Args:
        content_root (Path): Workspace content root.
        vibe (str | None): Operator-chosen assistant vibe.
        emoji (str | None): Signature emoji.

    Returns:
        str: Patched markdown body.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> from sevn.onboarding.seed import load_template, render_template
        >>> with tempfile.TemporaryDirectory() as td:
        ...     root = Path(td)
        ...     _ = (root / "IDENTITY.md").write_text(
        ...         render_template(load_template("IDENTITY.md"), "Nova"),
        ...         encoding="utf-8",
        ...     )
        ...     body = _patch_identity_md_from_personality(root, vibe="calm", emoji="🌿")
        ...     "calm" in body and "🌿" in body
        True
    """
    path = content_root / "IDENTITY.md"
    text = path.read_text(encoding="utf-8") if path.is_file() else load_template("IDENTITY.md")
    lines = text.splitlines()
    if vibe and not _replace_identity_section(lines, "Vibe", vibe):
        lines.extend(["", "## Vibe", "", vibe])
    if emoji and not _replace_identity_section(lines, "Emoji", emoji):
        lines.extend(["", "## Emoji", "", emoji])
    return "\n".join(lines).strip() + "\n"


def _patch_soul_md_from_personality(content_root: Path, *, vibe: str | None) -> str | None:
    """Optionally annotate ``SOUL.md`` tone with onboarding vibe.

    Args:
        content_root (Path): Workspace content root.
        vibe (str | None): Operator-chosen assistant vibe.

    Returns:
        str | None: Patched body when ``vibe`` is set; else ``None``.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> from sevn.onboarding.seed import load_template, render_template
        >>> with tempfile.TemporaryDirectory() as td:
        ...     root = Path(td)
        ...     _ = (root / "SOUL.md").write_text(
        ...         render_template(load_template("SOUL.md"), "Nova"),
        ...         encoding="utf-8",
        ...     )
        ...     body = _patch_soul_md_from_personality(root, vibe="sharp analyst")
        ...     body is not None and "sharp analyst" in body
        True
    """
    if not vibe:
        return None
    path = content_root / "SOUL.md"
    if not path.is_file():
        return None
    lines = path.read_text(encoding="utf-8").splitlines()
    marker = "## Tone & Communication"
    note = f"- **Onboarding vibe:** {vibe}"
    if any(line.strip() == note for line in lines):
        return None
    start = next((i for i, line in enumerate(lines) if line.strip() == marker), None)
    if start is None:
        lines.extend(["", marker, "", note])
    else:
        insert_at = start + 1
        while insert_at < len(lines) and not lines[insert_at].strip():
            insert_at += 1
        lines.insert(insert_at, note)
    return "\n".join(lines).strip() + "\n"


def seed_personality_from_wizard(
    content_root: Path,
    merged: dict[str, Any],
) -> list[Path]:
    """Merge wizard ``onboarding.personality`` into workspace markdown files.

    Skips all writes when every personality field is empty (W8.5). Preserves
    ``<!-- sevn-bootstrap:user-incomplete -->`` until ``name`` is set (D11).
    Removes ``BOOTSTRAP.md`` only after a real operator name is written.

    Args:
        content_root (Path): Resolved workspace content root.
        merged (dict[str, Any]): Promoted workspace document.

    Returns:
        list[Path]: Markdown files written (empty when skipped).

    Examples:
        >>> import json
        >>> import tempfile
        >>> from pathlib import Path
        >>> from sevn.onboarding.seed import seed_narrative_templates, seed_personality_from_wizard
        >>> with tempfile.TemporaryDirectory() as td:
        ...     root = Path(td)
        ...     sj = root / "sevn.json"
        ...     merged = {
        ...         "schema_version": 1,
        ...         "workspace_root": ".",
        ...         "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        ...         "onboarding": {"personality": {"name": "Alex"}},
        ...     }
        ...     _ = sj.write_text(json.dumps(merged), encoding="utf-8")
        ...     _ = seed_narrative_templates(sj, merged)
        ...     written = seed_personality_from_wizard(root, merged)
        ...     any(p.name == "USER.md" for p in written)
        True
    """
    reject_package_checkout_content_root(content_root)
    draft = _personality_draft_from_merged(merged)
    if not draft:
        return []
    from sevn.tools.workspace_files import write_workspace_md

    user_fields: dict[str, str] = {}
    if name := draft.get("name"):
        user_fields["Name"] = name
    if role := draft.get("role"):
        user_fields["Role"] = role
    if timezone := draft.get("timezone"):
        user_fields["Timezone"] = timezone
    style = _combined_personality_text(draft.get("style"), draft.get("style_detail"))
    if style:
        user_fields["Style"] = style
    if language := draft.get("language"):
        user_fields["Language"] = language
    preferences = _combined_personality_text(
        draft.get("preferences"),
        draft.get("preferences_detail"),
    )
    if preferences:
        user_fields["Preferences"] = preferences
    vibe = draft.get("vibe")
    emoji = draft.get("emoji")
    written: list[Path] = []
    if user_fields:
        user_body = _patch_user_md_from_personality(content_root, fields=user_fields)
        written.append(write_workspace_md(content_root, "USER.md", user_body))
    identity_body = _patch_identity_md_from_personality(content_root, vibe=vibe, emoji=emoji)
    if vibe or emoji:
        written.append(write_workspace_md(content_root, "IDENTITY.md", identity_body))
    soul_body = _patch_soul_md_from_personality(content_root, vibe=vibe)
    if soul_body is not None:
        written.append(write_workspace_md(content_root, "SOUL.md", soul_body))
    if draft.get("name"):
        bootstrap = content_root / "BOOTSTRAP.md"
        if bootstrap.is_file():
            bootstrap.unlink()
    return written


def refresh_bundled_core_skills(content_root: Path) -> list[str]:
    """Replace workspace ``skills/core/<id>`` trees from the shipped bundled packages.

    Unlike :func:`seed_bundled_skills`, existing packages are removed and recopied so
    operator sync picks up script fixes (for example renamed skill scripts).

    Opt-in core skills (``computer-use``, ``cursor_cloud``) are refreshed only when
    already present under ``skills/core/``.

    Args:
        content_root (Path): Resolved workspace content root.

    Returns:
        list[str]: Skill ids whose on-disk trees were replaced.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> from sevn.onboarding.seed import refresh_bundled_core_skills, seed_bundled_skills
        >>> td = Path(tempfile.mkdtemp())
        >>> _ = seed_bundled_skills(td)
        >>> isinstance(refresh_bundled_core_skills(td), list)
        True
    """
    reject_package_checkout_content_root(content_root)
    bundled_core = BUNDLED_SKILLS_ROOT / "core"
    if not bundled_core.is_dir():
        return []
    dest_root = content_root / "skills" / "core"
    dest_root.mkdir(parents=True, exist_ok=True)
    refreshed: list[str] = []
    for src_pkg in sorted(bundled_core.iterdir()):
        if not src_pkg.is_dir():
            continue
        skill_id = src_pkg.name
        if skill_id in _OPT_IN_CORE_SKILL_IDS and not (dest_root / skill_id).exists():
            continue
        dest_pkg = dest_root / skill_id
        if dest_pkg.exists():
            shutil.rmtree(dest_pkg)
        shutil.copytree(
            src_pkg,
            dest_pkg,
            ignore=lambda _dir, names: {name for name in names if name == "__pycache__"},
        )
        refreshed.append(skill_id)
    ensure_workspace_index(content_root)
    return refreshed


__all__ = [
    "NARRATIVE_TEMPLATE_NAMES",
    "ensure_skills_user_dir",
    "expected_core_skill_ids",
    "list_deployed_core_skill_ids",
    "load_personality_presets",
    "load_template",
    "opt_in_skill_ids_from_capabilities",
    "refresh_bundled_core_skills",
    "render_template",
    "resolve_agent_display_name",
    "seed_bundled_skills",
    "seed_narrative_templates",
    "seed_personality_from_wizard",
    "seed_tracing_defaults",
    "verify_core_skills_deployed",
]
