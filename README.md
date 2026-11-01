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

## Bots and agents

A bot has a runtime, a model, instructions, a workspace, an access level, an approval policy, and a network flag. Network stays off until you turn it on for that bot. Several agents of one bot can run at once, up to `bots.max_parallel_agents` (default 3). The host also caps running turns at `runtime.max_running_turns` (default 3). A new task past the bot cap waits, and the chat shows how many jobs are ahead.

Each agent owns one thread. Statuses are `running`, `waiting`, `idle`, `done`, and `archived`. A finished turn with nothing pending becomes idle. Idle for 24 hours becomes done, and done for 7 days becomes archived. A follow-up sent to a done or archived agent continues the same thread. Each turn's instructions name up to ten other open agents of that bot, with title and status.

Every agent gets its own `tasks/<agent_id>/` folder inside the bot workspace. The folder stays when the agent is archived. A write outside that folder takes an advisory lock for ten minutes, refreshed on each write. A second agent that writes the same path gets `path_locked`, with the holder's id and title. Locks are released when the turn finishes and when the agent is done. Writes inside the agent's own scratch folder are not locked.

New agents start with isolation `shared`, so file tools and the shell use the bot workspace. When an agent's isolation is `worktree` and that workspace is a git repository, those tools use a git worktree at `<sevn-home>/worktrees/<agent_id>` on branch `sevn/<agent_id>`. Its parent is host-managed, outside bot-writable workspaces, so a sibling cannot replace the checkout root. A workspace that is not a git repository stays on the scratch folder.

## Routing

Every incoming message is routed, and the choice is written to the decision log. Rules run first, and the first match wins: a reply to an agent's message, an explicit agent, a message that is `/new` or starts with `/new `, a `/continue` prefix that matches exactly one open title, or a user reply within ten minutes of the only pending question. Plugins can add earlier rules for a source.

If no rule matches, the host asks jev (`decisions.jev_model`, default `jev-1.13.0`) one request covering the intent and the target agent. When an open agent is running, that request also asks whether to queue, steer, or interrupt. The text sent out is redacted. The jev key is the secret `provider/typesafe`, or the `TYPESAFE_API_KEY` environment variable. Intent must reach 0.70, the target 0.65, and the busy question 0.60 (`decisions.thresholds` in `$SEVN_HOME/config.toml`). A busy answer below its gate rejects the jev route. The accepted route follows the intent, and the busy label is stored on the decision log.

Below a gate, or when jev has no key or does not answer, the host walks a fallback chain. A step whose own confidence is under 0.6 moves on:

1. A Pydantic AI model, when a provider key is configured (`decisions.llm_model`, otherwise the cheapest configured model).
2. Local Ollama, when `SEVN_OLLAMA_URL` answers `/api/chat` (`decisions.ollama_model`, default `llama3.2:3b`).
3. When the bot runtime is Claude, one tool-less prompt in a throwaway session that is closed afterward. This call spends that runtime's subscription quota. `decisions.allow_cli_fallback` defaults to true and turns the step off when set to false.
4. A deterministic default: one open agent is continued; none starts a new task; more than one asks you, with a chip for a new task and one chip per open title.

`decisions.provider` defaults to `jev`. `rules` stops after the rules and does not call a model; with no rule match the route is a new task. `llm` skips jev and starts at the Pydantic AI step.

The route then runs. A new request starts an agent. Chit-chat starts an agent with no tools and closes it after one reply. A follow-up queues on the target. Steer injects the text into a running Pydantic AI turn; other runtimes queue it. An answer fills the pending question. Cancel stops the agent.

**Move to…** and **Start new** call `messages.reroute`. A job that has not started moves. A running turn is cancelled and the job is queued on the new agent. The decision log stores `corrected_to`, and the host emits `route.corrected`.

## Memory

A bot stores memories in two tiers, `pinned` and `recall`, and searches them with FTS5. The agent can save, search, forget, and pin. Pinned text shares one budget, `memory.pinned_budget` (default 4 KB). The bot settings list memories and can edit, pin, unpin, and delete them.

The memory block is added to the user turn and labelled untrusted data. Later turns receive a diff of what changed. Writes from a turn are staged and committed only when that turn succeeds. A failed or cancelled turn keeps none of them. Writes for one bot are serialized. The bot cannot change a tier whose origin is the user (`memory_locked`).

