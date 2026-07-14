<!-- generated: do not edit by hand; run `sevn readme update secrets` -->
# Secrets — Secrets backends, logical keys, fingerprint confirmation, and gateway-vs-proxy split

[![Spec][spec-badge]][spec-link]
[![Source][source-badge]][source-link]
[![Index][index-badge]][index-link]

> **Summary.** Secrets backends, logical keys, fingerprint confirmation, and gateway-vs-proxy split.

## Level 1 — Overview (non-technical)

**Secrets** is a core part of sevn.bot — the personal AI assistant you run on your own machine. Secrets backends, logical keys, fingerprint confirmation, and gateway-vs-proxy split.

In everyday use, secrets helps Sevn do its job reliably: you interact through familiar channels (Telegram, browser, voice), and this layer keeps those interactions safe, consistent, and under your control.

## Level 2 — How it works (technical)

### Components and layout

Implementation spans `src/sevn/secrets/`, `src/sevn/security/secrets/`. The package contains 17 Python module(s); primary entry points include `src/sevn/secrets/__init__.py`, `src/sevn/secrets/fingerprint.py`, `src/sevn/secrets/migrate.py`, `src/sevn/security/secrets/__init__.py`, `src/sevn/security/secrets/backends/__init__.py`, `src/sevn/security/secrets/backends/encrypted_file.py`, and 11 more.

### Data and control flow

Secrets is organized around `  init  `, `fingerprint`, `migrate`, `  init  `, and 2 more under `src/sevn/secrets/`; implementation spans `src/sevn/secrets/`, `src/sevn/security/secrets/`. Primary entry points include fingerprint.py (fingerprint_sha256_hex), migrate.py (secrets_dir_under_content_root), encrypted_file.py (default_encrypted_store_path), linux_secret_service.py (LinuxSecretServiceBackend.get).

### Configuration

Operator settings come from `sevn.json` in the workspace. Related normative specs: `about-sevn.bot/specs/06-secrets.md`. Run `sevn config validate` after edits; use `sevn doctor` to confirm the install sees the expected layout.

### Key modules

- `src/sevn/secrets/fingerprint.py` — `fingerprint_sha256_hex`
- `src/sevn/secrets/migrate.py` — `secrets_dir_under_content_root`, `legacy_plaintext_entries`, `remove_legacy_plaintext_artifacts`, `encrypted_file_backend_for_workspace`
- `src/sevn/security/secrets/backends/encrypted_file.py` — `default_encrypted_store_path`, `EncryptedFileBackend.get`, `EncryptedFileBackend.load_decrypted_map`, `EncryptedFileBackend.set`
- `src/sevn/security/secrets/backends/linux_secret_service.py` — `LinuxSecretServiceBackend.get`, `LinuxSecretServiceBackend.set`, `LinuxSecretServiceBackend.delete`
- `src/sevn/security/secrets/backends/macos_keychain.py` — `MacOSKeychainBackend.get`, `MacOSKeychainBackend.set`, `MacOSKeychainBackend.delete`

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
