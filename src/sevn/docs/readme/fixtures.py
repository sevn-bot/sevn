"""Deterministic fixture contexts for offline README template preview.

Module: sevn.docs.readme.fixtures
Depends: (none)

Exports:
    FIXTURE_CONTEXTS — one render context dict per §C0 profile.

Examples:
    >>> from sevn.docs.readme.fixtures import FIXTURE_CONTEXTS
    >>> FIXTURE_CONTEXTS["root"]["profile"]
    'root'
    >>> "summary" in FIXTURE_CONTEXTS["subsystem"]
    True
"""

from __future__ import annotations

from typing import Any

_FIXTURE_SUBSYSTEM_MAP: list[dict[str, str]] = [
    {
        "slug": "gateway",
        "title": "Gateway",
        "summary": "FastAPI control plane: channels, sessions, turn spine.",
        "profile": "subsystem",
        "path": "docs/readmes/gateway.md",
    },
    {
        "slug": "agent",
        "title": "Agent runtime",
        "summary": "Triager, tier-B/C executors, harness discipline.",
        "profile": "subsystem",
        "path": "docs/readmes/agent.md",
    },
    {
        "slug": "tools",
        "title": "Tools registry",
        "summary": "Curated inventory of @sevn_tool plugins.",
        "profile": "catalog",
        "path": "docs/readmes/tools.md",
    },
]

