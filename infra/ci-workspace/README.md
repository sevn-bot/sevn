# CI compose workspace

Seeded `sevn.json` bind-mounted into the gateway container by `docker-compose.ci.yml`
(`about-sevn.bot/specs/25-cicd-full.md` §10.4). Runtime SQLite and artefacts live under `.sevn/` inside
this directory.

**Wave 10 seeded state** (consumes Wave 9 onboarding/CLI outputs):

- `gateway.token` — `e2e-dev-token` for local `/login` / diagnostics against compose.
- `channels.webchat` — JWT + `allowed_origins` for localhost compose (`13001`) and
  optional local webServer (`13002`).
- `telemetry.enabled` — `false` (Wave 9A schema shape).
- `security.scanner.heuristic_only` — fast CI scans without LLM Guard corpus.
- `tracing.sinks` — jsonl sink for Mission Control trace feed smoke.

Set `SEVN_E2E_ECHO_TURN=1` on the gateway service (see `docker-compose.ci.yml`) so
diagnostics echo turns receive deterministic replies. (Former TS E2E harness removed;
webchat/onboarding/MC journeys are parked — see github.com/sevn-bot/sevn/issues/37.)
