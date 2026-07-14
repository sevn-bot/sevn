# Security Policy

## Reporting a Vulnerability

Please **do not** open a public issue for security vulnerabilities.

Report privately via [GitHub Security Advisories](https://github.com/sevn-bot/sevn/security/advisories/new).
You will receive an acknowledgement as soon as possible.

## Supported Versions

This project is under active early development; only the latest `main` is supported.

## Security model

Product security architecture — scanner/llmignore policy, secrets backends, and
Mission Control reveal flows — is documented in
[`docs/readmes/security.md`](docs/readmes/security.md) and
[`docs/readmes/secrets.md`](docs/readmes/secrets.md). Provider API keys are brokered
through the egress proxy (`docs/readmes/proxy-egress.md`); channel tokens and gateway
credentials resolve in the gateway process.
