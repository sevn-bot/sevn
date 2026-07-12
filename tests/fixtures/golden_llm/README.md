# Golden live-LLM corpus (W11)

Hermetic tier-B eval fixtures with record/replay. Live runs are opt-in; CI replays
pre-recorded transport scripts tokenlessly.

## Layout

```text
golden_llm/
├── README.md
├── harness.py              # case schema, workspace prep, replay runner
├── workspace_template/     # copied to tmp_path per case
├── cases/
│   ├── tools/              # native registry tools
│   ├── skills/             # bundled skills (load_skill / run_skill_script)
│   ├── input/              # multimodal stubs (W10)
│   └── codemode/           # multi-tool composite stubs (W8)
├── recordings/             # transport scripts + provider_turn_messages
└── runner/
    └── test_golden_llm_tier_b.py
```

## Case schema

Each `cases/*/*.json` file carries:

| Field | Purpose |
|-------|---------|
| `id` | Stable case id |
| `tier` | Executor tier (`B`) |
| `requires.tools` / `requires.skills` | Triager-listed capabilities |
| `user_messages` | Operator prompts (last message drives tier B) |
| `triage_stub` | Pre-baked `TriageResult` JSON (skips routing tokens) |
| `workspace.inline_files` | Hermetic files written into the temp workspace |
| `assertions` | `tools_called`, `tool_success`, `response_contains` |

Truth signal: `extras.provider_turn_messages` tool names (same as `tools/conversation_eval.py`).

## Running

```bash
# Tokenless replay (default CI path)
make test TESTS=tests/fixtures/golden_llm/runner/

# Live record (opt-in; needs provider keys)
SEVN_GOLDEN_LLM=1 pytest -m golden_llm tests/fixtures/golden_llm/runner/
```

Replay tests run without `SEVN_GOLDEN_LLM`. Tests marked `golden_llm` that call a live
provider are skipped unless `SEVN_GOLDEN_LLM=1`.

## Record / replay

1. **Record:** with `SEVN_GOLDEN_LLM=1`, the runner executes tier B against a live
   transport and writes `recordings/<case_id>.json` (`transport_responses` +
   `provider_turn_messages`).
2. **Replay:** CI loads the recording and drives a scripted OpenAI transport — no tokens.

W12 migrates cases into `pydantic_evals.Dataset` with span evaluators. CI gate:

```bash
make golden-llm-ci
```