FIXTURE_CONTEXTS: dict[str, dict[str, Any]] = {
    "root": {
        "slug": "root",
        "profile": "root",
        "title": "sevn.bot",
        "intro_lines": [
            "I'm Sevn. I'm more than a bot,",
            "or an Assistant, AI or not.",
            "I'm Sevn, I can be what you want,",
            "Agentic, attentive, shaped to your intent.",
            "I'm not perfect, I know, but I'm working on it,",
            "I will get better every day, as we keep turning it.",
            "Mostly Python, but also a harness,",
            "a model or many, to serve you or somebody.",
            "Tools when you need hands, quiet when you don't,",
            "Your gateway, your rules — I run where you chose.",
        ],
        "tagline": "I'm Sevn. I'm more than a bot,",
        "package_version": "0.0.1",
        "repo_owner": "sevn-bot",
        "repo_name": "sevn",
        "value_prop": (
            "sevn.bot is a personal AI gateway you run on your own machine — "
            "channels, triage, tier-B/C executors, tools, skills, and workspace "
            "memory under operator control."
        ),
        "highlights": list(
            (
                "Chat on Telegram, in your browser, or by voice — one assistant, many ways to reach it",
                "Runs on your machine — you choose the AI models and keep control of your data",
                "Remembers context across conversations so you do not have to repeat yourself",
                "Built-in safety checks help catch risky requests before they run",
                "Mission Control dashboard shows what Sevn is doing and lets you steer active tasks",
                "Automations and scheduled triggers can run work even when you are not chatting",
                "Grows with you through skills, tools, and workspace memory you control",
            )
        ),
        "architecture_bullets": [
            "Turn spine: channel → gateway → triage → executor → tools/skills → reply",
            "Secrets and LLM calls route through the paired egress proxy",
            "SQLite storage, configurable tracing sinks, and workspace-scoped memory",
        ],
        "subsystem_entries": _FIXTURE_SUBSYSTEM_MAP,
        "quick_start": (
            "**Clone and onboard**\n\n"
            "```bash\n"
            "git clone https://github.com/sevn-bot/sevn.git\n"
            "cd sevn\n"
            "make setup\n"
            "sevn onboard\n"
            "sevn doctor\n"
            "```\n\n"
            "`make setup` syncs dependencies, installs pre-commit hooks, and puts the "
            "`sevn` CLI on your PATH (via uv). Do **not** hand-edit `sevn.json` for "
            "first-time setup — run **`sevn onboard`** (web wizard by default; "
            "`sevn onboard --cli` for the terminal UI). It writes workspace config, "
            "secrets, and optional daemon units.\n\n"
            "After onboarding, use the **`sevn` CLI** for everyday operations: "
            "`sevn doctor`, `sevn gateway start`, `sevn sync --latest`, etc."
        ),
        "install_steps": [
            "Clone this repository",
            "From the repo root, run **`make setup`** — installs **uv** when missing, fetches **Python 3.12+** via uv (see `.python-version`), syncs dependencies, and puts the `sevn` CLI on PATH",
            "Run **`sevn onboard`** to configure your workspace (replaces manual `sevn.json` editing; installs gateway/proxy daemons by default)",
            "Run **`sevn doctor`** to confirm the install is healthy",
        ],
    },
    "subsystem": {
        "slug": "gateway",
        "profile": "subsystem",
        "title": "Gateway",
        "role": "FastAPI control plane for channels, sessions, and the turn spine",
        "summary": (
            "The gateway is sevn.bot's FastAPI control plane: it accepts channel "
            "messages, manages sessions and queues, and orchestrates the triage → "
            "executor turn spine."
        ),
        "spec_path": "specs/17-gateway.md",
        "source_dir": "src/sevn/gateway/",
        "level1": (
            "The gateway is the front door for every operator interaction. It "
            "accepts messages from Telegram and other channels, keeps session state, "
            "and hands work to the agent runtime without exposing provider keys."
        ),
        "level2": (
            "Key modules include `agent_turn.py` (turn orchestration), channel "
            "adapters under `channels/`, and FastAPI routes for Mission Control. "
            "Configuration comes from `sevn.json`; tracing events flow to configured sinks."
        ),
        "level3": (
            "Primary entry: `src/sevn/gateway/agent_turn.py`. Session queue and steer "
            "logic live alongside channel webhook handlers. See "
            "`src/sevn/gateway/__init__.py` for the public surface."
        ),
        "references": [
            "specs/17-gateway.md",
            "docs/readmes/agent.md",
            "about-sevn.bot/ARCHITECTURE.md",
        ],
    },
    "index": {
        "slug": "index",
        "profile": "index",
        "title": "README catalog",
        "entries": [
            {
                "slug": "gateway",
                "title": "Gateway",
                "summary": "FastAPI control plane: channels, sessions, turn spine.",
                "profile": "subsystem",
                "path": "docs/readmes/gateway.md",
                "status": "placeholder",
            },
            {
                "slug": "agent",
                "title": "Agent runtime",
                "summary": "Triager, tier-B/C executors, harness discipline.",
                "profile": "subsystem",
                "path": "docs/readmes/agent.md",
                "status": "placeholder",
            },
        ],
    },
    "catalog": {
        "slug": "tools",
        "profile": "catalog",
        "title": "Tools registry",
        "summary": (
            "Curated inventory of @sevn_tool plugins, adapters, and permission gates "
            "shipped with sevn.bot."
        ),
        "items": [
            {
                "name": "read_file",
                "path": "src/sevn/tools/file_ops/read.py",
                "summary": "Read workspace files within operator boundaries.",
            },
            {
                "name": "web_fetch",
                "path": "src/sevn/tools/web_fetch.py",
                "summary": "HTTP fetch via egress proxy with size limits.",
            },
        ],
    },
    "guide": {
        "slug": "onboarding",
        "profile": "guide",
        "title": "Onboarding",
        "summary": (
            "Operator setup: CLI, web wizard, Telegram flows, daemon install, "
            "and onboarding profiles."
        ),
        "steps": [
            {
                "heading": "Prerequisites",
                "body": "Python 3.12+, uv, and network access for initial sync.",
            },
            {
                "heading": "First run",
                "body": "Run `sevn onboard` or the web wizard; validate with `sevn doctor`.",
            },
        ],
        "references": ["specs/22-onboarding.md", "specs/23-cli.md"],
    },
    "freeform": {
        "slug": "example",
        "profile": "freeform",
        "title": "Example freeform README",
        "summary": (
            "Escape hatch profile for one-off READMEs whose shape does not fit "
            "subsystem, catalog, or guide templates."
        ),
        "body": (
            "This section is freeform prose. The checker validates Summary, "
            "GitHub-safe rendering, and link resolution only."
        ),
    },
}
