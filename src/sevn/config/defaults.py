"""Non-workspace tunables (`Final` constants).

Module: sevn.config.defaults
Depends: (none)

Exports:
    SUPPORTED_SCHEMA_VERSIONS — ``schema_version`` values this binary accepts.
    DEFAULT_GATEWAY_HOST — loopback bind default.
    DEFAULT_GATEWAY_PORT — HTTP port when ``gateway.port`` omitted.
    DEFAULT_GATEWAY_QUEUE_MODE — inbound queue policy string.
    DEFAULT_SECRET_CACHE_TTL_SECONDS — in-memory decrypted cache TTL (``specs/06-secrets.md`` §5).
    DEFAULT_PROXY_SECRET_TTL_SECONDS — alias for ``DEFAULT_SECRET_CACHE_TTL_SECONDS`` (proxy).
    MIN_PBKDF2_ITERATIONS — floor for encrypted-file KDF (``specs/06-secrets.md`` §3.1).
    SECRET_FILE_FORMAT_VERSION — on-disk encrypted blob version.
    DEFAULT_ENCRYPTED_SECRET_STORE_NAME — default filename under ``.sevn/secrets/``.
    DEFAULT_MACOS_KEYCHAIN_SERVICE — macOS Keychain service name.
    DEFAULT_LINUX_SECRET_COLLECTION_LABEL — libsecret collection label.
    SANDBOX_MAX_CPU — Docker ``--cpus`` default (``specs/08-sandbox.md`` §5.1).
    SANDBOX_MAX_MEM_MB — RAM cap default (``specs/08-sandbox.md`` §5.1).
    SANDBOX_MAX_DISK_MB — writable layer cap default (``specs/08-sandbox.md`` §5.1).
    SANDBOX_MAX_PIDS — ``--pids-limit`` default (``specs/08-sandbox.md`` §5.1).
    SANDBOX_MAX_LIFETIME_S — sandbox / token TTL alignment (``specs/08-sandbox.md`` §5.1).
    SANDBOX_SNAPSHOT_INTERVAL_MIN — snapshot cadence minutes (``specs/08-sandbox.md`` §5.1).
    SANDBOX_SNAPSHOT_RETENTION_COUNT_DEFAULT — retained snapshot tarball count when unset (same §5).
    DEFAULT_SCANNER_PROVIDERS — scanner egress provider chain order (§09 §5).
    DEFAULT_SCANNER_TOXICITY_THRESHOLD — classifier toxicity score cutoff (§09 §5).
    DEFAULT_LLMIGNORE_REL_PATH — default ``.llmignore`` directory under the workspace.
    DEFAULT_LLMIGNORE_RETENTION_*_DAYS — per-subdir TTL defaults (§09 §3.2).
    DEFAULT_SCANNER_MODEL_* — default model ids for scanner chain entries (implementation).
    DEFAULT_TRIAGER_TIER_B_TOOL_CAP — Triager tier-B tool list cap default (`specs/10-schema-ontology.md` §5).
    DEFAULT_TRIAGER_TIER_B_SKILL_CAP — Triager tier-B skill list cap default (same).
    DEFAULT_TIER_B_RETRY_HISTORY_TURNS — windowed transcript cap for tier-B retry passes.
    LOADED_BODY_CACHE_DEFAULT_CAP — LRU slots for lazy ``load_*`` payloads (`specs/11-tools-registry.md` §3.2).
    TOOL_LARGE_RESULT_THRESHOLD_BYTES — spill threshold for tool JSON blobs (§3.1).
    LOAD_SKILL_MARKDOWN_INLINE_MAX_BYTES — inline ``markdown`` budget for menu ``load_skill``.
    TOOL_LARGE_RESULT_PREVIEW_CHARS — preview length hint for spill descriptors.
    INITIAL_REGISTRY_VERSION — baseline Triager/registry cache generation (§5).
    DEFAULT_TRIAGER_TIMEOUT_*_S — Triager latency staircase defaults (`specs/13-rlm-triager.md` §5).
    DEFAULT_COMPLEXITY_CLAMP_* — low-confidence C/D downgrade thresholds (`specs/13-rlm-triager.md`).
    DEFAULT_TIER_B_EXECUTOR_TIMEOUT_S — tier-B wall-clock cap per cascade step (`specs/17-gateway.md`).
    DEFAULT_TIER_CD_EXECUTOR_TIMEOUT_S — tier-C/D wall-clock cap per cascade step (same).
    DEFAULT_CASCADE_BUDGET_S — cumulative cascade wall-clock cap (same).
    TRIAGER_ENABLED_ENV_KEY — canonical env name for optional gateway Triager gating (`specs/13-rlm-triager.md` §10.1).
    TIER_B_MAX_ROUNDS — outer chat+tool iteration cap for tier-B (`specs/14-executor-tier-b.md` §5).
    TIER_B_MAX_ROUNDS_EXPANDED — expanded tier-B cap used when tier-C escalation is unavailable (same).
    TIER_B_TOOL_MAX_RETRIES — pydantic-ai per-tool retry budget for tier-B (default ``3``).
    TIER_B_TOOL_CALL_BUDGET — per-turn total tool-call cap before tier-B is steered to synthesize.
    TIER_B_COUNT_PLANNING — count planning-only LLM rounds against the budget (default ``False``, same).
    CD_OUTER_ROUNDS_MAX — C/D outer execute units per turn (`specs/21-executor-tier-cd.md` §4.5).
    CD_RLM_MAX_ITERATIONS — inner ``dspy.RLM`` iteration cap (same).
    CD_RLM_MAX_OUTPUT_CHARS — REPL stdout cap (same).
    CD_RLM_DEFAULT_MAX_LLM_CALLS — inner sub-LM call anchor before regime merge (same).
    DEFAULT_RLM_C_D_BACKEND — ``rlm.c_d_backend`` default (same §5).
    DEFAULT_RLM_REPL_LIFETIME — ``rlm.repl_lifetime`` default (`specs/08-sandbox.md` §4.6).
    DEFAULT_PLAN_APPROVAL_ENABLED — ``plan_approval.enabled`` default (`specs/21-executor-tier-cd.md` §5).
    DEFAULT_PLAN_APPROVAL_TTL_SECONDS — pending C/D plan approval TTL (same).
    DEFAULT_GATEWAY_AUTO_RESUME_B — tier-B boot auto-resume (`specs/16-harness-discipline.md` §4.2).
    DEFAULT_REPLAY_MAX_PER_DAY — turn replay cap (`specs/16-harness-discipline.md` §5).
    DEFAULT_HARNESS_SNAPSHOT_TRIAGER_TIER_A — optional triager-only checkpoints (§5).
    HARNESS_SNAPSHOT_GC_ORPHAN_MAX_AGE_NS — boot orphan GC age (`specs/16-harness-discipline.md` §2.2).
    HARNESS_ZOMBIE_MAX_CONCURRENT — zombie parallel drains (§4.4).
    HARNESS_ZOMBIE_MAX_PENDING — zombie queue depth cap (§4.4).
    HARNESS_ZOMBIE_TTL_S — per-zombie TTL seconds (§4.4).
    DEFAULT_LCM_* — lossless context defaults (`specs/15-memory-lcm.md` §5).
    DEFAULT_WEBCHAT_JWT_TTL_SECONDS — Web UI JWT TTL default (`specs/19-channel-webui.md` §2.3).
    DEFAULT_DASHBOARD_JWT_TTL_SECONDS — Mission Control JWT TTL default (§24 §2.2).
    DEFAULT_DASHBOARD_TRACE_LIMIT_MAX — Heavy trace-list pagination cap (§24 §2.3).
    DEFAULT_DASHBOARD_ADMIN_LIMIT_MAX — Small admin-list pagination cap (§24 §2.3).
    DEFAULT_WEBCHAT_AUTH_TIMEOUT_SECONDS — WS auth-frame deadline (`specs/19-channel-webui.md` §2.2).
    DEFAULT_WEBCHAT_TTS_INLINE — Web UI inline TTS default (`specs/19-channel-webui.md` §5).
    DEFAULT_WEBCHAT_PUBLIC — Web UI anonymous binding default (`specs/19-channel-webui.md` §5).
    DEFAULT_VOICE_STT_PROVIDERS — default STT chain tags (`specs/20-voice.md` §5).
    DEFAULT_VOICE_TTS_PROVIDERS — default TTS chain tags (same).
    DEFAULT_VOICE_LOCAL_TTS_ENGINE — default engine for ``text_to_voice`` (``kokoro`` / ``supertonic``).
    DEFAULT_VOICE_TRIGGER_KEYWORDS — ``when_asked`` word-boundary triggers (same).
    DEFAULT_VOICE_MAX_MB — inbound voice size cap (same).
    DEFAULT_VOICE_MAX_SECONDS — inbound voice duration cap (same).
    DEFAULT_VOICE_STT_CONFIDENCE_REPROMPT_THRESHOLD — low-confidence reprompt floor (same).
    DEFAULT_VOICE_TTS_TEMP_TTL_DAYS — orphan TTS file TTL hint (same).
    DEFAULT_VOICE_PRELOAD_LOCAL_TTS_ON_BOOT — optional local TTS warm (same).
    DEFAULT_VOICE_STT_WHISPER_MODEL — default GGML model size the whisper.cpp provisioner
        downloads (`build-plan-from-review/waves/voice-duplex-tts-menu-log-fixes-wave-plan.md` W2).
    VOICE_INBOUND_TRANSCRIPT_PREFIX — gateway prefix before quoted transcript (§2.3).
    ONBOARDING_TOKEN_TTL_SECONDS — ``onboard_token`` TTL for local web wizard (`specs/22-onboarding.md` §4.6).
    ONBOARDING_WIZARD_BIND_HOST — loopback bind default for ``sevn onboard --web`` (same).
    ONBOARDING_LOG_MAX_BYTES — soft cap hint for ``logs/onboard-*.log`` rotation (same §7).
    CLI_GATEWAY_GET_LIVENESS_TIMEOUT_S — cheap GET total timeout (`specs/23-cli.md` §2.3).
    CLI_GATEWAY_GET_DEFAULT_TIMEOUT_S — default JSON API GET timeout (same).
    CLI_GATEWAY_GET_MAX_RETRIES — idempotent GET retries after first attempt (same §2.3).
    CLI_GATEWAY_GET_RETRY_BACKOFF_S — sleep between GET retries in seconds (200 ms; same).
    DEFAULT_TRIGGERS_MAX_CONCURRENT — non-interactive run semaphore sizing (`specs/30-non-interactive-triggers.md` §5).
    DEFAULT_TRIGGERS_MAX_INLINE_BYTES — prompt spill threshold before `inbox` path (same).
    DEFAULT_TRIGGERS_WEBHOOK_DEDUPE_TTL_S — dedupe row retention (same §3.2 / PRD).
    DEFAULT_SELF_IMPROVE_* / SELF_IMPROVE_SAMPLER_* — self-improve sampler/job/eval defaults (`specs/33-self-improvement.md` §5).
    TRACE_ATTRS_JSON_MAX_BYTES — ``attrs_json`` size cap before truncate-with-marker (`specs/04-tracing.md` §10.7).
    DEFAULT_TRACE_TTL_DAYS — retention window for ``trace_events`` rows; lifespan purge job (same).
    DEFAULT_TRACE_ROLLUP_LOOKBACK_HOURS — hours of completed buckets to aggregate per rollup tick (same).
    DEFAULT_TRACE_REDACTION_ENABLED — ``tracing.redaction.enabled`` default (`specs/04-tracing.md` §2.5).
    DEFAULT_TRACE_REDACTION_DENY_KEYS — default sensitive attribute key substrings (same).
    DEFAULT_TRACE_REDACTION_DENY_VALUE_PATTERNS — default value regexes (same).
    DEFAULT_TRACING_REDACTION — bundled ``tracing.redaction`` object for docs / seed parity.
    DEFAULT_TRACING_SINKS — default ``tracing.sinks[]`` (sqlite + daily JSONL dir).
    DEFAULT_TURN_BUNDLES_ENABLED — ``diagnostics.turn_bundles.enabled`` default (off).
    DEFAULT_DIAGNOSTICS_TURN_BUNDLES — bundled ``diagnostics.turn_bundles`` object.

    Private:
    _doctest_phase0_anchor — Phase 0 doctest anchor for CI gates.
    >>> {1, 2} <= SUPPORTED_SCHEMA_VERSIONS
    True
    >>> SANDBOX_MAX_CPU
    2
    >>> LOADED_BODY_CACHE_DEFAULT_CAP
    64
"""

