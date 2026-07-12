"""Wave W10: architecture grounding doc + anti-fabrication / brevity prompts.

Covers:
- The packaged ``SEVN-ARCHITECTURE.md`` lists the real LLM-calling files and
  contains none of the previously fabricated names.
- The anti-fabrication, brevity, and Telegram-formatting prompt text is present
  and wired into the tier-B prompt builders.
- ``SEVN-ARCHITECTURE.md`` seeds copy-if-absent like the other narrative templates.
"""

from __future__ import annotations

import json
from pathlib import Path

from sevn.onboarding.seed import (
    NARRATIVE_TEMPLATE_NAMES,
    load_template,
    seed_narrative_templates,
)
from sevn.prompts.tier_b import (
    tier_b_architecture_context_prompt,
    tier_b_brevity_prompt,
    tier_b_hallucination_guard_prompt,
    tier_b_no_preamble_echo_prompt,
    tier_b_retrieval_honesty_prompt,
    tier_b_telegram_formatting_prompt,
)

# The complete, real set of files that issue an LLM request (fact-checked
# against the checkout 2026-05-30 / W10.1).
_REAL_LLM_FILES = (
    "src/sevn/agent/triager/run.py",
    "src/sevn/agent/adapters/tier_b_model.py",
    "src/sevn/agent/executors/cd_harness.py",
    "src/sevn/security/llm_guard_scanner.py",
    "src/sevn/lcm/compaction.py",
    "src/sevn/memory/dreaming/scorer.py",
    "src/sevn/memory/user_model/extractor.py",
    "src/sevn/config/llm_params.py",
)

# Names the bot previously hallucinated; none of these exist.
_FABRICATED_NAMES = (
    "llm/gateway.py",
    "LlmGateway",
    "OpenAiLlm",
    "AnthropicLlm",
    "LLM_TRIAGER_",
    "GPT-4o",
)


def test_architecture_doc_lists_real_llm_files() -> None:
    doc = load_template("SEVN-ARCHITECTURE.md")
    for path in _REAL_LLM_FILES:
        assert path in doc, path


def test_architecture_doc_has_no_fabricated_names() -> None:
    doc = load_template("SEVN-ARCHITECTURE.md")
    # The doc may *name* the fabricated items in its "do not exist" warning, but
    # only inside the explicit negative section. Assert they never appear as a
    # claimed real path/class in the request-flow / LLM-files sections.
    files_section, _, _ = doc.partition("## Names that do not exist")
    for bad in _FABRICATED_NAMES:
        assert bad not in files_section, bad


def test_architecture_doc_real_set_is_authoritative() -> None:
    # Mention "the only" / complete-set language so the model treats it as closed.
    doc = load_template("SEVN-ARCHITECTURE.md")
    assert "only" in doc.lower()
    assert "Which files actually call an LLM" in doc


def test_hallucination_guard_has_anti_fabrication_rule() -> None:
    block = tier_b_hallucination_guard_prompt()
    assert "Self-architecture honesty" in block
    assert "SEVN-ARCHITECTURE.md" in block
    assert "general knowledge" in block
    assert "LlmGateway" in block


def test_github_repo_eval_prompt_covers_clone_and_readme() -> None:
    from sevn.prompts.tier_b import tier_b_github_repo_eval_prompt

    block = tier_b_github_repo_eval_prompt()
    assert "git clone" in block
    assert "README" in block
    assert "skill_management" in block


def test_workspace_code_search_prompt_classifies_scope() -> None:
    from sevn.prompts.tier_b import tier_b_workspace_code_search_prompt

    block = tier_b_workspace_code_search_prompt()
    assert "Workspace vs code file search" in block
    assert "LLM_params_config.json" in block
    assert "source_code/" in block
    assert "list_dir" in block
    assert 'search_in_file(path=".")' in block
    assert "asyncio" not in block  # CodeMode example lives in codemode playbook


def test_list_registry_playbook_present() -> None:
    from sevn.prompts.tier_b import tier_b_list_registry_playbook_prompt

    block = tier_b_list_registry_playbook_prompt()
    assert "list_registry playbook" in block
    assert "load_tool" in block
    assert "do you have" in block
    assert "meta_loaders.py" in block


def test_last30days_playbook_present() -> None:
    from sevn.prompts.tier_b import (
        tier_b_last30days_playbook_prompt,
        tier_b_triager_bound_mandate_prompt,
    )

    block = tier_b_last30days_playbook_prompt()
    assert "last30days playbook" in block
    assert "references/contract.md" in block
    assert "run_skill_script" in block
    mandate = tier_b_triager_bound_mandate_prompt(
        ["load_skill", "list_registry"],
        ["last30days"],
    )
    assert "skill_md_path" in mandate
    assert "last30days" in mandate


def test_retrieval_honesty_has_capability_verification_rule() -> None:
    block = tier_b_retrieval_honesty_prompt()
    # Capability-honesty: must verify via the registry before denying a capability.
    assert "Capability honesty" in block
    assert "list_registry" in block
    assert "no live web access" in block
    # Directory questions must go through list_dir / glob, not memory.
    assert "list_dir" in block
    assert "glob" in block


