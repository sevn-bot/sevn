# sevn

sevn is a personal, local-first host for persistent AI bots. A bot runs one agent per request. Clients speak one protocol to the host over WebSocket. Secrets and conversation data stay on the host.

## Development

Install the toolchain, then start the host and the Vite dev server:

```bash
make setup
make dev
```

`make setup` installs the Python workspace, the web app, and the git hooks. `make dev` runs `sevn serve` with `SEVN_DEV=1` and Vite, which proxies `/ws` and `/auth` to the host (default `127.0.0.1:8787`).

The container image is `deploy/Dockerfile`. It listens on `0.0.0.0:8787` with `SEVN_HOME=/data`. Set `SEVN_ALLOWED_HOSTS` to every non-loopback `Host` the Origin guard should accept before clients use `/ws` or `/auth`. Publishing the port on loopback looks like `-e SEVN_ALLOWED_HOSTS=127.0.0.1:8787`. `/health` is not guarded.

## Commands

| Purpose | Command | When |
|---------|---------|------|
| setup | `make setup` | Fresh checkout |
| format | `make format` | Before committing |
| lint | `make lint` | After every edit batch: `ruff check` + `ruff format --check`, `biome check`, `cargo fmt --check` + `cargo clippy -D warnings`, swiftlint, on present components |
| typecheck | `make typecheck` | After every edit batch (pyright strict, `tsc --noEmit`) |
| test | `make test` | All unit tests of present components; no secrets required. `PYTEST_ARGS=…` passes pytest flags |
| test (one component) | `make test-host` · `make test-web` · `make test-link` · `make test-edge` · `make test-apple` | Iteration |
| test (run marked) | `make test RUN_MARKED=1` | Runs expected-failure / skipped RED tests as ordinary tests (see Testing) |
| db heads | `make db-heads` | Prints Alembic heads; fails unless exactly one head (see K-MIG) |
| contracts | `make contracts` | Regenerate TS + Swift contracts from Pydantic; `make contracts-check` fails on drift |
| e2e | `make e2e` | Playwright smoke against a local `sevn serve` |
| ci-fast | `make ci-fast` | lint + typecheck + contracts-check, for mid-wave checks |
| ci | `make ci` | Full pre-merge gate (ci-fast + test + e2e + builds) |

## License

[MIT](LICENSE)