from __future__ import annotations

from typing import Final, Literal

DEFAULT_GATEWAY_HOST: Final[str] = "127.0.0.1"
DEFAULT_GATEWAY_PORT: Final[int] = 3001
DEFAULT_GATEWAY_QUEUE_MODE: Final[Literal["cancel", "steer"]] = "cancel"

# Gateway HTTP + session caps (`specs/17-gateway.md` §5; PRD 01 DM cap).
DEFAULT_GATEWAY_SESSION_MESSAGE_CAP_DM: Final[int] = 400
DEFAULT_GATEWAY_RATE_LIMIT_CAPACITY: Final[float] = 30.0
DEFAULT_GATEWAY_RATE_LIMIT_REFILL_PER_SECOND: Final[float] = 1.5
DEFAULT_GATEWAY_SHUTDOWN_DRAIN_TIMEOUT_S: Final[float] = 20.0

# ``dispatcher_callbacks`` dedupe row retention (`specs/17-gateway.md` §3.4).
DEFAULT_DISPATCHER_CALLBACKS_TTL_SECONDS: Final[int] = 7 * 24 * 3600

# WebChat channel knobs (`specs/19-channel-webui.md` §2.3, §2.6, §5).
DEFAULT_WEBCHAT_JWT_TTL_SECONDS: Final[int] = 3600
DEFAULT_WEBCHAT_AUTH_TIMEOUT_SECONDS: Final[float] = 10.0
DEFAULT_WEBCHAT_TTS_INLINE: Final[bool] = True
DEFAULT_WEBCHAT_PUBLIC: Final[bool] = False

# Mission Control / dashboard (`specs/24-dashboard.md` §2.2-§2.3, §5).
DEFAULT_DASHBOARD_JWT_TTL_SECONDS: Final[int] = 24 * 3600
DEFAULT_DASHBOARD_TRACE_LIMIT_MAX: Final[int] = 200
DEFAULT_DASHBOARD_ADMIN_LIMIT_MAX: Final[int] = 500
DEFAULT_DASHBOARD_PAGE_AGENT_ENABLED: Final[bool] = True

