<!-- generated: do not edit by hand; run `make faq-generate` -->

# Frequently Asked Questions (FAQ)

## Table of contents

- [General](#general)
  - [What is sevn.bot?](#what-is-sevnbot)
  - [Which channels can I talk to sevn.bot through?](#which-channels-can-i-talk-to-sevnbot-through)
  - [How do I install and run sevn.bot?](#how-do-i-install-and-run-sevnbot)
  - [How can I contribute to the project?](#how-can-i-contribute-to-the-project)
  - [What are skills and how do they extend sevn.bot?](#what-are-skills-and-how-do-they-extend-sevnbot)
- [Technical Q&A](#technical-qa)
  - [How does a single turn flow through the system?](#how-does-a-single-turn-flow-through-the-system)
  - [How does sevn.bot guard against unsafe or risky requests?](#how-does-sevnbot-guard-against-unsafe-or-risky-requests)
  - [How are secrets and credentials managed?](#how-are-secrets-and-credentials-managed)
  - [How does sevn.bot remember context across conversations?](#how-does-sevnbot-remember-context-across-conversations)
  - [Is there a command-line interface for operating sevn.bot?](#is-there-a-command-line-interface-for-operating-sevnbot)

## General

### What is sevn.bot?

sevn.bot is a single AI assistant that you own and that lives in the channels you already use, such as Telegram or a browser. It remembers context across sessions, runs on the LLM provider you choose, and gets work done by composing tools, skills, and external integrations under your control. The [architecture overview](../about-sevn.bot/ARCHITECTURE.md) describes the turn spine that connects a channel message all the way through to a reply.

### Which channels can I talk to sevn.bot through?

Today sevn.bot ships with a Telegram adapter and a browser-based Web UI bridge, with voice input/output layered on top of the gateway. Every channel talks to the same triage and executor pipeline, so the assistant behaves consistently no matter which surface you use. See [channels subsystem README](readmes/channels.md) for the adapter patterns and how new channels plug into the turn spine.

### How do I install and run sevn.bot?

The project ships a Makefile with setup and install targets, plus Docker Compose files for local or production deployment, so you can pick whichever workflow fits your environment. Configuration lives in a workspace sevn.json file that controls channels, models, and enabled skills. Start with [getting started guide](../about-sevn.bot/getting-started.html) for the step-by-step operator walkthrough.

### How can I contribute to the project?

Contributions are welcome via pull requests that follow the project's conventional-commit style and pass the CI gates defined in the Makefile. Before opening a change, read [CONTRIBUTING.md](../CONTRIBUTING.md) for the local setup, linting, and test commands expected of every submission, and check open issues for good first tasks.

### What are skills and how do they extend sevn.bot?

Skills are self-contained capability bundles the assistant can load on demand, ranging from bundled core skills to workspace-specific ones an operator adds. They let sevn.bot pick up new abilities, like querying an API or running a specialised workflow, without changing the core agent runtime. The [skills system README](readmes/skills.md) catalogs the bundled and workspace skill loaders and subprocess runners.

## Technical Q&A

### How does a single turn flow through the system?

A turn moves through a fixed spine: a channel receives a message, hands it to the gateway, which runs triage to size and route the work, then dispatches it to a tier-appropriate executor that calls tools and skills before producing a reply. Secrets and LLM calls are routed through a paired egress proxy rather than being called directly. The [agent runtime README](readmes/agent.md) documents the triager, tier-B/C executors, and sandboxing that back this pipeline.

### How does sevn.bot guard against unsafe or risky requests?

Built-in safety checks screen requests before they run, combining an LLM Guard scanner with a llmignore mechanism and a block-and-notify flow so risky actions surface to the operator instead of executing silently. This scanning layer sits ahead of tool execution in the turn spine and is implemented in [LLM Guard scanner implementation](../src/sevn/security/llm_guard_scanner.py), with the broader model described in [security scanner README](readmes/security.md).

### How are secrets and credentials managed?

Secrets live behind pluggable backends selected by a logical-key chain, with per-secret TTLs and a fingerprint confirmation step before a sensitive value is used, so credentials are never handed to a model or tool without an explicit, auditable check. The fingerprinting logic itself is implemented in [secrets fingerprint module](../src/sevn/secrets/fingerprint.py), and the full backend/TTL model is documented in [secrets subsystem README](readmes/secrets.md).

### How does sevn.bot remember context across conversations?

Memory is backed by an LCM (long-context memory) store that compacts older turns, maintains a per-user model, and can run background 'dreaming' passes to consolidate what it has learned, with optional Honcho integrations for richer recall. This lets the assistant reference earlier conversations without replaying the full transcript on every turn. Details live in [memory & context README](readmes/memory-context.md).

### Is there a command-line interface for operating sevn.bot?

Yes, the sevn command-line interface is the operator entry point for tasks like generating READMEs, managing configuration, and running diagnostics, and it is registered through the project's packaging metadata. The CLI's top-level application wiring lives in [CLI application entry point](../src/sevn/cli/app.py), which is a good starting point for tracing how subcommands are registered.
