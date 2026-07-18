# 0002. Adopt AI-Builder-Club verifier-setup into spec-kit-wave

**Status:** Accepted
**Date:** 2026-07-14
**Source:** [AI-Builder-Club/skills verifier-setup](https://github.com/AI-Builder-Club/skills/blob/main/skills/verifier-setup/SKILL.md) (MIT)

## Context

[AI-Builder-Club/skills](https://github.com/AI-Builder-Club/skills) ships a
**verifier-setup** skill that scaffolds a per-task **`/verify`** loop: one-time repo
setup → generated verify SOP → independent verifier sub-agent → screenshot/video proof →
PR with embedded evidence. sevn.bot already has partial verification (`make ci-affected`,
`make telegram-e2e`, Mission Control) but no unified proof-before-PR skill.

## Decisions

| # | Decision |
|---|----------|
| D1 | **Integration home = spec-kit-wave.** Skill at `skills/verifier-setup/SKILL.md`; verify template at `skills/verifier-setup/assets/verify.template.md`; special agent at `agents/verifier-setup.md` + `prompts/verifier-setup.md`. |
| D2 | **IDE install = `make install-skills`.** Symlink (default) or `COPY=1` into `.cursor/skills/` and `.claude/skills/` — same pattern as mattpocock adoption (ADR 0001 D4). |
| D3 | **sevn defaults in the adapted skill:** `make compose-up`, Mission Control on `SEVN_GATEWAY_PORT` (3001), web driver `cursor-ide-browser` MCP, Telegram driver `telegram_test` + `make telegram-e2e`, regression `make ci-affected`. |
| D4 | **Generated output** lives in `.cursor/skills/verify/` and `.claude/skills/verify/` (repo-specific, not vendored in the kit). |
| D5 | **Evidence** under `evidence/` (gitignored at repo root). |
| D6 | **Special agent dispatch:** `make verifier-setup` / `make verifier-setup-run`; Cursor agent at `.cursor/agents/verifier-setup.md`. Not part of LangGraph wave loop. |

## Consequences

- Operators run **verifier-setup once** (or when verification infra changes), then **`/verify`** per task before PRs.
- Upstream `dev-local-setup`, browser-CLI adapters, and `crabbox-setup` are **not** vendored; sevn reuses `compose-up`, existing MCP/skills, and local-only run mode by default.
- spec-kit-wave remains operator-private (gitignored); tracked repo carries ADR + `.cursor/agents/verifier-setup.md`.