# Encrypted store + resolved cache (``specs/06-secrets.md``).
DEFAULT_SECRET_CACHE_TTL_SECONDS: Final[int] = 300
DEFAULT_PROXY_SECRET_TTL_SECONDS: Final[int] = DEFAULT_SECRET_CACHE_TTL_SECONDS
MIN_PBKDF2_ITERATIONS: Final[int] = 310_000
SECRET_FILE_FORMAT_VERSION: Final[int] = 1
DEFAULT_ENCRYPTED_SECRET_STORE_NAME: Final[str] = "store.enc"
DEFAULT_MACOS_KEYCHAIN_SERVICE: Final[str] = "dev.sevn.bot.secrets"
DEFAULT_LINUX_SECRET_COLLECTION_LABEL: Final[str] = "sevn.secrets"
# Encrypted-file unlock mechanism when ``secrets_backend.encrypted_file.key_source`` is unset.
# Passphrase by default: a bare ``SEVN_SECRETS_MASTER_KEY`` is inert unless ``key_source`` is
# explicitly ``master_key`` (``specs/06-secrets.md`` §5).
DEFAULT_ENCRYPTED_FILE_KEY_SOURCE: Final[str] = "passphrase"

# v2 is a no-shape-change bump for ``sevn migrate`` / backup tests (`specs/22-onboarding.md` §4.4).
SUPPORTED_SCHEMA_VERSIONS: Final[frozenset[int]] = frozenset({1, 2})

# LLM Guard / ``.llmignore`` (``specs/09-security-scanner.md`` §3, §5).
DEFAULT_SCANNER_PROVIDERS: Final[tuple[str, ...]] = ("local_ollama", "openai")
DEFAULT_SCANNER_TOXICITY_THRESHOLD: Final[float] = 0.9
DEFAULT_LLMIGNORE_REL_PATH: Final[str] = ".llmignore"
DEFAULT_LLMIGNORE_RETENTION_BLOCKED_DAYS: Final[int] = 90
DEFAULT_LLMIGNORE_RETENTION_QUARANTINE_DAYS: Final[int] = 30
DEFAULT_LLMIGNORE_RETENTION_INCIDENTS_DAYS: Final[int] = 7
# Inbound / feedback / tool-result UTF-8 payload cap before scan (``specs/09`` §10.2).
# Gateway max-message policy (``specs/17-gateway.md`` §10.7) must stay aligned with this default.
DEFAULT_SCANNER_MAX_INBOUND_BYTES: Final[int] = 524_288
# Default OpenAI-chat-shaped model ids for scanner provider chain (proxy resolves keys).
DEFAULT_SCANNER_MODEL_LOCAL_OLLAMA: Final[str] = "llama3"
DEFAULT_SCANNER_MODEL_OPENAI: Final[str] = "gpt-4o-mini"

# When true, all model slots inherit ``providers.tier_default.triager`` (``specs/02`` §2.4).
DEFAULT_USE_MAIN_MODEL_FOR_ALL: Final[bool] = True

# Per-slot native pydantic-ai models (``providers.native_model.<slot>``); W3 default off.
DEFAULT_NATIVE_MODEL_ENABLED: Final[bool] = False

# Tier-B CodeMode (``agent.codemode.enabled``); W8 default off.
DEFAULT_CODEMODE_ENABLED: Final[bool] = False

# CodeMode sandbox (Monty) ``ResourceLimits`` — enforced inside the Rust sandbox so a
# CPU-bound or pathological snippet (e.g. catastrophic regex) aborts in-sandbox instead of
# blocking the event loop and freezing the gateway. ``max_duration_secs`` must stay well under
# ``DEFAULT_TIER_B_EXECUTOR_TIMEOUT_S`` so the in-sandbox cap fires before the outer executor
# ``asyncio.wait_for`` backstop (`specs/14-executor-tier-b.md` W8).
DEFAULT_CODEMODE_MAX_DURATION_S: Final[float] = 45.0
DEFAULT_CODEMODE_MAX_MEMORY_BYTES: Final[int] = 512 * 1024 * 1024
DEFAULT_CODEMODE_MAX_ALLOCATIONS: Final[int] = 50_000_000
DEFAULT_CODEMODE_MAX_RETRIES: Final[int] = 3

# CLI diagnostic agent (``agent.diagnostics.enabled``); W4 default on.
DEFAULT_DIAGNOSTICS_AGENT_ENABLED: Final[bool] = True

# Triager tier-B list caps (`specs/10-schema-ontology.md` §5; PRD 04 §5.2).
# Tool cap lowered 10 -> 5: the Triager should pick a MINIMAL anchor set (1-3 tools);
# the executor loads more on demand via ``load_tool`` and a widened-toolkit retry
# re-runs with a broader set if needed, so a low cap discourages whole-index dumps
# without blocking legitimate multi-tool turns (`specs/13-rlm-triager.md` §2.3).
DEFAULT_TRIAGER_TIER_B_TOOL_CAP: Final[int] = 5
DEFAULT_TRIAGER_TIER_B_SKILL_CAP: Final[int] = 7

# Tier-B retry-storm guard (`specs/17-gateway.md` §3.4): a failed tier-B turn re-runs the
# executor through summarize / full-index retry passes. The first (narrow) pass keeps the
# full transcript; retry passes fail on *behaviour* (no tool called), not missing context,
# so they get a windowed transcript (last N turns) to stop re-sending the whole 33-turn
# history on every pass and blowing the token budget ~5x.
DEFAULT_TIER_B_RETRY_HISTORY_TURNS: Final[int] = 6

# Flat skill basename collision precedence under ``workspace/skills/{core,generated,user}``:
# **user overrides generated overrides core** (`specs/12-skills-system.md` §2.2).

# Skill subprocess / registry ergonomics (`specs/12-skills-system.md` §5, §10.3).
DEFAULT_SKILLS_WATCH_DEBOUNCE_MS: Final[int] = 500
DEFAULT_SKILL_MAX_WALL_SECONDS: Final[int] = 300
# Chronic skill failure detector (`specs/12-skills-system.md` §3.5; mirrors tool knobs in `specs/11-tools-registry.md`).
DEFAULT_SKILL_FAILURE_WINDOW_DAYS: Final[int] = 14
DEFAULT_SKILL_FAILURE_REWRITE_THRESHOLD: Final[int] = 3

# Transitional bundled skill index aliases (`plan/tools-skills-full-inventory-wave-plan.md` Wave TFI-13).
# Remove after one release when callers migrate to canonical ids.
BUNDLED_SKILL_INDEX_ALIASES: Final[dict[str, str]] = {
    "mycode_scan": "mycode",
}

