"""First-session intro slim prompt composition, persona, and size budget.

Covers:
- ``build_tier_b_intro_prompt_parts`` assembles exactly the D3 KEEP blocks and
  excludes the D4 DROP blocks (``specs/14-executor-tier-b.md`` §10.18).
- ``load_persona_block_intro`` includes IDENTITY/SOUL/USER and omits AGENTS.md (D2).
- Joined ``system_prompt`` stays under 55k chars on the bundled-template fixture
  (stretch goal <50k; measured baseline ~20.3k, 2026-06-03).
- ``build_intro_extra_instructions`` (W2 gateway helper) excludes repo-access,
  orientation, and self-arch text and includes the FIRST_SESSION_INTRO marker (D5).
- W6 (F9): intro instructions reference ``write`` (always-invokable) not
  ``write_workspace_md`` (lazy stub); protocol + tooling agree.

References:
    specs/14-executor-tier-b.md §10.18 (intro slim prompt profile)
    specs/17-gateway.md §10.23 (gateway extras trim on first-session intro)
    plan/first-session-intro-slim-agents-hub-wave-plan.md - locked decisions D2-D5, D10
    plan/live-session-eager-hydration-serp-recurrence-wave-plan.md W6 (F9)
"""

from __future__ import annotations

from pathlib import Path

