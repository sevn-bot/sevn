<!-- curated: hand-authored; after source changes review the body, then run `sevn readme fingerprint secrets` -->
# Secrets — Secrets backends, logical-key chain, TTL, and fingerprint confirmation

[![Spec][spec-badge]][spec-link]
[![Source][source-badge]][source-link]
[![Index][index-badge]][index-link]

> **Summary.** Secrets backends, logical-key chain, TTL, and fingerprint confirmation.

## Level 1 — Overview (non-technical)

**Secrets** is how sevn.bot stores and resolves credentials without scattering plaintext across config files. Operator-facing values — Telegram tokens, the gateway bearer token, Mission Control login, webhook secrets — live in an ordered **backend chain** (macOS Keychain, Linux Secret Service, encrypted file, optional OpenBao/Proton Pass). Provider API keys for LLM vendors are resolved in the **egress proxy**, not in the gateway turn spine.

When you confirm a secret on the CLI, sevn shows a **fingerprint** (SHA-256 hex) so you can verify you typed the right value without echoing it. Mission Control lets the **owner** reveal `${SECRET:…}` aliases and store entries for audit — every reveal is logged.

## Level 2 — How it works (technical)

Implementation spans [`src/sevn/secrets/`](../../src/sevn/secrets/) (operator helpers) and [`src/sevn/security/secrets/`](../../src/sevn/security/secrets/) (backends, chain, factory).

### Gateway vs egress proxy