# Workspace ``sevn.json``: ``skills.<plugin>.enabled`` and ``skills.computer_use.enabled`` default
# **disabled** until the owner opts in (`specs/12-skills-system.md` §5).
DEFAULT_COMPUTER_USE_ENABLED: Final[bool] = False
DEFAULT_COMPUTER_USE_TARGET: Final[str] = "host"
DEFAULT_COMPUTER_USE_SNAPSHOT_ANNOTATE: Final[bool] = False
DEFAULT_COMPUTER_USE_TRAJECTORY_ENABLED: Final[bool] = True
DEFAULT_COMPUTER_USE_TRAJECTORY_SHARE: Final[bool] = True
DEFAULT_CUA_AGENT_ENABLED: Final[bool] = False
DEFAULT_CUA_AGENT_REQUIRE_COMPUTER_USE: Final[bool] = True
DEFAULT_CUA_AGENT_APPROVAL: Final[str] = "per_run"
DEFAULT_LUME_ENABLED: Final[bool] = False

# Tool registry + spill knobs (`specs/11-tools-registry.md`).
LOADED_BODY_CACHE_DEFAULT_CAP: Final[int] = 64
TOOL_LARGE_RESULT_THRESHOLD_BYTES: Final[int] = 32_768
LOAD_SKILL_MARKDOWN_INLINE_MAX_BYTES: Final[int] = 20_480
TOOL_LARGE_RESULT_PREVIEW_CHARS: Final[int] = 256
INITIAL_REGISTRY_VERSION: Final[int] = 1

# Triager timeout staircase (`specs/13-rlm-triager.md` §5) — aligns with PRD posture 5/20/40/60s.
DEFAULT_TRIAGER_TIMEOUT_INDICATOR_S: Final[float] = 5.0
DEFAULT_TRIAGER_TIMEOUT_WARN_S: Final[float] = 20.0
DEFAULT_TRIAGER_TIMEOUT_WARN2_S: Final[float] = 40.0
DEFAULT_TRIAGER_TIMEOUT_HARD_S: Final[float] = 60.0

# Complexity clamp (`specs/13-rlm-triager.md`) — low-confidence C/D routes downgrade to B.
DEFAULT_COMPLEXITY_CLAMP_CONFIDENCE_THRESHOLD: Final[float] = 0.85
DEFAULT_COMPLEXITY_CLAMP_SHORT_WORD_LIMIT: Final[int] = 6

# Gateway cascade / executor wall-clock timeouts (`specs/17-gateway.md`).
DEFAULT_TIER_B_EXECUTOR_TIMEOUT_S: Final[float] = 180.0
DEFAULT_TIER_CD_EXECUTOR_TIMEOUT_S: Final[float] = 300.0
DEFAULT_CASCADE_BUDGET_S: Final[float] = 270.0

# Gateway may consult ``os.environ[TRIAGER_ENABLED_ENV_KEY]`` when wiring Triager (`specs/13-rlm-triager.md` §10.1).
TRIAGER_ENABLED_ENV_KEY: Final[str] = "TRIAGER_ENABLED"

# Tier-B executor (`specs/14-executor-tier-b.md` §5).
# ``TIER_B_MAX_ROUNDS`` is the per-turn outer chat+tool iteration cap.
# ``TIER_B_MAX_ROUNDS_EXPANDED`` is the cap used when the gateway retries tier B
# after tier-C escalation is unavailable (`specs/17-gateway.md` §2.6 step 9).
# ``TIER_B_COUNT_PLANNING`` decides whether LLM rounds that produced no tool call
# (i.e. pure planning/thinking) consume the budget; default ``False``.
#
# Wave 3 (CONVERSATION_REVIEW_2026-05-28.md §A12): defaults lowered to A=3
# (triager schema retries), B=30 (tier-B outer rounds), C=60 (tier-B expanded /
# tier-C/D outer rounds). Empirically, requests that need more rounds than this
# are signalling an unclear request or a tool/skill gap — better to stop and
# surface ``TIER_B_ROUND_BUDGET_TEMPLATE`` than to grind silently.
TIER_B_MAX_ROUNDS: Final[int] = 30
TIER_B_MAX_ROUNDS_EXPANDED: Final[int] = 60
TIER_B_TOOL_MAX_RETRIES: Final[int] = 3
# Per-turn total tool-call cap. Past this, tier-B exploration tools are blocked with a
# synthesis steer so a wandering model (e.g. re-reading files for dozens of rounds)
# is forced to answer from gathered evidence instead of burning rounds/tokens.
TIER_B_TOOL_CALL_BUDGET: Final[int] = 40
# Per-turn hard cap on how many times a *single* tool may return an error before it is
# blocked with a terminal synthesis steer. The identical-call escalation
# (``repeated_wrong_tool_call``) only fires on repeated *same-args* calls, so a model
# that varies arguments each attempt (e.g. guessing CLI subcommands or rewriting
# ``run_code`` snippets) could otherwise fail the same tool for dozens of rounds up to
# ``TIER_B_TOOL_CALL_BUDGET``. Sits above ``RECOVERY_WIDEN_FAILURE_THRESHOLD`` (2) so the
# diagnostics-widen recovery still gets a chance first.
TIER_B_TOOL_FAILURE_HARD_CAP: Final[int] = 5
TIER_B_COUNT_PLANNING: Final[bool] = False
# Triager retry budget for schema / model failures (`specs/13-rlm-triager.md` §6).
TRIAGER_MAX_RETRY_ATTEMPTS: Final[int] = 3
# Pydantic-ai output retries inside ``structured_output_call`` — kept low because
# MiniMax empty-content is nudged once at the transport layer (W5); a bad pass falls
# back to the synthetic schema fast instead of re-running the model multiple times.
TRIAGER_PYDANTIC_OUTPUT_RETRIES: Final[int] = 1
# Provider-side max output tokens for tier-B responses (Anthropic/Bedrock).
# Raised from 4096 so long answers (full file reads, log summaries) don't truncate.
TIER_B_MAX_OUTPUT_TOKENS: Final[int] = 20000
# Per-agent max-output ceilings in ``gateway.budget.*_max_output_tokens`` (sevn.json).
# Runtime applies ``min(sevn.json ceiling, LLM_params_config.json value)``.
TRIAGER_MAX_OUTPUT_TOKENS: Final[int] = 4096
TIER_CD_MAX_OUTPUT_TOKENS: Final[int] = 4096
GUARD_MAX_OUTPUT_TOKENS: Final[int] = 256
LCM_MAX_OUTPUT_TOKENS: Final[int] = 4096
DREAMING_MAX_OUTPUT_TOKENS: Final[int] = 256
USER_MODEL_MAX_OUTPUT_TOKENS: Final[int] = 2048
# Default ``model_overrides["minimax/*"].max_output_tokens`` in LLM_params_config.json.
MINIMAX_MAX_OUTPUT_TOKENS: Final[int] = 4096
# First-session BOOTSTRAP intro cap (`gateway.first_session_intro.max_output_tokens`).
# Matches triager egress (4096) so MiniMax Anthropic wire accepts the intro turn.
FIRST_SESSION_INTRO_MAX_OUTPUT_TOKENS: Final[int] = 4096

# Tier-B output mode picks how the executor's final answer reaches the user
# (``PROBLEMS.md`` Priority 2). ``two_message_finally`` keeps the preamble +
# answer pattern but routes the answer through an editable placeholder so the
# answer-row exists from turn start, eliminating the "missing second answer"
# bug structurally. ``stream`` edits the placeholder progressively as tokens
# arrive (UX upgrade; requires pydantic-ai streaming integration shipped in a
# follow-up). Default is ``stream`` per the design but only
# ``two_message_finally`` is functional until Step 6 wires real streaming.
TIER_B_ANSWER_MODE_DEFAULT: Final[str] = "stream"

