<!-- generated: do not edit by hand; run `sevn readme update secrets` -->
# Secrets — Secrets backends, logical keys, fingerprint confirmation — keys never in the gateway process

[![Spec][spec-badge]][spec-link]
[![Source][source-badge]][source-link]
[![Index][index-badge]][index-link]

> **Summary.** Secrets backends, logical keys, fingerprint confirmation — keys never in the gateway process.

## Level 1 — Overview (non-technical)

**Secrets** is a core part of sevn.bot — the personal AI assistant you run on your own machine. Secrets backends, logical keys, fingerprint confirmation — keys never in the gateway process.

In everyday use, secrets helps Sevn do its job reliably: you interact through familiar channels (Telegram, browser, voice), and this layer keeps those interactions safe, consistent, and under your control.

## Level 2 — How it works (technical)

### Components and layout

Implementation spans `src/sevn/secrets/`, `src/sevn/security/secrets/`. The package contains 17 Python module(s); primary entry points include `src/sevn/secrets/__init__.py`, `src/sevn/secrets/fingerprint.py`, `src/sevn/secrets/migrate.py`, `src/sevn/security/secrets/__init__.py`, `src/sevn/security/secrets/backends/__init__.py`, `src/sevn/security/secrets/backends/encrypted_file.py`, and 11 more.

### Data and control flow

Secrets is a supporting subsystem; see Level 3 for the module-level flow.

### Configuration

Operator settings come from `sevn.json` in the workspace. Related normative specs: `about-sevn.bot/specs/06-secrets.md`. Run `sevn config validate` after edits; use `sevn doctor` to confirm the install sees the expected layout.

### Key modules

- `src/sevn/secrets/fingerprint.py` — `fingerprint_sha256_hex`
- `src/sevn/secrets/migrate.py` — `secrets_dir_under_content_root`, `legacy_plaintext_entries`, `remove_legacy_plaintext_artifacts`, `encrypted_file_backend_for_workspace`
- `src/sevn/security/secrets/backends/encrypted_file.py` — `default_encrypted_store_path`, `EncryptedFileBackend.get`, `EncryptedFileBackend.load_decrypted_map`, `EncryptedFileBackend.set`
- `src/sevn/security/secrets/backends/linux_secret_service.py` — `LinuxSecretServiceBackend.get`, `LinuxSecretServiceBackend.set`, `LinuxSecretServiceBackend.delete`
- `src/sevn/security/secrets/backends/macos_keychain.py` — `MacOSKeychainBackend.get`, `MacOSKeychainBackend.set`, `MacOSKeychainBackend.delete`

## Level 3 — Deep dive (low-level, technical)

Primary source tree: `src/sevn/` (17 Python files). Normative design: `about-sevn.bot/specs/06-secrets.md`.

### Module inventory

- `src/sevn/secrets/__init__.py` — Operator-facing secrets helpers outside ''sevn.security'' ('about-sevn.bot/specs/06-secrets.md').
- `src/sevn/secrets/fingerprint.py` — Stable fingerprints for operator CLI confirmation ('about-sevn.bot/specs/06-secrets.md' §2.6).
- `src/sevn/secrets/migrate.py` — Legacy plaintext ''.sevn/secrets'' promotion ('about-sevn.bot/specs/06-secrets.md' §10.2).
- `src/sevn/security/secrets/__init__.py` — Secrets abstraction for the trust boundary (''about-sevn.bot/specs/06-secrets.md'').
- `src/sevn/security/secrets/backends/__init__.py` — Concrete secret backends (''about-sevn.bot/specs/06-secrets.md'' §4.1).
- `src/sevn/security/secrets/backends/encrypted_file.py` — Encrypted JSON map on disk with AEAD (''about-sevn.bot/specs/06-secrets.md'' §3.1).
- `src/sevn/security/secrets/backends/linux_secret_service.py` — Linux secret service via optional ''secretstorage'' (''about-sevn.bot/specs/06-secrets.md'' §3.2).
- `src/sevn/security/secrets/backends/macos_keychain.py` — macOS Keychain via ''security'' CLI (''about-sevn.bot/specs/06-secrets.md'' §3.2).
- `src/sevn/security/secrets/backends/openbao.py` — OpenBao / Vault OSS KV v2 read path (''about-sevn.bot/specs/06-secrets.md'' §3.2).
- `src/sevn/security/secrets/backends/proton_pass.py` — Proton Pass CLI bridge (''about-sevn.bot/specs/06-secrets.md'' §3.2).
- `src/sevn/security/secrets/cache.py` — TTL cache for resolved secret strings (''about-sevn.bot/specs/06-secrets.md'' §2.2).
- `src/sevn/security/secrets/chain.py` — Ordered backend chain with read/write policy (''about-sevn.bot/specs/06-secrets.md'' §2.2, §5).
- … and 5 more Python modules