The host does not save a memory on its own. After a successful turn, a jev score of at least 0.8 that the user stated a durable fact or preference adds a one-line hint on that agent's next turn to consider `memory.save`.

## Sandbox

The bot access level defaults to `workspace`. Bot settings can switch the level and the network flag.

Claude Code's native tools currently run without sevn's OS confinement. Claude bots therefore require explicitly selected `access=full` and `network=on`; other combinations fail before the CLI session opens. Tool approvals remain required. Use Pydantic AI for workspace confinement, isolated execution, or network-off tools.

`workspace` file tools resolve paths and refuse anything outside the bot workspace and the `Shared` directory next to the workspaces folder (`path_outside_workspace`). The shell runs under Seatbelt on macOS, using `host/src/sevn/sandbox/profiles/sevn-workspace.sb`, or under bubblewrap on Linux. The workspace and `Shared` are writable. The rest of the system is read-only, and your home directory is not readable at all except for git's config (`~/.gitconfig`, `~/.config/git`) and the usual toolchain installs (`~/.local/bin`, `~/.local/share/uv`, `~/.cargo/bin`, `~/.rustup/toolchains`, `~/.nvm/versions`, `~/.pyenv`, `~/.bun/bin`, `~/.deno/bin`, `~/go/bin`, pnpm). Reads and writes are also denied for `.ssh`, `.aws`, `Library/Keychains`, the CLI credential directories, and the sevn database, secrets, keys, run token and logs wherever `SEVN_HOME` puts them. On macOS the command can reach only the Mach services it needs for name lookup, logging, preferences, DNS and TLS trust, so the keychain, the pasteboard, `open` and Apple Events are out of reach. On Linux it runs in new namespaces (`--unshare-all`, `--new-session`), so it cannot see or signal host processes. Network follows the bot flag, which defaults to off. Other platforms do not run that confined command. Running the host itself inside Docker needs `--security-opt seccomp=unconfined --security-opt apparmor=unconfined --security-opt systempaths=unconfined` for bubblewrap to start.

Every shell command, at every level, gets only `PATH` (without the host's own virtualenv), `HOME`, `USER`, `LOGNAME`, `SHELL`, `TMPDIR`, `TERM`, `TZ` and the locale variables from the host environment, so provider keys, `TYPESAFE_API_KEY` and `SEVN_SECRET_*` values never reach it. A command runs for at most 300 seconds; on a timeout or a cancelled turn its whole process group is stopped. The model reads the exit code, stdout and stderr, each capped at 64 KB.

`workspace` and `isolated` run the shell inside that confinement without an approval prompt. `full` runs the shell with no confinement. `approval.risk` scores each `full` command as `low`, `medium`, `high`, or `destructive`. Only a command made entirely of known read-only programs (`ls`, `cat`, `grep`, `find` without `-delete` or `-exec`, and similar) with no output redirect, variable or command substitution is `low`; an unknown program, a write, or a line the scorer cannot parse is at least `medium`, and `git` is never `low`. With approval policy `auto`, a `low` command runs without asking and every other score waits. Policy `ask` waits on every `full` command. A bot policy of `allow_all` skips that wait and still uses the bot's access level. Recursive `rm` of `/` or the home directory, `sudo`, a `curl` or `wget` pipe into a shell, `dd` onto a device, and a redirect or `tee` onto a dotfile are always `destructive`.

`isolated` runs the command with `docker run --rm`, the workspace and `Shared` mounted, and the working directory set to the workspace. Network is off unless the bot flag is on. This level needs Docker.

Host sandbox mode defaults to `enforced`. A missing mode file means enforced. An owner can switch it with `host.set_sandbox_mode` only after confirming with the phrase `I understand`. `allow_all` runs every bot as `full` and skips approvals, so shell commands are neither confined nor held for review. The host emits an audit event, and `system.info` reports `caps.allow_all` so clients keep a banner up. Setting the mode back to `enforced` restores each bot's own level. The default config leaves `allow_all` off.

## Evals

`decisions.evals_on` defaults to false. `sevn evals run decisions` then prints `evals disabled`, replays nothing, and exports no decision state. When `evals_on` is true, the same command replays the synthetic routing cases in `host/evals/decisions/` and writes a local JSON report. A missing `judge-jev` binary skips the judge. The cases are synthetic messages.

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