# Code understanding — index artefacts under the checkout's ``.index/<tool>/...`` (Wave 5 A8).
# Graphify bootstrap paths live on ``GraphifySettings`` in
# ``sevn.code_understanding.models`` / ``graphify.py``.
DEFAULT_MYCODE_OUTPUT_RELATIVE: Final[str] = ".index/mycode/MYCODE.md"
# Graphify bootstrap for the sevn.bot checkout when ``SEVN_REPO_ROOT`` resolves
# (`specs/35-bot-evolution.md` EV-1; ``sevn.config.sevn_repo``).
DEFAULT_GRAPHIFY_SEVN_PROFILE_ID: Final[str] = "sevn"
DEFAULT_GRAPHIFY_SEVN_OUTPUT_REL: Final[str] = ".index/graphify"
DEFAULT_WORKSPACE_OUTPUT_DIR: Final[str] = "out"

# code-review-graph MCP (`specs/28-code-understanding.md` §2.1, §4.5, §10.7).
DEFAULT_CODE_REVIEW_GRAPH_TOOL_PRESET: Final[str] = "read_only"
DEFAULT_CODE_REVIEW_GRAPH_MCP_SERVER_ID: Final[str] = "code_review_graph"
DEFAULT_CODE_REVIEW_GRAPH_COMMAND: Final[str] = "code-review-graph"
CODE_REVIEW_GRAPH_READ_ONLY_TOOLS: Final[tuple[str, ...]] = (
    "get_minimal_context_tool",
    "get_impact_radius_tool",
    "get_review_context_tool",
    "query_graph_tool",
    "semantic_search_nodes_tool",
    "detect_changes_tool",
)

# Tier C/D executor (`specs/21-executor-tier-cd.md` §4.5, §5).
CD_OUTER_ROUNDS_MAX: Final[int] = 30
CD_RLM_MAX_ITERATIONS: Final[int] = 20
CD_RLM_MAX_OUTPUT_CHARS: Final[int] = 10_000
CD_RLM_DEFAULT_MAX_LLM_CALLS: Final[int] = 20
DEFAULT_RLM_C_D_BACKEND: Final[Literal["dspy", "lambda_rlm"]] = "dspy"
DEFAULT_RLM_REPL_LIFETIME: Final[Literal["per_turn", "per_session", "per_run"]] = "per_turn"
DEFAULT_TIER_CD_LAMBDA_RLM_ENABLED: Final[bool] = False
DEFAULT_PLAN_APPROVAL_ENABLED: Final[bool] = False
DEFAULT_PLAN_APPROVAL_TTL_SECONDS: Final[int] = 15 * 60
# ``SynthSig`` closing message cap (`specs/21-executor-tier-cd.md` §11; `specs/24-dashboard.md` §11).
CD_SYNTH_MAX_TOKENS: Final[int] = 4096
CD_SYNTH_MAX_CHARS: Final[int] = CD_SYNTH_MAX_TOKENS * 4
# User-visible copy when λ runtime lacks plan/execute split (`specs/21-executor-tier-cd.md` §2.3).
LAMBDA_RLM_DEGRADED_PLAN_SPLIT_MESSAGE: Final[str] = (
    "This run uses simplified λ-RLM planning (no separate plan step). "
    "Tools marked as requiring human approval still block until you confirm each step."
)

# Harness discipline (`specs/16-harness-discipline.md` §4.2, §5).
DEFAULT_GATEWAY_AUTO_RESUME_B: Final[bool] = False
DEFAULT_REPLAY_MAX_PER_DAY: Final[int] = 20
DEFAULT_HARNESS_SNAPSHOT_TRIAGER_TIER_A: Final[bool] = False
HARNESS_SNAPSHOT_GC_ORPHAN_MAX_AGE_NS: Final[int] = 14 * 24 * 60 * 60 * 1_000_000_000

# Zombie-watch (`specs/16-harness-discipline.md` §4.4).
HARNESS_ZOMBIE_MAX_CONCURRENT: Final[int] = 4
HARNESS_ZOMBIE_MAX_PENDING: Final[int] = 256
HARNESS_ZOMBIE_TTL_S: Final[int] = 3600

# Sandbox resource defaults (``specs/08-sandbox.md`` §5.1).
SANDBOX_MAX_CPU: Final[int] = 2
SANDBOX_MAX_MEM_MB: Final[int] = 2048
SANDBOX_MAX_DISK_MB: Final[int] = 4096
SANDBOX_MAX_PIDS: Final[int] = 256
SANDBOX_MAX_LIFETIME_S: Final[int] = 7200
SANDBOX_SNAPSHOT_INTERVAL_MIN: Final[int] = 30
SANDBOX_SNAPSHOT_RETENTION_COUNT_DEFAULT: Final[int] = 3

# LCM — lossless context (`specs/15-memory-lcm.md` §5): bounded suffix vs prompt-cache §4.1.
DEFAULT_LCM_ENABLED: Final[bool] = True
DEFAULT_LCM_FRESH_TAIL_COUNT: Final[int] = 32
DEFAULT_LCM_AUTOCOMPACT_DISABLED: Final[bool] = False
DEFAULT_LCM_LEAF_TARGET_TOKENS: Final[int] = 1200
DEFAULT_LCM_CONDENSED_TARGET_TOKENS: Final[int] = 2000
DEFAULT_LCM_LEAF_CHUNK_TOKENS: Final[int] = 20000
DEFAULT_LCM_LEAF_MIN_FANOUT: Final[int] = 8
DEFAULT_LCM_CONDENSED_MIN_FANOUT: Final[int] = 4
DEFAULT_LCM_INCREMENTAL_MAX_DEPTH: Final[int] = 0  # 0 => unlimited condensation depth (§5 table).
DEFAULT_LCM_LARGE_FILE_TOKEN_THRESHOLD: Final[int] = 25000
DEFAULT_LCM_TOPIC_SEARCH_MAX_SESSIONS: Final[int] = 32
DEFAULT_LCM_SUMMARY_LANGUAGE: Final[str] = "auto"
DEFAULT_LCM_DEDUP_OVERLAP_THRESHOLD: Final[float] = 0.85
DEFAULT_LCM_SMART_COLLAPSE_ENABLED: Final[bool] = True
DEFAULT_LCM_UNCACHED_SUFFIX_FRACTION: Final[float] = 0.12
DEFAULT_LCM_UNCACHED_SUFFIX_FLOOR_TOKENS: Final[int] = 512
DEFAULT_LCM_UNCACHED_SUFFIX_CEILING_TOKENS: Final[int] = 16000
DEFAULT_MEMORY_PRE_COMPACTION_FLUSH_ENABLED: Final[bool] = True
# Honcho-style inferred operator profile (`specs/32-memory-honcho.md` §3.2).
DEFAULT_USER_MODEL_ENABLED: Final[bool] = False
DEFAULT_USER_MODEL_MAX_FACTS: Final[int] = 64
DEFAULT_USER_MODEL_MAX_INJECT_TOKENS: Final[int] = 600
DEFAULT_USER_MODEL_BUMP_THROTTLE_MINUTES: Final[int] = 60
DEFAULT_USER_MODEL_TRIGGER_TIERS: Final[tuple[str, ...]] = ("B", "C", "D")

