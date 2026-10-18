# sevn

sevn is a personal, local-first host for persistent AI bots. A bot runs one agent per request. Clients speak one protocol to the host over WebSocket. Secrets and conversation data stay on the host.

## Quick start

Set a provider key, start the host, and open the chat. `sevn secret set` reads the value with no echo and stores it in the secret backend. The value is never printed.

```bash
sevn secret set provider/anthropic
sevn serve --open
```

Create a bot and send a message. The reply streams into the chat. `sevn secret list` prints names only. `sevn secret rm <name>` deletes one. The same commands take `provider/openai`, `provider/google`, and `provider/openrouter`. Ollama needs no key; set `SEVN_OLLAMA_URL` instead.

Pydantic AI approvals stay waiting across a host restart, and answering one resumes the turn. A Claude turn waiting on approval does not: Claude holds that answer in memory, so a restart marks the turn interrupted and you send the message again. Cancelling a turn is kept if the host stops before the model finishes, so that request is not sent again.

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
