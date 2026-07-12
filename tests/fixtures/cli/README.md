# CLI test fixtures

- `doctor_success_envelope.json` — stable **`--json`** success envelope for `sevn doctor` (`specs/23-cli.md` §2.6). Contract tests assert required keys; live output varies by workspace and gateway reachability.
- `doctor_w0_golden_check_ids.json` — W0 baseline (2026-06-17) canonical check **`id`** list + envelope key contract for W2 doctor framework back-compat (`plan/cli-comprehensive-parity-doctor-wave-plan.md` W0.7). **`detail`** / **`warnings`** values are environment-specific; W2 asserts IDs + top-level shape only.
- **Daemon / service-manager tests** — optional `sevn gateway|proxy {start,stop,restart}` integration is **skipped** in CI (`tests/cli/test_daemon_smoke.py`) until launchd/systemd harnesses exist (`specs/23-cli.md` §10.4).