# Telegram Bot API (`specs/18-channel-telegram.md` §4.4; chunk cap under `specs/17-gateway.md` §5).
# UTF-16 code units must stay under 4096; 4090 leaves margin for entities.
TELEGRAM_MAX_TEXT_LENGTH: Final[int] = 4090
# In-memory ``update_id`` dedupe (`specs/18-channel-telegram.md` §4.1).
TELEGRAM_UPDATE_DEDUP_CAP: Final[int] = 10_000
TELEGRAM_UPDATE_DEDUP_TRIM_TO: Final[int] = 5_000
# ``setMyCommands`` coalesce before publish (`specs/18-channel-telegram.md` §4.5).
TELEGRAM_SET_MY_COMMANDS_DEBOUNCE_S: Final[float] = 2.0
# ``callback_data`` UTF-8 byte cap (Telegram Bot API; ``specs/18-channel-telegram.md`` §4.5).
TELEGRAM_CALLBACK_DATA_MAX_BYTES: Final[int] = 64
# ``dispatcher_state`` per-kind TTL defaults (`specs/17-gateway.md`; Wave 0C control-surface).
_DEFAULT_DISPATCHER_STATE_MENU_TTL_S: Final[int] = 24 * 3600
_DEFAULT_DISPATCHER_STATE_SECRET_WIZARD_TTL_S: Final[int] = 2 * 3600
_DEFAULT_DISPATCHER_STATE_PLAN_APPROVAL_TTL_S: Final[int] = 15 * 60
_DEFAULT_DISPATCHER_STATE_WEBAPP_TTL_S: Final[int] = 3600
DEFAULT_DISPATCHER_STATE_TTL_SECONDS: Final[dict[str, int]] = {
    "menu": _DEFAULT_DISPATCHER_STATE_MENU_TTL_S,
    "toggle": _DEFAULT_DISPATCHER_STATE_MENU_TTL_S,
    "prompt": _DEFAULT_DISPATCHER_STATE_MENU_TTL_S,
    "skill": _DEFAULT_DISPATCHER_STATE_MENU_TTL_S,
    "action": _DEFAULT_DISPATCHER_STATE_MENU_TTL_S,
    "scene": _DEFAULT_DISPATCHER_STATE_MENU_TTL_S,
    "form": _DEFAULT_DISPATCHER_STATE_MENU_TTL_S,
    "secret_wizard": _DEFAULT_DISPATCHER_STATE_SECRET_WIZARD_TTL_S,
    "plan_approval": _DEFAULT_DISPATCHER_STATE_PLAN_APPROVAL_TTL_S,
    "callback_overflow": _DEFAULT_DISPATCHER_STATE_MENU_TTL_S,
    "webapp_share": _DEFAULT_DISPATCHER_STATE_WEBAPP_TTL_S,
    "webapp_feedback": _DEFAULT_DISPATCHER_STATE_WEBAPP_TTL_S,
    "webapp_viewer": _DEFAULT_DISPATCHER_STATE_WEBAPP_TTL_S,
}
# Back-compat alias for callback overflow tokenisation (`specs/18-channel-telegram.md` §4.5).
DISPATCHER_STATE_CALLBACK_OVERFLOW_TTL_S: Final[int] = DEFAULT_DISPATCHER_STATE_TTL_SECONDS[
    "callback_overflow"
]

# Bot API 10.1 rich messages (`channels.telegram.rich.mode`; D3).
DEFAULT_TELEGRAM_RICH_MODE: Final[Literal["off", "auto", "all"]] = "auto"

# Telegram inline mode (`channels.telegram.inline.*`; D7/D8).
DEFAULT_TELEGRAM_INLINE_ENABLED: Final[bool] = False
DEFAULT_TELEGRAM_INLINE_FEEDBACK: Final[bool] = False
DEFAULT_TELEGRAM_INLINE_CACHE_TIME_AGENT: Final[int] = 10
DEFAULT_TELEGRAM_INLINE_CACHE_TIME_STATIC: Final[int] = 300

# Telegram quick-action bar per-button visibility (`specs/18-channel-telegram.md` §10.10).
DEFAULT_TELEGRAM_QA_SHOW_REGEN: Final[bool] = True
DEFAULT_TELEGRAM_QA_SHOW_THUMBS_UP: Final[bool] = True
DEFAULT_TELEGRAM_QA_SHOW_THUMBS_DOWN: Final[bool] = True
DEFAULT_TELEGRAM_QA_SHOW_SHARE: Final[bool] = True
DEFAULT_TELEGRAM_QA_SHOW_FEEDBACK: Final[bool] = True

# Voice STT/TTS chains (`specs/20-voice.md` §5; PRD 01 §5.5, PRD 05 §5.8).
DEFAULT_VOICE_STT_PROVIDERS: Final[tuple[str, ...]] = (
    "whisper_cpp",
    "openai_whisper",
    "deepgram",
    "google_stt",
    "xai_grok_stt",
)
DEFAULT_VOICE_TTS_PROVIDERS: Final[tuple[str, ...]] = (
    "text_to_voice",
    "edge_tts",
    "openai_tts",
    "elevenlabs",
    "mistral_voxtral",
    "google_gemini_tts",
)
DEFAULT_VOICE_LOCAL_TTS_ENGINE: Final[str] = "kokoro"
DEFAULT_VOICE_TRIGGER_KEYWORDS: Final[tuple[str, ...]] = (
    "read aloud",
    "read this aloud",
    "speak",
    "voice reply",
)
DEFAULT_VOICE_MAX_MB: Final[float] = 25.0
DEFAULT_VOICE_MAX_SECONDS: Final[float] = 300.0
DEFAULT_VOICE_STT_CONFIDENCE_REPROMPT_THRESHOLD: Final[float] = 0.7
DEFAULT_VOICE_TTS_TEMP_TTL_DAYS: Final[int] = 7
DEFAULT_VOICE_PRELOAD_LOCAL_TTS_ON_BOOT: Final[bool] = False
DEFAULT_VOICE_ENABLED: Final[bool] = True
# GGML model the whisper.cpp provisioner downloads by default (pyclaww parity — "base" is
# recommended for Apple Silicon: balanced speed/accuracy at ~74 MB).
DEFAULT_VOICE_STT_WHISPER_MODEL: Final[str] = "base"

# Inlined transcript prefix — stable across channels (`specs/20-voice.md` §2.3).
VOICE_INBOUND_TRANSCRIPT_PREFIX: Final[str] = '[Voice message transcribed]: "'

# Guided onboarding / local web wizard (`specs/22-onboarding.md` §4.6, §5).
ONBOARDING_TOKEN_TTL_SECONDS: Final[int] = 60 * 60
ONBOARDING_WIZARD_BIND_HOST: Final[str] = "127.0.0.1"
ONBOARDING_LOG_MAX_BYTES: Final[int] = 1_048_576

# CLI → gateway HTTP client (`specs/23-cli.md` §2.3).
CLI_GATEWAY_GET_LIVENESS_TIMEOUT_S: Final[float] = 5.0
CLI_GATEWAY_GET_DEFAULT_TIMEOUT_S: Final[float] = 30.0
CLI_GATEWAY_GET_MAX_RETRIES: Final[int] = 2
CLI_GATEWAY_GET_RETRY_BACKOFF_S: Final[float] = 0.2