from sevn.agent.adapters.tier_b_tools import _ALWAYS_INVOKABLE_FILE_OPS
from sevn.agent.persona import build_tier_b_intro_prompt_parts
from sevn.config.workspace_config import WorkspaceConfig
from sevn.gateway.agent_turn import build_intro_extra_instructions
from sevn.gateway.first_session import bootstrap_capture_instructions, tier_b_intro_instructions

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_WS = WorkspaceConfig(schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"})


def _join(parts: list[str]) -> str:
    """Mirror run_b_turn's join idiom."""
    return "\n\n".join(p for p in parts if p.strip())


# ---------------------------------------------------------------------------
# W3.1 — D3 KEEP blocks are present
# ---------------------------------------------------------------------------


def test_intro_prompt_contains_persistence_marker(tmp_path: Path) -> None:
    """tier_b_persistence_prompt is in the intro prompt (D3 KEEP)."""
    parts = build_tier_b_intro_prompt_parts(tmp_path)
    joined = _join(parts)
    # stable literal from tier_b_persistence_prompt body
    assert "Tool-error persistence" in joined
    assert "next viable" in joined


def test_intro_prompt_contains_hallucination_guard_marker(tmp_path: Path) -> None:
    """tier_b_hallucination_guard_prompt is in the intro prompt (D3 KEEP)."""
    parts = build_tier_b_intro_prompt_parts(tmp_path)
    joined = _join(parts)
    # from hallucination guard heading + body
    assert "do_not_reconstruct" in joined
    assert "Tool inventory rules" in joined


def test_intro_prompt_contains_tools_vs_skills_marker(tmp_path: Path) -> None:
    """tier_b_tools_vs_skills_prompt is in the intro prompt (D3 KEEP)."""
    parts = build_tier_b_intro_prompt_parts(tmp_path)
    joined = _join(parts)
    assert "Tools vs Skills" in joined
    assert "run_skill_runnable" in joined


# ---------------------------------------------------------------------------
# W3.1 — D4 DROP blocks are absent
# ---------------------------------------------------------------------------


def test_intro_prompt_excludes_sevn_architecture(tmp_path: Path) -> None:
    """tier_b_architecture_context_prompt is dropped on intro (D4)."""
    # Write a minimal SEVN-ARCHITECTURE.md so the block *would* produce content
    # if it were included -- then confirm it is absent.
    arch_path = tmp_path / "SEVN-ARCHITECTURE.md"
    arch_path.write_text("## SEVN-ARCHITECTURE\nGround truth doc.", encoding="utf-8")
    parts_with_file = build_tier_b_intro_prompt_parts(tmp_path)
    joined_with_file = _join(parts_with_file)
    assert "SEVN-ARCHITECTURE.md (self-architecture ground truth)" not in joined_with_file


def test_intro_prompt_excludes_sessions_context(tmp_path: Path) -> None:
    """tier_b_sessions_context_prompt is dropped on intro (D4)."""
    # Write a SESSIONS.md so the block would produce content if included.
    sessions_path = tmp_path / "SESSIONS.md"
    sessions_path.write_text(
        "## SESSIONS.md recall guide\nUse history() to recall past sessions.",
        encoding="utf-8",
    )
    parts = build_tier_b_intro_prompt_parts(tmp_path)
    joined = _join(parts)
    # The sessions context block wraps body under "SESSIONS.md (session recall)".
    assert "SESSIONS.md (session recall)" not in joined


def test_intro_prompt_excludes_log_query_playbook(tmp_path: Path) -> None:
    """tier_b_log_query_playbook_prompt is dropped on intro (D4)."""
    parts = build_tier_b_intro_prompt_parts(tmp_path)
    joined = _join(parts)
    # stable literal from log_query playbook heading
    assert "log_query playbook" not in joined
    assert "offset_from_tail" not in joined


def test_intro_prompt_excludes_index_architecture(tmp_path: Path) -> None:
    """tier_b_index_architecture_prompt is dropped on intro (D4)."""
    parts = build_tier_b_intro_prompt_parts(tmp_path)
    joined = _join(parts)
    # stable literal from tier_b_index_architecture_prompt
    assert "Architecture questions via the code index" not in joined
    assert "graphify query" not in joined


def test_intro_prompt_excludes_repo_access_playbook(tmp_path: Path) -> None:
    """tier_b_repo_access_prompt (source_code/ mirror playbook) is dropped on intro (D4)."""
    parts = build_tier_b_intro_prompt_parts(tmp_path)
    joined = _join(parts)
    # stable literal from tier_b_repo_access_prompt heading
    assert "sevn.bot source access (use for any code or gateway question)" not in joined


# ---------------------------------------------------------------------------
# W3.2 — Intro persona includes IDENTITY/SOUL/USER and excludes AGENTS.md (D2)
# ---------------------------------------------------------------------------


def test_intro_persona_includes_identity_md(tmp_path: Path) -> None:
    """load_persona_block_intro includes ## IDENTITY.md marker (D2 KEEP)."""
    (tmp_path / "IDENTITY.md").write_text("Name: TestBot", encoding="utf-8")
    parts = build_tier_b_intro_prompt_parts(tmp_path)
    joined = _join(parts)
    assert "## IDENTITY.md" in joined
    assert "TestBot" in joined


def test_intro_persona_includes_user_md(tmp_path: Path) -> None:
    """load_persona_block_intro includes ## USER.md marker (D2 KEEP)."""
    (tmp_path / "USER.md").write_text("Name: Alice\nTimezone: UTC", encoding="utf-8")
    parts = build_tier_b_intro_prompt_parts(tmp_path)
    joined = _join(parts)
    assert "## USER.md" in joined


def test_intro_persona_includes_soul_md(tmp_path: Path) -> None:
    """load_persona_block_intro includes ## SOUL.md marker (D2 KEEP)."""
    (tmp_path / "SOUL.md").write_text("Tone: warm and helpful", encoding="utf-8")
    parts = build_tier_b_intro_prompt_parts(tmp_path)
    joined = _join(parts)
    assert "## SOUL.md" in joined


def test_intro_persona_excludes_agents_md(tmp_path: Path) -> None:
    """load_persona_block_intro does NOT include ## AGENTS.md (D2 DROP)."""
    # Write an AGENTS.md that would appear if it were included.
    (tmp_path / "AGENTS.md").write_text(
        "# AGENTS\nfull agents hub content marker-unique-string",
        encoding="utf-8",
    )
    parts = build_tier_b_intro_prompt_parts(tmp_path)
    joined = _join(parts)
    assert "## AGENTS.md" not in joined
    assert "full agents hub content marker-unique-string" not in joined


# ---------------------------------------------------------------------------
# W3.3 — Size budget: joined system_prompt < 55k on bundled templates (D10)
# ---------------------------------------------------------------------------


def test_intro_system_prompt_size_under_55k(tmp_path: Path) -> None:
    """Intro joined system_prompt < 55,000 chars on template-fallback fixture.

    Stretch goal: < 50,000 chars.
    Measured baseline (2026-06-03, bundled templates): ~20,328 chars.
    A regression above 55k indicates a D4 block was added back or a large
    template was included; above 50k is a soft warning (stretch goal).
    """
    parts = build_tier_b_intro_prompt_parts(tmp_path)
    joined = _join(parts)
    # Hard budget from D10
    assert len(joined) < 55_000, (
        f"Intro system_prompt size {len(joined):,} chars exceeds 55k hard budget. "
        "Check that no D4 blocks were re-added to build_tier_b_intro_prompt_parts."
    )
    # Stretch goal documented here — not a hard assertion; see D10 commentary.
    # Baseline: ~20,328 chars with bundled IDENTITY/SOUL/USER templates (2026-06-03).
    # If this number creeps above 50k, investigate which persona file or block grew.


def test_intro_prompt_has_ten_parts(tmp_path: Path) -> None:
    """build_tier_b_intro_prompt_parts returns exactly 10 parts (9 static + persona)."""
    parts = build_tier_b_intro_prompt_parts(tmp_path)
    assert len(parts) == 10


# ---------------------------------------------------------------------------
# W3.4 — build_intro_extra_instructions excludes orientation/repo/self-arch (D5)
# ---------------------------------------------------------------------------


def test_intro_extra_instructions_contains_first_session_intro_marker(tmp_path: Path) -> None:
    """build_intro_extra_instructions includes the FIRST_SESSION_INTRO marker (D5 KEEP)."""
    parts = build_intro_extra_instructions(workspace=_WS, bootstrap_body=None)
    joined = "\n\n".join(p for p in parts if p.strip())
    assert "FIRST_SESSION_INTRO" in joined


def test_intro_extra_instructions_excludes_repo_access_playbook(tmp_path: Path) -> None:
    """build_intro_extra_instructions does NOT include source_code/ repo playbook (D5 DROP)."""
    parts = build_intro_extra_instructions(workspace=_WS, bootstrap_body=None)
    joined = "\n\n".join(p for p in parts if p.strip())
    # stable literal from tier_b_repo_access_prompt heading
    assert "sevn.bot source access" not in joined
    assert "source_code/" not in joined


def test_intro_extra_instructions_excludes_orientation_block(tmp_path: Path) -> None:
    """build_intro_extra_instructions does NOT include orientation block text (D5 DROP)."""
    parts = build_intro_extra_instructions(workspace=_WS, bootstrap_body=None)
    joined = "\n\n".join(p for p in parts if p.strip())
    # orientation_block_for_workspace emits workspace-root orientation text
    # with a heading like "## Workspace orientation" or checkout-specific content.
    # A safe stable marker is the checkout-specific heading wording.
    assert "Workspace orientation" not in joined


def test_intro_extra_instructions_excludes_self_arch_inject(tmp_path: Path) -> None:
    """build_intro_extra_instructions does NOT include self-arch inject text (D5 DROP)."""
    parts = build_intro_extra_instructions(workspace=_WS, bootstrap_body=None)
    joined = "\n\n".join(p for p in parts if p.strip())
    # stable literal from tier_b_self_architecture_inject
    assert "Self-architecture turn (mandatory)" not in joined
    assert "zero grounding tool calls" not in joined


def test_intro_extra_instructions_includes_bootstrap_body(tmp_path: Path) -> None:
    """build_intro_extra_instructions includes the BOOTSTRAP.md body when provided."""
    parts = build_intro_extra_instructions(
        workspace=_WS,
        bootstrap_body="# BOOTSTRAP\nName: TestBot",
    )
    joined = "\n\n".join(p for p in parts if p.strip())
    assert "[BOOTSTRAP.md]" in joined
    assert "Name: TestBot" in joined


# ---------------------------------------------------------------------------
# W6 (F9) — protocol + tooling agreement: intro instructions reference write
# ---------------------------------------------------------------------------


def test_intro_instructions_reference_write_not_write_workspace_md() -> None:
    """tier_b_intro_instructions mandates ``write``, not ``write_workspace_md`` (W6/F9).

    The intro turn's triage.tools=[] causes full_index mode; ``write_workspace_md``
    is a lazy-stub there (not in any always-invokable set) and the model cannot
    call it without a ``load_tool`` ritual first.  ``write`` is always-invokable
    and always has its full schema — protocol and tooling must agree.
    """
    text = tier_b_intro_instructions(
        workspace=_WS,
        bootstrap_body=None,
    )
    assert "write_workspace_md" not in text, (
        "tier_b_intro_instructions still references write_workspace_md; "
        "the intro turn cannot call it without load_tool (it's a lazy stub)."
    )
    assert "``write``" in text, (
        "tier_b_intro_instructions must reference the ``write`` tool "
        "(always-invokable, full schema always available)."
    )


def test_bootstrap_capture_instructions_reference_write_not_write_workspace_md() -> None:
    """bootstrap_capture_instructions mandates ``write``, not ``write_workspace_md`` (W6/F9).

    Bootstrap follow-up turns share the same tooling constraint: ``write_workspace_md``
    is a lazy stub unless pre-seeded into loaded_tools.  ``write`` is always available.
    """
    text = bootstrap_capture_instructions(
        workspace=_WS,
        bootstrap_body=None,
    )
    assert "write_workspace_md" not in text, (
        "bootstrap_capture_instructions still references write_workspace_md."
    )
    assert "``write``" in text, "bootstrap_capture_instructions must reference the ``write`` tool."


def test_write_tool_is_always_invokable() -> None:
    """``write`` is in _ALWAYS_INVOKABLE_FILE_OPS — full schema always present (W6/F9).

    This is the load-bearing property: ``prepare_lazy_tool_definitions`` passes
    always-invokable names through with their real schema.  If ``write`` were ever
    removed from that set the intro bootstrap mandate would silently break again.
    """
    assert "write" in _ALWAYS_INVOKABLE_FILE_OPS, (
        "``write`` must remain in _ALWAYS_INVOKABLE_FILE_OPS so the intro turn "
        "can call it without a load_tool ritual."
    )


def test_write_workspace_md_not_in_always_invokable() -> None:
    """``write_workspace_md`` is NOT always-invokable — it requires load_tool (W6/F9).

    Documents why the protocol copy was changed: referencing a lazy-stub tool in
    mandatory instructions produces the F9 failure where the model reports it cannot
    call the tool despite it appearing registered in list_registry.
    """
    assert "write_workspace_md" not in _ALWAYS_INVOKABLE_FILE_OPS, (
        "Unexpected: write_workspace_md moved into _ALWAYS_INVOKABLE_FILE_OPS. "
        "If this is intentional, revert the W6 protocol-copy change and reference "
        "write_workspace_md in tier_b_intro_instructions instead."
    )
