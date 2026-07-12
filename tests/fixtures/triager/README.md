## Triager fixtures

- `custom_stub_result.json` — optional `SEVN_TRIAGER_STUB_FIXTURE_PATH` for `tests/agent/test_triager_run.py`.
- `e2e_tier_b_stub.json` — tier-B routing stub for `tests/agent/test_e2e_single_message.py`.
- `tier_c_stub.json` — tier-C routing stub for `tests/agent/test_e2e_tier_c_smoke.py` and v1-smoke gate 7 (`SEVN_TRIAGER_STUB=1` + `SEVN_TRIAGER_STUB_FIXTURE_PATH`).
- `golden_routing.jsonl` — ≥200 labelled routing rows for eval replay (`specs/13-rlm-triager.md` §11; Wave 5).

### Golden routing sampling policy (Wave E-2)

Eval replay does **not** run every row on each graph invocation:

| Context | Sample size | Selection |
|---------|-------------|-----------|
| Local dev (default) | 200 | Stratified by `labels.intent`, seed `33` |
| CI (`CI=1` / GitHub Actions) | 50 | Same stratified policy |
| Override | `SEVN_EVAL_GOLDEN_SAMPLE=N` | Fixed `N` rows |

`run_live_replay_smoke` in `eval_network=replay` uses a bounded slice of **12** rows.
`eval_network=live_budget` caps rows via `eval.token_budget_daily` (~500 tokens per triager call).

Accuracy gate: **intent match rate ≥ 0.95** (default). With `SEVN_TRIAGER_STUB=1`, replay injects per-row stub JSON from labels (recorded responses). With stub off, the live Triager transport is used.

Regenerate `golden_routing.jsonl` with `uv run python` and the generator in Wave 5 commit history, or extend rows manually keeping `id`, `message`, `locale`, and `labels` keys stable.