# Non-interactive triggers (`specs/30-non-interactive-triggers.md` §5, §3.2).
DEFAULT_TRIGGERS_MAX_CONCURRENT: Final[int] = 4
DEFAULT_TRIGGERS_MAX_INLINE_BYTES: Final[int] = 65536
DEFAULT_TRIGGERS_WEBHOOK_DEDUPE_TTL_S: Final[int] = 7 * 24 * 3600
DEFAULT_TRIGGERS_INBOX_SPILL_MAX_FILES: Final[int] = 500

# Self-improve loop (`specs/33-self-improvement.md` §5).
DEFAULT_SELF_IMPROVE_ENABLED: Final[bool] = True
DEFAULT_SELF_IMPROVE_SAMPLER_MAX_CANDIDATES: Final[int] = 100
SELF_IMPROVE_SAMPLER_MAX_CANDIDATES_MIN: Final[int] = 10
SELF_IMPROVE_SAMPLER_MAX_CANDIDATES_MAX: Final[int] = 500
DEFAULT_SELF_IMPROVE_EXPLICIT_FEEDBACK_FLOOR_PCT: Final[float] = 0.20
DEFAULT_SELF_IMPROVE_CLEAN_PRE_FILTER_RATIO: Final[float] = 0.10
DEFAULT_SELF_IMPROVE_PER_CHANNEL_PCT_MAX: Final[float] = 0.40
DEFAULT_SELF_IMPROVE_PER_CHANNEL_PCT_MIN_VOICE: Final[float] = 0.05
DEFAULT_SELF_IMPROVE_PER_INTENT_PCT_MAX: Final[float] = 0.40
DEFAULT_SELF_IMPROVE_PER_TIER_PCT_MAX: Final[float] = 0.40
DEFAULT_SELF_IMPROVE_JOBS_MAX_CONCURRENT_WRITERS: Final[int] = 1
DEFAULT_SELF_IMPROVE_EVAL_DOCKER_REQUIRED: Final[bool] = True
DEFAULT_SELF_IMPROVE_IMPROVE_ARTEFACT_RETENTION_DAYS: Final[int] = 30
DEFAULT_SELF_IMPROVE_EXPORT_TTL_DAYS: Final[int] = 30
DEFAULT_SELF_IMPROVE_SPEC_KIT_ENABLED: Final[bool] = False
DEFAULT_SELF_IMPROVE_SPEC_KIT_REQUIRE_PLAN: Final[bool] = True
DEFAULT_SELF_IMPROVE_SPEC_KIT_REQUIRE_HITL_PLAN: Final[bool] = False
DEFAULT_SELF_IMPROVE_TRAJECTORIES_INGEST_ON_TURN: Final[bool] = True
DEFAULT_SELF_IMPROVE_TRAJECTORIES_INGEST_CRON: Final[str] = "0 4 * * *"
DEFAULT_SPEC_KIT_ENABLED: Final[bool] = True
DEFAULT_SPEC_KIT_CONSTITUTION_PATH: Final[str] = "evolution/spec-kit/CONSTITUTION.md"
DEFAULT_SPEC_KIT_INTEGRATION: Final[str] = "copilot"
DEFAULT_SPEC_KIT_DRY_RUN_DEFAULT: Final[bool] = False
DEFAULT_MY_SEVN_ISSUES_AUTO_FILE_ON_FAILURE: Final[bool] = False
DEFAULT_MY_SEVN_ISSUES_SYNC_ENABLED: Final[bool] = True
DEFAULT_MY_SEVN_ISSUES_SYNC_CRON: Final[str] = "0 */6 * * *"  # specs/35-bot-evolution.md L1 (FL-1)
DEFAULT_MY_SEVN_ISSUES_WEBHOOK_IMPORT: Final[bool] = True
DEFAULT_MY_SEVN_ISSUES_AUTO_RUN_ON_IMPORT: Final[bool] = False  # owner opt-in (L1)
DEFAULT_MY_SEVN_EXECUTOR_BUG: Final[str] = "local"
DEFAULT_MY_SEVN_EXECUTOR_FEATURE: Final[str] = "cursor_cloud"
DEFAULT_MY_SEVN_EXECUTOR_CURSOR_POLL_MODE: Final[str] = "background"
DEFAULT_MY_SEVN_SYNC_CRON: Final[str] = "0 4 * * *"
DEFAULT_SELF_IMPROVE_HUB_USE_GITHUB: Final[bool] = True
# Pipeline dry-run defaults — FL-2.2 (full-loop-evolution-wave-plan.md).
# ci_dry_run_default / promotion_dry_run_default protect against accidental
# real CI + promotion in non-live runs; spec_kit_dry_run_default = False so
# spec-kit LLM stages run by default.  local_implement_max_turns caps tier-B
# budget for the worktree implement step (FL-4A).
DEFAULT_MY_SEVN_PIPELINES_CI_DRY_RUN: Final[bool] = True
DEFAULT_MY_SEVN_PIPELINES_PROMOTION_DRY_RUN: Final[bool] = True
DEFAULT_MY_SEVN_PIPELINES_SPEC_KIT_DRY_RUN: Final[bool] = False
DEFAULT_MY_SEVN_PIPELINES_LOCAL_IMPLEMENT_MAX_TURNS: Final[int] = 20

# Mission Control trace retention (`specs/04-tracing.md` §10.7 / §11 — Option A bundle).
# 64 KiB cap is enforced *before* writing to SQLite/JSONL; oversized payloads are
# truncated and replaced with a marker so the row is preserved without unbounded
# growth (`specs/04-tracing.md` §11 design notes). Truncation logs a warning.
TRACE_ATTRS_JSON_MAX_BYTES: Final[int] = 64 * 1024
# Default TTL applied by the gateway lifespan purge job. The cron tick re-runs
# the purge so retention stays bounded even on long-lived processes.
DEFAULT_TRACE_TTL_DAYS: Final[int] = 30
# Rollup writer aggregates events into ``trace_rollups_hourly`` buckets. The
# lookback window controls how many completed hour buckets to recompute per run
# — large enough to catch late-arriving spans, small enough to stay cheap.
DEFAULT_TRACE_ROLLUP_LOOKBACK_HOURS: Final[int] = 6
# Trace payload redaction (`specs/04-tracing.md` §2.5; control-surface Wave 0D).
# Applied once in ``RedactingSink`` before ``MultiSink`` fan-out.
DEFAULT_TRACE_REDACTION_ENABLED: Final[bool] = True
DEFAULT_TRACE_REDACTION_DENY_KEYS: Final[tuple[str, ...]] = (
    "authorization",
    "cookie",
    "api_key",
    "secret",
    "password",
    "access_token",
    "refresh_token",
    "id_token",
    "bearer_token",
    "auth_token",
)
DEFAULT_TRACE_REDACTION_DENY_VALUE_PATTERNS: Final[tuple[str, ...]] = (
    r"sk-[A-Za-z0-9]{20,}",
    r"ghp_[A-Za-z0-9]{20,}",
)
DEFAULT_TRACING_REDACTION: Final[dict[str, object]] = {
    "enabled": DEFAULT_TRACE_REDACTION_ENABLED,
    "deny_keys": list(DEFAULT_TRACE_REDACTION_DENY_KEYS),
    "deny_value_patterns": list(DEFAULT_TRACE_REDACTION_DENY_VALUE_PATTERNS),
}
DEFAULT_TRACING_SINKS: Final[list[dict[str, str]]] = [
    {"type": "sqlite"},
    {"type": "jsonl_file", "path": ".sevn/traces/"},
]

