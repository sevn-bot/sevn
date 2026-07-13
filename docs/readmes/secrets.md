<!-- generated: do not edit by hand; run `sevn readme update secrets` -->
# Secrets — Secrets backends, logical keys, fingerprint confirmation — keys never in the gateway process

[![Spec][spec-badge]][spec-link]
[![Source][source-badge]][source-link]
[![Index][index-badge]][index-link]

> **Summary.** Secrets backends, logical keys, fingerprint confirmation — keys never in the gateway process.

## Level 1 — Overview (non-technical)

**Secrets** is a core part of sevn.bot — the personal AI assistant you run on your own machine. Secrets backends, logical keys, fingerprint confirmation — keys never in the gateway process.

In everyday use, secrets helps Sevn do its job reliably: you interact through familiar channels (Telegram, browser, voice), and this layer keeps those interactions safe, consistent, and under your control.

Deliver a single trust boundary for credentials: backend modules + TTL cache under src/sevn/security/, wired exclusively by the egress proxy (src/sevn/proxy/) so agent-facing processes never see raw k

## Level 2 — How it works (technical)

### Components and layout

Implementation lives under `src/sevn/secrets/`. The package contains 17 Python module(s); primary entry points include `src/sevn/secrets/__init__.py`, `src/sevn/secrets/fingerprint.py`, `src/sevn/secrets/migrate.py`, `src/sevn/security/secrets/__init__.py`, and 2 more.

### Data and control flow

Secrets sits in the sevn.bot turn spine: a channel delivers a message, the gateway normalises it, triage routes work to the right executor, and the reply returns through the same channel adapter. This subsystem owns the responsibilities described in the manifest summary and defers provider API calls to the paired egress proxy (keys never load in the gateway process).

### Configuration

Operator settings come from `sevn.json` in the workspace. Related normative specs: `about-sevn.bot/specs/06-secrets.md`. Run `sevn config validate` after edits; use `sevn doctor` to confirm the install sees the expected layout.

### Key modules

- `src/sevn/secrets/fingerprint.py` — `fingerprint_sha256_hex`
- `src/sevn/secrets/migrate.py` — `secrets_dir_under_content_root`, `legacy_plaintext_entries`, `remove_legacy_plaintext_artifacts`, `encrypted_file_backend_for_workspace`
- `src/sevn/security/secrets/backends/encrypted_file.py` — `default_encrypted_store_path`, `EncryptedFileBackend.get`, `EncryptedFileBackend.load_decrypted_map`, `EncryptedFileBackend.set`
- `src/sevn/security/secrets/backends/linux_secret_service.py` — `LinuxSecretServiceBackend.get`, `LinuxSecretServiceBackend.set`, `LinuxSecretServiceBackend.delete`
- `src/sevn/security/secrets/backends/macos_keychain.py` — `MacOSKeychainBackend.get`, `MacOSKeychainBackend.set`, `MacOSKeychainBackend.delete`

### Spec context

From about-sevn.bot/specs/06-secrets.md:
Deliver a single trust boundary for credentials: backend modules + TTL cache under src/sevn/security/, wired exclusively by the egress proxy (src/sevn/proxy/) so agent-facing processes never see raw k

## Level 3 — Deep dive (low-level, technical)

Primary source tree: `src/sevn/secrets/` (17 Python files). Normative design: `about-sevn.bot/specs/06-secrets.md`.

### Module inventory

- `src/sevn/secrets/__init__.py` — """Operator-facing secrets helpers outside ''sevn.security'' ('about-sevn.bot/specs/06-secrets.md').
- `src/sevn/secrets/fingerprint.py` — """Stable fingerprints for operator CLI confirmation ('about-sevn.bot/specs/06-secrets.md' §2.6).
- `src/sevn/secrets/migrate.py` — """Legacy plaintext ''.sevn/secrets'' promotion ('about-sevn.bot/specs/06-secrets.md' §10.2).
- `src/sevn/security/secrets/__init__.py` — """Secrets abstraction for the trust boundary (''about-sevn.bot/specs/06-secrets.md'').
- `src/sevn/security/secrets/backends/__init__.py` — """Concrete secret backends (''about-sevn.bot/specs/06-secrets.md'' §4.1).
- `src/sevn/security/secrets/backends/encrypted_file.py` — """Encrypted JSON map on disk with AEAD (''about-sevn.bot/specs/06-secrets.md'' §3.1).
- `src/sevn/security/secrets/backends/linux_secret_service.py` — """Linux secret service via optional ''secretstorage'' (''about-sevn.bot/specs/06-secrets.md'' §3.2).
- `src/sevn/security/secrets/backends/macos_keychain.py` — """macOS Keychain via ''security'' CLI (''about-sevn.bot/specs/06-secrets.md'' §3.2).
- `src/sevn/security/secrets/backends/openbao.py` — """OpenBao / Vault OSS KV v2 read path (''about-sevn.bot/specs/06-secrets.md'' §3.2).
- `src/sevn/security/secrets/backends/proton_pass.py` — """Proton Pass CLI bridge (''about-sevn.bot/specs/06-secrets.md'' §3.2).
- `src/sevn/security/secrets/cache.py` — """TTL cache for resolved secret strings (''about-sevn.bot/specs/06-secrets.md'' §2.2).
- `src/sevn/security/secrets/chain.py` — """Ordered backend chain with read/write policy (''about-sevn.bot/specs/06-secrets.md'' §2.2, §5).
- … and 5 more Python modules