### Package init (`src/sevn/secrets/__init__.py`)

See `src/sevn/secrets/__init__.py` for implementation details.

### Fingerprint (`src/sevn/secrets/fingerprint.py`)

Public entry points:
- `fingerprint_sha256_hex`

### Migrate (`src/sevn/secrets/migrate.py`)

Public entry points:
- `secrets_dir_under_content_root`
- `legacy_plaintext_entries`
- `remove_legacy_plaintext_artifacts`
- `encrypted_file_backend_for_workspace`
- `promote_legacy_plaintext_to_encrypted_store`
- `promote_legacy_plaintext_to_encrypted_store_sync`
- `store_enc_reserved_path`
- `non_legacy_files_present`

### Package init (`src/sevn/security/secrets/__init__.py`)

See `src/sevn/security/secrets/__init__.py` for implementation details.

### Package init (`src/sevn/security/secrets/backends/__init__.py`)

See `src/sevn/security/secrets/backends/__init__.py` for implementation details.

### Encrypted File (`src/sevn/security/secrets/backends/encrypted_file.py`)

Public entry points:
- `default_encrypted_store_path`
- `EncryptedFileBackend.get`
- `EncryptedFileBackend.load_decrypted_map`
- `EncryptedFileBackend.set`
- `EncryptedFileBackend (+1 methods)`

### Linux Secret Service (`src/sevn/security/secrets/backends/linux_secret_service.py`)

Public entry points:
- `LinuxSecretServiceBackend.get`
- `LinuxSecretServiceBackend.set`
- `LinuxSecretServiceBackend.delete`

### Macos Keychain (`src/sevn/security/secrets/backends/macos_keychain.py`)

Public entry points:
- `MacOSKeychainBackend.get`
- `MacOSKeychainBackend.set`
- `MacOSKeychainBackend.delete`

### Openbao (`src/sevn/security/secrets/backends/openbao.py`)

Public entry points:
- `OpenBaoBackend.get`
- `OpenBaoBackend.set`
- `OpenBaoBackend.delete`

### Proton Pass (`src/sevn/security/secrets/backends/proton_pass.py`)

Public entry points:
- `ProtonPassCliBackend.get`
- `ProtonPassCliBackend.set`
- `ProtonPassCliBackend.delete`

### Cache (`src/sevn/security/secrets/cache.py`)

See `src/sevn/security/secrets/cache.py` for implementation details.

### Chain (`src/sevn/security/secrets/chain.py`)

See `src/sevn/security/secrets/chain.py` for implementation details.

### Additional modules

5 more Python files under `src/sevn/` — including `src/sevn/security/secrets/errors.py`, `src/sevn/security/secrets/factory.py`, `src/sevn/security/secrets/passphrase_prime.py`, `src/sevn/security/secrets/protocol.py`.

### Extension and invariants

Follow `about-sevn.bot/specs/06-secrets.md` for merge gates, error semantics, and compatibility constraints. After code changes under `src/sevn/`, run `sevn readme update secrets` and `make readme-check`.

## References

- [../../about-sevn.bot/specs/06-secrets.md](../../about-sevn.bot/specs/06-secrets.md)

[spec-badge]: https://img.shields.io/badge/Spec-2a7fc6?style=for-the-badge&logo=readthedocs&logoColor=white
[spec-link]: ../../about-sevn.bot/specs/06-secrets.md
[source-badge]: https://img.shields.io/badge/Source-0c0a09?style=for-the-badge&logo=github&logoColor=white
[source-link]: ../../src/sevn/
[index-badge]: https://img.shields.io/badge/All_READMEs-5fb1f7?style=for-the-badge&logo=markdown&logoColor=white
[index-link]: INDEX.md