# Turn-bundle diagnostics (turn-bundle-build-plan-from-errors W0 / D8).
# Default ``enabled: false`` — zero behaviour change until the post-turn writer lands (W1).
DEFAULT_TURN_BUNDLES_ENABLED: Final[bool] = False
DEFAULT_DIAGNOSTICS_TURN_BUNDLES: Final[dict[str, object]] = {
    "enabled": DEFAULT_TURN_BUNDLES_ENABLED,
}

# Dreaming — optional cron promotion (`specs/31-memory-dreaming.md` §5).
DEFAULT_DREAMING_ENABLED: Final[bool] = True
DEFAULT_DREAMING_CRON: Final[str] = "0 3 * * *"
DEFAULT_DREAMING_THRESHOLD: Final[float] = 0.5
DEFAULT_DREAMING_MAX_PROMOTIONS_PER_RUN: Final[int] = 8
DEFAULT_DREAMING_BACKFILL_DAYS: Final[int] = 90
DEFAULT_DREAMING_RECALL_WEIGHT: Final[float] = 0.5
DEFAULT_DREAMING_DIVERSITY_WEIGHT: Final[float] = 0.3
DEFAULT_DREAMING_RECENCY_WEIGHT: Final[float] = 0.2
DEFAULT_DREAMING_SCORING_ADAPTIVE: Final[bool] = False
DEFAULT_DREAMING_LLM_RANKER_ENABLED: Final[bool] = False

# Second Brain (`specs/27-second-brain.md` §5).
DEFAULT_SECOND_BRAIN_ENABLED: Final[bool] = True
DEFAULT_SECOND_BRAIN_OUTPUTS_RETENTION_DAYS: Final[int] = 90
DEFAULT_SECOND_BRAIN_FETCH_MAX_RESPONSE_MIB: Final[int] = 10
DEFAULT_SECOND_BRAIN_FETCH_TIMEOUT_S: Final[int] = 30
DEFAULT_SECOND_BRAIN_MAX_STUB_PAGES_PER_INGEST: Final[int] = 500
DEFAULT_SECOND_BRAIN_WITCHCRAFT_FRESH_SECONDS: Final[int] = 300

# OpenUI (`specs/29-openui.md` §5) — parity with ``sevn.json`` defaults.
DEFAULT_OPENUI_TOKEN_TTL_SECONDS: Final[int] = 21_600
DEFAULT_OPENUI_CALLBACK_TIMEOUT_SECONDS: Final[int] = 1800
DEFAULT_OPENUI_SOFT_CAP_BYTES: Final[int] = 131_072
DEFAULT_OPENUI_HARD_CAP_BYTES: Final[int] = 1_048_576

# Plugin hook ordering defaults (`specs/34-plugin-hooks.md` §4.3, §5):
# Primary lexicographic key ``(distribution_name, entry_point_name, PluginHook.name)``,
# then workspace ``plugin_hooks.<id>.runs_after`` as a stable topological tie-break.
DEFAULT_PLUGIN_HOOK_PRE_TRANSFORM_TIMEOUT_S: Final[float] = 5.0
DEFAULT_PLUGIN_HOOK_DISPATCH_TIMEOUT_S: Final[float] = 30.0

# Daemon service logging (`specs/04-tracing.md` §5.1, `specs/02-config-and-workspace.md` §2.4).
# Loguru ``{time:…SSSZ}`` — trailing ``Z`` is the **offset glyph** (e.g. ``+02:00``),
# not a literal UTC ``Z`` suffix. ``SEVN_LOG_TZ`` overrides via ``setup_service_logging``.
SERVICE_LOG_FORMAT: Final[str] = (
    "{time:YYYY-MM-DD HH:mm:ss.SSSZ} | {level: <8} | "
    "{extra[message_id]} | {file.path}:{line} {function} | {message}"
)
DEFAULT_LOG_RETENTION_DAYS: Final[int] = 10
DEFAULT_LOG_ARCHIVE_MODE: Final[str] = "copy"
DEFAULT_LOG_ARCHIVE_DESTINATION: Final[str] = "logs/archive"
# ``None`` = use the structured-log hard ceiling (``TOOL_DEBUG_RESULT_LOG_HARD_CAP``)
# rather than logging the full tool envelope JSON on ``tool_call.finish`` DEBUG lines.
DEFAULT_TOOL_DEBUG_RESULT_MAX_CHARS: Final[int | None] = None
# Hard upper bound on the ``result=`` preview written to structured DEBUG log lines,
# independent of ``logging.tool_debug_result_max_chars``. Stops a single oversized
# tool result (e.g. a 1 MB ``log_query`` / ``read`` body) from spilling hundreds of
# KB into ``gateway.log`` (recursive ``log_query`` bloat). The full result is still
# returned to the model — this caps the LOG rendering only.
TOOL_DEBUG_RESULT_LOG_HARD_CAP: Final[int] = 4096
# Egress proxy upstream fetch (`specs/07-egress-proxy.md` §10.13 W2).
PROXY_UPSTREAM_TIMEOUT_CONNECT_S: Final[float] = 10.0
PROXY_UPSTREAM_TIMEOUT_READ_S: Final[float] = 90.0
PROXY_UPSTREAM_TIMEOUT_WRITE_S: Final[float] = 30.0
PROXY_UPSTREAM_TIMEOUT_POOL_S: Final[float] = 10.0
PROXY_TOOL_TO_PROXY_TIMEOUT_CONNECT_S: Final[float] = 5.0
PROXY_TOOL_TO_PROXY_TIMEOUT_READ_S: Final[float] = 30.0
PROXY_TOOL_TO_PROXY_TIMEOUT_WRITE_S: Final[float] = 30.0
PROXY_TOOL_TO_PROXY_TIMEOUT_POOL_S: Final[float] = 10.0
PROXY_HTTP_MAX_CONNECTIONS: Final[int] = 20
PROXY_HTTP_MAX_KEEPALIVE_CONNECTIONS: Final[int] = 10
DEFAULT_PROXY_PORT: Final[int] = 8787
DEFAULT_MINIMAX_ANTHROPIC_BASE_URL: Final[str] = "https://api.minimax.io/anthropic/v1"
DEFAULT_MINIMAX_OPENAI_BASE_URL: Final[str] = "https://api.minimax.io/v1"
DEFAULT_MINIMAX_TRANSPORT: Final[str] = "chat_completions"

# Sub-agents (L1/L2) — `subagents` subtree (`specs/36-sub-agents.md` D2).
DEFAULT_SUBAGENTS_ENABLED: Final[bool] = True
DEFAULT_SUBAGENTS_MAX_LEVEL1: Final[int] = 5
DEFAULT_SUBAGENTS_MAX_LEVEL2: Final[int] = 3
DEFAULT_SUBAGENT_SPECIALIST_MAX_CONCURRENT: Final[int] = 2


def _doctest_phase0_anchor() -> bool:
    """Trivial return used only to anchor doctests in CI.

    Returns:
        bool: Always True.

    Examples:
        >>> _doctest_phase0_anchor()
        True
    """
    return True