### Fingerprint (`src/sevn/secrets/fingerprint.py`)

Public entry points:
- `fingerprint_sha256_hex` — see `src/sevn/secrets/fingerprint.py`

### Migrate (`src/sevn/secrets/migrate.py`)

Public entry points:
- `secrets_dir_under_content_root` — see `src/sevn/secrets/migrate.py`
- `legacy_plaintext_entries` — see `src/sevn/secrets/migrate.py`
- `remove_legacy_plaintext_artifacts` — see `src/sevn/secrets/migrate.py`
- `encrypted_file_backend_for_workspace` — see `src/sevn/secrets/migrate.py`
- `promote_legacy_plaintext_to_encrypted_store` — see `src/sevn/secrets/migrate.py`
- `promote_legacy_plaintext_to_encrypted_store_sync` — see `src/sevn/secrets/migrate.py`
- `store_enc_reserved_path` — see `src/sevn/secrets/migrate.py`
- `non_legacy_files_present` — see `src/sevn/secrets/migrate.py`

### Encrypted File (`src/sevn/security/secrets/backends/encrypted_file.py`)

Public entry points:
- `default_encrypted_store_path` — see `src/sevn/security/secrets/backends/encrypted_file.py`
- `EncryptedFileBackend.get` — see `src/sevn/security/secrets/backends/encrypted_file.py`
- `EncryptedFileBackend.load_decrypted_map` — see `src/sevn/security/secrets/backends/encrypted_file.py`
- `EncryptedFileBackend.set` — see `src/sevn/security/secrets/backends/encrypted_file.py`
- `EncryptedFileBackend (+1 methods)` — see `src/sevn/security/secrets/backends/encrypted_file.py`

### Linux Secret Service (`src/sevn/security/secrets/backends/linux_secret_service.py`)

Public entry points:
- `LinuxSecretServiceBackend.get` — see `src/sevn/security/secrets/backends/linux_secret_service.py`
- `LinuxSecretServiceBackend.set` — see `src/sevn/security/secrets/backends/linux_secret_service.py`
- `LinuxSecretServiceBackend.delete` — see `src/sevn/security/secrets/backends/linux_secret_service.py`

### Macos Keychain (`src/sevn/security/secrets/backends/macos_keychain.py`)

Public entry points:
- `MacOSKeychainBackend.get` — see `src/sevn/security/secrets/backends/macos_keychain.py`
- `MacOSKeychainBackend.set` — see `src/sevn/security/secrets/backends/macos_keychain.py`
- `MacOSKeychainBackend.delete` — see `src/sevn/security/secrets/backends/macos_keychain.py`

### Openbao (`src/sevn/security/secrets/backends/openbao.py`)

Public entry points:
- `OpenBaoBackend.get` — see `src/sevn/security/secrets/backends/openbao.py`
- `OpenBaoBackend.set` — see `src/sevn/security/secrets/backends/openbao.py`
- `OpenBaoBackend.delete` — see `src/sevn/security/secrets/backends/openbao.py`

### Proton Pass (`src/sevn/security/secrets/backends/proton_pass.py`)

Public entry points:
- `ProtonPassCliBackend.get` — see `src/sevn/security/secrets/backends/proton_pass.py`
- `ProtonPassCliBackend.set` — see `src/sevn/security/secrets/backends/proton_pass.py`
- `ProtonPassCliBackend.delete` — see `src/sevn/security/secrets/backends/proton_pass.py`

### Additional modules

5 more Python files under `src/sevn/secrets/` — including `src/sevn/security/secrets/errors.py`, `src/sevn/security/secrets/factory.py`, `src/sevn/security/secrets/passphrase_prime.py`, `src/sevn/security/secrets/protocol.py`.

### Extension and invariants

Follow `about-sevn.bot/specs/06-secrets.md` for merge gates, error semantics, and compatibility constraints. After code changes under `src/sevn/secrets/`, run `sevn readme update secrets` and `make readme-check`.

## References

- [../../about-sevn.bot/specs/06-secrets.md](../../about-sevn.bot/specs/06-secrets.md)

[spec-badge]: https://img.shields.io/badge/Spec-2a7fc6?style=for-the-badge&logo=readthedocs&logoColor=white
[spec-link]: ../../about-sevn.bot/specs/06-secrets.md
[source-badge]: https://img.shields.io/badge/Source-0c0a09?style=for-the-badge&logo=github&logoColor=white
[source-link]: ../../src/sevn/secrets/
[index-badge]: https://img.shields.io/badge/All_READMEs-5fb1f7?style=for-the-badge&logo=markdown&logoColor=white
[index-link]: INDEX.md
