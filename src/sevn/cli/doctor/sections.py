"""Doctor report section order and check-id mapping (`specs/23-cli.md` §3).

Module: sevn.cli.doctor.sections
Depends: typing

Exports:
    section_for — resolve section name for a check id.
    title_for — resolve display title for a check id.
    registered_check_ids — all check ids the doctor framework may emit.
"""

from __future__ import annotations

SECTION_ORDER: tuple[str, ...] = (
    "Workspace",
    "Gateway",
    "Secrets",
    "Channels",
    "Models/LLM",
    "Browser/Tools",
    "Voice",
    "Storage",
    "Optional extras",
)

CHECK_SECTIONS: dict[str, str] = {
    "sevn_json": "Workspace",
    "my_sevn": "Workspace",
    "code_orientation": "Workspace",
    "operator_lock": "Workspace",
    "llmignore": "Workspace",
    "sevn_cli": "Workspace",
    "gateway_token_configured": "Gateway",  # nosec B105 — doctor section label
    "proxy_healthz": "Gateway",
    "gateway_health": "Gateway",
    "gateway_ready": "Gateway",
    "secrets_backend": "Secrets",
    "keychain_unlock": "Secrets",
    "webapp_https": "Channels",
    "telegram_probe": "Channels",
    "llm_reachability": "Models/LLM",
    "provider_credentials": "Models/LLM",
    "openai_oauth_credential": "Models/LLM",
    "docker": "Browser/Tools",
    "browser_extra": "Browser/Tools",
    "browser_readiness": "Browser/Tools",
    "browser_cdp_engine": "Browser/Tools",
    "cua_cli_binary": "Browser/Tools",
    "cua_driver_binary": "Browser/Tools",
    "cua_tcc_accessibility": "Browser/Tools",
    "cua_tcc_automation": "Browser/Tools",
    "cua_tcc_screen_recording": "Browser/Tools",
    "lume_binary": "Browser/Tools",
    "openwiki_cli": "Browser/Tools",
    "openwiki_credentials": "Browser/Tools",
    "skillspector": "Browser/Tools",
    "skillspector_extra": "Browser/Tools",
    "pyodide_deno": "Browser/Tools",
    "voice_backends": "Voice",
    "sqlite": "Storage",
    "auto_run_on_import": "Optional extras",
    "extensions": "Optional extras",
    "pdf_weasyprint": "Optional extras",
    "pdf_extra": "Optional extras",
    "pp_espn": "Optional extras",
    "pp_flight_goat": "Optional extras",
    "pp_movie_goat": "Optional extras",
    "pp_recipe_goat": "Optional extras",
    "witchcraft_probe": "Optional extras",
    "second_brain_vault_layout": "Workspace",
    "subagents_registry": "Storage",
}

CHECK_TITLES: dict[str, str] = {
    "sevn_json": "sevn.json",
    "gateway_token_configured": "Gateway token",  # nosec B105 — check title
    "my_sevn": "my_sevn",
    "code_orientation": "Code orientation",
    "operator_lock": "Operator lock",
    "sevn_cli": "sevn CLI",
    "auto_run_on_import": "auto_run_on_import",
    "extensions": "Extensions",
    "sqlite": "SQLite",
    "secrets_backend": "Secrets backend",
    "keychain_unlock": "Keychain unlock",
    "webapp_https": "WebApp HTTPS",
    "docker": "Docker",
    "browser_extra": "Browser (Playwright)",
    "browser_readiness": "Browser readiness",
    "browser_cdp_engine": "Browser (CDP engine)",
    "cua_cli_binary": "cua CLI",
    "cua_driver_binary": "cua-driver",
    "cua_tcc_accessibility": "Cua Accessibility (TCC)",
    "cua_tcc_automation": "Cua Automation (TCC)",
    "cua_tcc_screen_recording": "Cua Screen Recording (TCC)",
    "lume_binary": "lume CLI",
    "openwiki_cli": "OpenWiki CLI",
    "openwiki_credentials": "OpenWiki credentials",
    "skillspector": "SkillSpector",
    "pyodide_deno": "Pyodide sandbox",
    "proxy_healthz": "Proxy /healthz",
    "llm_reachability": "LLM reachability",
    "provider_credentials": "Provider credentials",
    "openai_oauth_credential": "OpenAI OAuth (Codex)",
    "gateway_health": "Gateway /health",
    "gateway_ready": "Gateway /ready",
    "llmignore": ".llmignore",
    "pdf_weasyprint": "PDF (WeasyPrint)",
    "pdf_extra": "PDF extra",
    "pp_espn": "printing-press espn",
    "pp_flight_goat": "printing-press flight-goat",
    "pp_movie_goat": "printing-press movie-goat",
    "pp_recipe_goat": "printing-press recipe-goat",
    "voice_backends": "Voice backends",
    "witchcraft_probe": "Witchcraft",
    "second_brain_vault_layout": "Second Brain vault",
    "subagents_registry": "Sub-agents storage",
    "skillspector_extra": "SkillSpector CLI",
    "telegram_probe": "Telegram probe",
}

_DEFAULT_SECTION = "Optional extras"


def section_for(check_id: str) -> str:
    """Return the section name for a doctor check id.

    Args:
        check_id (str): Stable check identifier.

    Returns:
        str: Section heading from ``SECTION_ORDER``.

    Examples:
        >>> section_for("sevn_json")
        'Workspace'
        >>> section_for("unknown_check")
        'Optional extras'
    """
    return CHECK_SECTIONS.get(check_id, _DEFAULT_SECTION)


def title_for(check_id: str) -> str:
    """Return the human row title for a doctor check id.

    Args:
        check_id (str): Stable check identifier.

    Returns:
        str: Short title for Rich/plain doctor rows.

    Examples:
        >>> title_for("gateway_token_configured")
        'Gateway token'
        >>> title_for("custom_id")
        'custom_id'
    """
    return CHECK_TITLES.get(check_id, check_id)


def registered_check_ids() -> frozenset[str]:
    """Return all check ids the doctor framework may emit.

    Returns:
        frozenset[str]: Keys from ``CHECK_SECTIONS``.

    Examples:
        >>> "sevn_json" in registered_check_ids()
        True
    """
    return frozenset(CHECK_SECTIONS.keys())


__all__ = [
    "CHECK_SECTIONS",
    "CHECK_TITLES",
    "SECTION_ORDER",
    "registered_check_ids",
    "section_for",
    "title_for",
]