def test_pdf_file_pipeline_routing_provisions_discovery_tools() -> None:
    """P3: triager must not narrow PDF/file pipelines to send_file-only surfaces."""
    from sevn.agent.triager.models import ComplexityTier, Intent, TriageResult
    from sevn.agent.triager.routing_policy import apply_routing_policy, is_pdf_file_pipeline_message

    msg = "render the markdown to PDF and send it"
    assert is_pdf_file_pipeline_message(msg)
    parsed = TriageResult(
        intent=Intent.NEW_REQUEST,
        complexity=ComplexityTier.B,
        first_message="On it.",
        tools=["run_skill_script", "send_file"],
        skills=["pdf"],
        mcp_servers_required=[],
        confidence=0.9,
        requires_vision=False,
        requires_document=False,
    )
    out = apply_routing_policy(parsed, current_message=msg, turn_id="arch-pdf")
    assert "glob" in out.tools
    assert "terminal_run" in out.tools
    assert "get_page_content" in out.tools


def test_retrieval_honesty_has_source_grounded_body_rule() -> None:
    # P5: long-form body content must come from a retrieved artifact, not memory.
    block = tier_b_retrieval_honesty_prompt()
    assert "Source-grounded body content" in block
    # The fabrication-from-memory ban is explicit for convert/extract/summarize tasks.
    assert "regenerate the content from training memory" in block
    lowered = block.lower()
    assert "convert / extract / summarize" in lowered
    # Unsupported additions must be flagged Unverified.
    assert "**Unverified**" in block
    # The pass-through / no-rewrite recipe for render-to-PDF intents is present.
    assert "pass the fetched file straight through" in block.lower()
    assert "get_page_content url=… save_to=out/page.md" in block
    assert "scripts/pdf.py --out out/page.pdf --markdown-file out/page.md" in block
    # Spilled sources must be read, not reconstructed from the URL.
    assert "spill_path" in block


def test_brevity_prompt_present() -> None:
    block = tier_b_brevity_prompt()
    assert "Answer first" in block
    assert "self-flagellation" in block.lower()
    assert "preamble" in block.lower()


def test_telegram_formatting_prompt_present() -> None:
    block = tier_b_telegram_formatting_prompt()
    assert "table" in block.lower()
    assert "newline" in block.lower()


def test_no_preamble_echo_requires_substantive_final() -> None:
    # P2: the strengthened no-preamble-echo block must require a substantive final
    # message and forbid shipping a bare opener / parroted user phrase.
    block = tier_b_no_preamble_echo_prompt()
    lowered = block.lower()
    assert "final message must contain the substantive answer" in lowered
    assert "bare acknowledgement" in lowered
    assert "render that result" in lowered
    # Echoing the user's own words back at them is called out explicitly.
    assert "echo of the user's own words" in lowered
    # The discard contract is stated so the model knows an opener-only ships nothing.
    assert "treated as no answer" in lowered


def test_architecture_context_prompt_reads_workspace_copy(tmp_path: Path) -> None:
    (tmp_path / "SEVN-ARCHITECTURE.md").write_text(
        "# arch\nworkspace ground truth here\n",
        encoding="utf-8",
    )
    out = tier_b_architecture_context_prompt(tmp_path)
    assert "self-architecture ground truth" in out
    assert "workspace ground truth here" in out


def test_architecture_context_prompt_falls_back_to_template() -> None:
    out = tier_b_architecture_context_prompt(Path("/nonexistent-ws"))
    # Falls back to the packaged template, so the real LLM files are still present.
    assert "src/sevn/config/llm_params.py" in out


def test_architecture_doc_registered_in_narrative_templates() -> None:
    assert "SEVN-ARCHITECTURE.md" in NARRATIVE_TEMPLATE_NAMES


def test_architecture_doc_seeds_copy_if_absent(tmp_path: Path) -> None:
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "workspace_root": ".",
                "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
            }
        ),
        encoding="utf-8",
    )
    merged = {
        "schema_version": 1,
        "workspace_root": ".",
        "agent": {"display_name": "X"},
        "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
    }
    written = seed_narrative_templates(sevn_json, merged)
    names = {p.name for p in written}
    assert "SEVN-ARCHITECTURE.md" in names
    seeded = (tmp_path / "SEVN-ARCHITECTURE.md").read_text(encoding="utf-8")
    assert "Which files actually call an LLM" in seeded


def test_architecture_doc_seed_skips_existing(tmp_path: Path) -> None:
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "workspace_root": ".",
                "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "SEVN-ARCHITECTURE.md").write_text("operator edited arch", encoding="utf-8")
    written = seed_narrative_templates(
        sevn_json,
        {
            "schema_version": 1,
            "workspace_root": ".",
            "agent": {"display_name": "X"},
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        },
    )
    assert all(p.name != "SEVN-ARCHITECTURE.md" for p in written)
    assert (tmp_path / "SEVN-ARCHITECTURE.md").read_text(encoding="utf-8") == "operator edited arch"
