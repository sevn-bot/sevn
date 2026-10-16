# Spike S2 — CLI runtimes

Live scenarios were re-run for Claude, Codex, and OpenCode in one pytest session
(12 passed, 269.28s). Cursor was run separately. Login gates were not rechecked;
they stayed at the W2.R outcomes. First-text times below are `first_text_s` from
that session. Claude does not record one.

## Scenarios

| Runtime | tool call | permission | resume | interrupt | First text |
| --- | --- | --- | --- | --- | --- |
| claude | passed | passed | passed | passed | not recorded |
| codex | passed | passed | passed | passed | 4.354s, 2.970s, 3.201s / 3.198s, 3.583s then 17.542s |
| opencode | passed | passed | passed | passed | 82.637s, 11.620s, 8.604s / 3.289s, 14.365s then 4.225s |
| cursor | failed | failed | failed | failed | no turn started |

Codex and OpenCode columns are echo, permission, resume (first turn / second turn),
then the interrupted turn and the follow-up. The interrupted turn's time is until
the first text, after which the turn ends with `error` / `interrupted`.

Resume closes the process and opens a new one with the saved ref. The follow-up
answer contained `ping`. Interrupt returns from `session.interrupt()` without
waiting for the turn; the same process then accepts another turn and keeps the
same ref.

Cursor: `cursor-agent status` is authenticated, and `initialize` succeeds.
`session/new` returns JSON-RPC `-32000` `Authentication required`. All four
scenarios fail at session open. This is bonus D6, so the spike does not fail
with it. Verdict for Cursor is `no-go`.

## Event mapping

Native messages are reduced to a small JSON object and passed through
`map_native_event`. `ignored` events keep a `native_type` that is listed for
that runtime. Unknown types are dropped from fixtures.

| Native | RuntimeEvent |
| --- | --- |
| Codex `thread/start`, `thread/resume`, `thread/started` | `session_bound` |
| Codex `item/agentMessage/delta` | `text_delta` |
| Codex `item/reasoning/textDelta`, `summaryTextDelta` | `thinking_delta` |
| Codex `item/started` for mcp, shell, dynamic tool, file change | `tool_call_started` |
| Codex `item/completed` | `tool_call_finished` (`ok` false when failed or declined) |
| Codex approval and MCP elicitation requests | `permission_request` |
| Codex `turn/completed` status `interrupted` | `error` `interrupted` |
| Codex `turn/completed` status `failed` | `error` `failed` |
| Codex `turn/completed` otherwise | `turn_finished` |
| ACP session id from `session/new` or `session/load` | `session_bound` |
| ACP `agent_message_chunk` | `text_delta` |
| ACP `agent_thought_chunk` | `thinking_delta` |
| ACP `tool_call` | `tool_call_started` |
| ACP `tool_call_update` completed or failed | `tool_call_finished` |
| ACP `session/request_permission` | `permission_request` |
| ACP prompt `stopReason` `cancelled` | `error` `interrupted` |
| ACP `refusal`, `max_tokens`, `max_turn_requests` | `error` |
| ACP other stop reasons | `turn_finished` |

## Quirks

Codex app-server speaks NDJSON JSON-RPC on stdio. The pinned CLI (0.146.0)
rejects a configured model that is newer than that pin, so each process sets
`-c model="gpt-5.6-sol"` (a model in this CLI's catalog). MCP is two `-c`
overrides (`url`, `bearer_token_env_var`); the env var holds the raw token and
the CLI adds `Bearer`. Do not run `codex mcp add`; that writes the user config.
`approvalPolicy` is `untrusted` and `sandbox` is `workspace-write`. File writes
still raise `item/fileChange/requestApproval`. `sevn_echo` also raises
`mcpServer/elicitation/request`. Command and file decisions are `accept` or
`decline`. `decline` continues the turn. `turn/interrupt` is a request.
`thread/resume` replays notifications for the previous turn; the adapter keeps
only the turn id returned by `turn/start`. `account/*` and `remoteControl/*`
are not recorded. A `account/chatgptAuthTokens/refresh` request is answered
with JSON-RPC `-32601`. The token file is not read.

OpenCode `session/request_permission` offers `allow_once`, `allow_always`, and
`reject_once`. Selecting `reject_once` ends the prompt with `stopReason:
cancelled` (the turn aborts instead of letting the model retry). A denial is
therefore enforced by making the workspace read-only and selecting
`allow_once`, so the write fails and the model asks again. The approve path
restores write permission and selects `allow_once`. The process-local config
directory sets every permission to `ask` and
`experimental.continue_loop_on_deny`. The user's config is not modified.
`OPENCODE_DISABLE_FILEWATCHER` and `OPENCODE_FAST_BOOT` keep this process from
indexing other projects. `session/load` resumes after the process exits.
`session/cancel` is the interrupt.

Cursor uses the same ACP client. Session open fails as described above.

## Process model

Each spike session is one OS process.

Codex `app-server` can multiplex many threads on one process. This spike starts
one thread per process so a crash or interrupt stays local. Plans 0010 and 0030
can share one app-server across sessions and still resume by thread id.

Claude Code, OpenCode, and Cursor are one agent process per session.
`opencode acp` spawns `opencode serve --stdio` as its child. There is no
cross-session multiplex on those CLIs.

## State sevn must not read

Each CLI keeps its own resume and credential state. sevn stores the visible
conversation and the resume id the CLI returns. It must not read:

| CLI | Leave unread |
| --- | --- |
| Claude | the store written by `claude auth login` |
| Codex | `~/.codex` (`auth.json`, `config.toml`, session rolls) |
| OpenCode | `~/.local/share/opencode` (including `opencode.db` and `log`), `~/.config/opencode`, `~/.local/state/opencode`, `~/.cache/opencode` |
| Cursor | the store behind `cursor-agent status` |

## Terms (spec §4)

The user signs in to the unmodified CLI. sevn does not inject or read that
credential. Claude subscription use is acceptable for the owner's own machine
and risky if sevn is shipped to other people. Codex `app-server` is the
official surface. OpenCode and Cursor are reached through ACP `session/new`
`mcpServers`, not by reading their auth files.

## Runtime protocol for 0010 / 0030

The spike session is `open_session` / `turn` / `interrupt` / `aclose`. The host
seam should be the spec A.2.1 protocol. `answer` is the permission callback.

```python
class Runtime(Protocol):
    async def open(self, agent: AgentRecord) -> SessionRef: ...
    def run_turn(self, turn: TurnContext) -> AsyncIterator[RuntimeEvent]: ...
    async def answer(self, pending_id: str, answer: PendingAnswer) -> None: ...
    async def interrupt(self, agent_id: str) -> None: ...
    async def close(self, agent_id: str) -> None: ...
```