| Secret class | Resolved where | Typical keys |
| --- | --- | --- |
| Channel + gateway auth | **Gateway** via [`secrets_chain_from_workspace`](../../src/sevn/security/secrets/factory.py#L283) | Telegram bot token, `gateway.token`, dashboard login password refs |
| Provider API keys | **Egress proxy** ([`credentials.py`](../../src/sevn/proxy/credentials.py)) | Anthropic/OpenAI/Bedrock keys injected on `/llm/*` |
| Trace export tokens | Gateway boot async path | `tracing.sinks[].token_ref` for OTLP/Logfire |

The gateway **does** call [`secrets_chain_from_workspace`](../../src/sevn/security/secrets/factory.py#L283) for channel tokens, webhook secrets, and Mission Control login resolution ([`DashboardAuthService`](../../src/sevn/ui/dashboard/services/auth.py) resolves `${SECRET:…}` login passwords and gateway tokens at boot). Provider keys stay on the proxy side of the trust boundary.

### Backend chain and TTL

[`secrets_chain_from_workspace`](../../src/sevn/security/secrets/factory.py#L283) builds a [`SecretsChain`](../../src/sevn/security/secrets/chain.py) from `sevn.json` → `secrets_backend.chain` (or platform defaults via [`default_chain_entries`](../../src/sevn/security/secrets/factory.py#L64)). Reads walk the chain in order; writes honour `write_targets`. [`ResolvedSecretsCache`](../../src/sevn/security/secrets/cache.py) adds a TTL cache so hot paths do not hammer OS keychains.

Legacy plaintext `.sevn/secrets/` promotion: [`migrate.py`](../../src/sevn/secrets/migrate.py) in the operator package.

### Mission Control reveal API

Owner-only, CSRF-guarded endpoints:

| Route | Handler | Purpose |
| --- | --- | --- |
| `GET /api/v1/secrets/aliases/{logical_key}/reveal` | [`secrets_alias_reveal`](../../src/sevn/ui/dashboard/api/ops.py#L1094) | Resolve `${SECRET:…}` config alias plaintext |
| `GET /api/v1/secrets/store/entries/{alias}` | [`secrets_store_entry_reveal`](../../src/sevn/ui/dashboard/api/secrets_store.py#L163) | Reveal one logical store entry |

Both emit audited `mission.secrets.read` events via [`emit_mission_audit`](../../src/sevn/ui/dashboard/services/mission_audit.py).

### Fingerprint confirmation

[`fingerprint_sha256_hex`](../../src/sevn/secrets/fingerprint.py#L15) returns a stable 64-char hex digest for CLI confirmation (`sevn gateway set-token`, dashboard password setup) without logging plaintext.

### Configuration (`sevn.json` → `secrets_backend`)

Key knobs (full schema: [`infra/sevn.schema.json`](../../infra/sevn.schema.json)):

- `chain[]` — ordered backend entries (encrypted file, keychain, OpenBao, …)
- `write_targets` — which backend labels accept writes
- `encrypted_file.path`, `master_key_source` — encrypted-file backend
- Env: `SEVN_SECRETS_MASTER_KEY` (64 hex chars) parsed by [`parse_optional_master_key_hex`](../../src/sevn/security/secrets/factory.py#L82)

Validate after edits: `sevn config validate`; `sevn doctor` probes the chain.

### Key modules

- [`factory.py`](../../src/sevn/security/secrets/factory.py) — [`secrets_chain_from_workspace`](../../src/sevn/security/secrets/factory.py#L283), backend construction
- [`chain.py`](../../src/sevn/security/secrets/chain.py) — ordered read/write policy
- [`fingerprint.py`](../../src/sevn/secrets/fingerprint.py) — [`fingerprint_sha256_hex`](../../src/sevn/secrets/fingerprint.py#L15)
- [`secrets_store.py`](../../src/sevn/ui/dashboard/api/secrets_store.py) — Mission Control store CRUD + reveal
- [`ops.py`](../../src/sevn/ui/dashboard/api/ops.py) — config alias reveal

Normative spec: [`about-sevn.bot/specs/06-secrets.md`](../../about-sevn.bot/specs/06-secrets.md).

## Level 3 — Deep dive (low-level, technical)

Primary source tree: [`src/sevn/secrets`](../../src/sevn/secrets/) (17 Python files). Normative design: `about-sevn.bot/specs/06-secrets.md`.

### Module inventory

Operator-facing secrets helpers outside sevn.security (about-sevn.bot/specs/06-secrets.md).

Working with [`__init__.py`](../../src/sevn/secrets/__init__.py): inspect the public entry points below.

Stable fingerprints for operator CLI confirmation (about-sevn.bot/specs/06-secrets.md §2.6).

Working with [`fingerprint.py`](../../src/sevn/secrets/fingerprint.py): inspect the public entry points below.
Start with [`fingerprint_sha256_hex`](../../src/sevn/secrets/fingerprint.py#L15).

Legacy plaintext .sevn/secrets promotion (about-sevn.bot/specs/06-secrets.md §10.2).

Working with [`migrate.py`](../../src/sevn/secrets/migrate.py): inspect the public entry points below.
Start with [`secrets_dir_under_content_root`](../../src/sevn/secrets/migrate.py#L42), then [`legacy_plaintext_entries`](../../src/sevn/secrets/migrate.py#L59), [`remove_legacy_plaintext_artifacts`](../../src/sevn/secrets/migrate.py#L122), [`encrypted_file_backend_for_workspace`](../../src/sevn/secrets/migrate.py#L154).

Secrets abstraction for the trust boundary (about-sevn.bot/specs/06-secrets.md).

Working with [`__init__.py`](../../src/sevn/security/secrets/__init__.py): inspect the public entry points below.

Concrete secret backends (about-sevn.bot/specs/06-secrets.md §4.1).

This package uses optional native dependencies where required; unsupported
environments surface as missing keys rather than crashing on import.

Working with [`__init__.py`](../../src/sevn/security/secrets/backends/__init__.py): inspect the public entry points below.

Encrypted JSON map on disk with AEAD (about-sevn.bot/specs/06-secrets.md §3.1).

Working with [`encrypted_file.py`](../../src/sevn/security/secrets/backends/encrypted_file.py): inspect the public entry points below.
Start with [`default_encrypted_store_path`](../../src/sevn/security/secrets/backends/encrypted_file.py#L79), then [`EncryptedFileBackend.get`](../../src/sevn/security/secrets/backends/encrypted_file.py#L341), [`EncryptedFileBackend.load_decrypted_map`](../../src/sevn/security/secrets/backends/encrypted_file.py#L365), [`EncryptedFileBackend.set`](../../src/sevn/security/secrets/backends/encrypted_file.py#L386).

Linux secret service via optional secretstorage (about-sevn.bot/specs/06-secrets.md §3.2).

Working with [`linux_secret_service.py`](../../src/sevn/security/secrets/backends/linux_secret_service.py): inspect the public entry points below.
Start with [`LinuxSecretServiceBackend.get`](../../src/sevn/security/secrets/backends/linux_secret_service.py#L92), then [`LinuxSecretServiceBackend.set`](../../src/sevn/security/secrets/backends/linux_secret_service.py#L106), [`LinuxSecretServiceBackend.delete`](../../src/sevn/security/secrets/backends/linux_secret_service.py#L141).

macOS Keychain via security CLI (about-sevn.bot/specs/06-secrets.md §3.2).

Working with [`macos_keychain.py`](../../src/sevn/security/secrets/backends/macos_keychain.py): inspect the public entry points below.
Start with [`MacOSKeychainBackend.get`](../../src/sevn/security/secrets/backends/macos_keychain.py#L67), then [`MacOSKeychainBackend.set`](../../src/sevn/security/secrets/backends/macos_keychain.py#L99), [`MacOSKeychainBackend.delete`](../../src/sevn/security/secrets/backends/macos_keychain.py#L145).

OpenBao / Vault OSS KV v2 read path (about-sevn.bot/specs/06-secrets.md §3.2).

Working with [`openbao.py`](../../src/sevn/security/secrets/backends/openbao.py): inspect the public entry points below.
Start with [`OpenBaoBackend.get`](../../src/sevn/security/secrets/backends/openbao.py#L123), then [`OpenBaoBackend.set`](../../src/sevn/security/secrets/backends/openbao.py#L154), [`OpenBaoBackend.delete`](../../src/sevn/security/secrets/backends/openbao.py#L181).

Proton Pass CLI bridge (about-sevn.bot/specs/06-secrets.md §3.2).

Working with [`proton_pass.py`](../../src/sevn/security/secrets/backends/proton_pass.py): inspect the public entry points below.
Start with [`ProtonPassCliBackend.get`](../../src/sevn/security/secrets/backends/proton_pass.py#L165), then [`ProtonPassCliBackend.set`](../../src/sevn/security/secrets/backends/proton_pass.py#L193), [`ProtonPassCliBackend.delete`](../../src/sevn/security/secrets/backends/proton_pass.py#L232).

TTL cache for resolved secret strings (about-sevn.bot/specs/06-secrets.md §2.2).

Working with [`cache.py`](../../src/sevn/security/secrets/cache.py): inspect the public entry points below.
Start with [`ResolvedSecretsCache.chain`](../../src/sevn/security/secrets/cache.py#L66), then [`ResolvedSecretsCache.ttl_seconds`](../../src/sevn/security/secrets/cache.py#L80), [`ResolvedSecretsCache.get_resolved`](../../src/sevn/security/secrets/cache.py#L110).

Ordered backend chain with read/write policy (about-sevn.bot/specs/06-secrets.md §2.2, §5).

Working with [`chain.py`](../../src/sevn/security/secrets/chain.py): inspect the public entry points below.
Start with [`SecretsChain.backends`](../../src/sevn/security/secrets/chain.py#L59), then [`SecretsChain.get`](../../src/sevn/security/secrets/chain.py#L72), [`SecretsChain.get_resilient`](../../src/sevn/security/secrets/chain.py#L92), [`get_secret_resilient`](../../src/sevn/security/secrets/chain.py#L169).

5 more Python files under [`src/sevn/secrets`](../../src/sevn/secrets/) — including `src/sevn/security/secrets/errors.py`, `src/sevn/security/secrets/factory.py`, `src/sevn/security/secrets/passphrase_prime.py`, `src/sevn/security/secrets/protocol.py`.

### Extension and invariants

Follow [`06-secrets.md`](../../about-sevn.bot/specs/06-secrets.md) for merge gates, error semantics, and compatibility constraints. After code changes under [`src/sevn/secrets`](../../src/sevn/secrets/), run `sevn readme update secrets` and `make readme-check`.

## References

- [../../about-sevn.bot/specs/06-secrets.md](../../about-sevn.bot/specs/06-secrets.md)

[spec-badge]: https://img.shields.io/badge/Spec-2a7fc6?style=for-the-badge&logo=readthedocs&logoColor=white
[spec-link]: ../../about-sevn.bot/specs/06-secrets.md
[source-badge]: https://img.shields.io/badge/Source-0c0a09?style=for-the-badge&logo=github&logoColor=white
[source-link]: ../../src/sevn/secrets/
[index-badge]: https://img.shields.io/badge/All_READMEs-5fb1f7?style=for-the-badge&logo=markdown&logoColor=white
[index-link]: INDEX.md
