# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

- Bot core review fixes: a bot's shell can no longer read other bots' workspaces when the sevn home is outside the user's home, a finished message cannot be moved and run again, moving a waiting job closes its turn, `user.ask` questions stay in the thread, Ollama models can be selected, auto-approved low-risk shell commands finish, cancelling a turn releases its path locks, a follow-up to an idle agent respects the bot's parallel cap, sibling lanes each see memory changes, and CI actions are pinned to commits. A `#` comment no longer hides later lines from the shell risk scorer, creating a worktree runs no checkout filter from the bot's git config, the confined shell gets a writable `TMPDIR`, compaction keeps each tool call with its result, memory and agent tools stay within the caller's bot, `memory.search` returns ids and revisions, and a failed call can be retried with the same `op_id`.
- The workspace shell no longer reads the home directory outside git's config and toolchain installs, keeps no host secrets in its environment, cannot reach the keychain, pasteboard or Apple Events on macOS, and runs in its own namespaces on Linux. Commands time out after 300 seconds, stop with their process group on cancel, and show the model the exit code and stderr. Under `auto` only read-only commands skip approval, `history.read` stays within the bot, and a cancelled queued turn never runs.
- Jev router with a no-key fallback chain, parallel agents with workspace isolation, memories, sandboxed workspace tools, allow_all, compaction, and decision evals (off by default).
- Event replay is paged so a reconnect cannot overflow the session, an approval no longer blocks other calls, and exception text is redacted in logs.
- mergeCraft review runs v0.1.0a4 and can read CI runs.
- Database upgrades keep the initial tables as they shipped, so a later column can be added without colliding, including from a packaged install even when a parent directory has another project's alembic.ini.
- A model error keeps text already streamed and a fixed failure notice, and cancelling a turn survives a restart.
- A crashed turn resumes on startup, a message sent during an approval waits, and a failed turn is reported.
- Bots and agents with Pydantic AI and Claude runtimes; web chat with approvals.
- Spike S3: A2UI v0.9.1 on React and SwiftUI with sevn custom components.
- CI reviews pull requests with mergeCraft on OpenCode Go (DeepSeek V4.1 Flash).
- Spike S2: subscription CLI runtimes with sevn MCP tools.
- Foundation: `sevn serve` with WebSocket protocol (handshake, idempotent calls, durable events with replay), SPA shell, Docker image.
