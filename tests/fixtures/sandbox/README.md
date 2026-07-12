# Sandbox fixtures (Phase 1)

## `child_env_contract.json`

Lists the environment keys `build_sandbox_child_env` must set (`specs/08-sandbox.md` §2.2). Used by reviewers and optional Docker integration tests.

## Gated Docker integration

- **Local:** `make sandbox-integration` (sets `SEVN_CI_SANDBOX_DOCKER=1`, requires a reachable Docker daemon, pulls `busybox:1.36` once).
- **CI matrix:** Docker-backed jobs remain under `specs/25-cicd-full.md` §10.7; default `make ci` skips `-m sandbox_docker` tests.

Unit coverage today mocks `SandboxRunRegistry` and `docker_daemon_reachable` where needed; snapshot format and pruning tests run under the normal unit suite.
