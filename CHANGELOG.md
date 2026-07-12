# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Every user-visible code change adds a bullet under `## [Unreleased]`; those bullets
are cut into a dated, versioned section at release time.

## [Unreleased]

### Added

- Core runtime packages for the pre-0.0.1 migration import (config, storage, workspace, gateway, agent, security, proxy, and related tests)
- Configurable Second Brain vault path via `second_brain.paths.vault` (CLI setup, Telegram `/config`, onboarding, doctor)

### Changed

### Deprecated

### Removed

### Fixed

### Security

## [0.0.1] - 2026-07-08

First public release on [github.com/sevn-bot/sevn](https://github.com/sevn-bot/sevn).

### Added

- Multi-channel AI gateway (Telegram, Web UI, voice hooks) with tiered agent runtime
- Paired egress proxy, secrets backends, Mission Control dashboard, and workspace memory
- Onboarding wizard (`sevn onboard`), CLI, and `make setup` developer bootstrap
- Full Python package under `src/sevn/` with CI via `make ci`

### Changed

- Repository canonical home moved from the private `sevn-bot/sevn.bot` checkout to the public `sevn-bot/sevn` repo
