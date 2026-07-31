---
id: spec-06-secrets
kind: spec
title: Secrets — Spec
status: scaffold
owner: Alex
summary: 'Deliver a single trust boundary for credentials: backend modules + TTL cache
  under src/sevn/security/, wired exclusively by the egress proxy (src/sevn/proxy/)
  so agent-facing processes never see raw k'
last_updated: '2026-07-31'
fingerprint: sha256:29303c6328dfd6bef0b4d95e74795e8e5fd25aa16ef4e65640b279534cefa9c5
related: []
sources:
- src/sevn/security/secrets/**
parent_prd: prd-03-trust-and-control
depends_on:
- spec-00-foundation
- spec-02-config-and-workspace
build_phase: null
interfaces:
- name: EncryptedFileBackend
  file: src/sevn/security/secrets/backends/encrypted_file.py
  symbol: EncryptedFileBackend
- name: default_encrypted_store_path
  file: src/sevn/security/secrets/backends/encrypted_file.py
  symbol: default_encrypted_store_path
- name: LinuxSecretServiceBackend
  file: src/sevn/security/secrets/backends/linux_secret_service.py
  symbol: LinuxSecretServiceBackend
- name: MacOSKeychainBackend
  file: src/sevn/security/secrets/backends/macos_keychain.py
  symbol: MacOSKeychainBackend
- name: OpenBaoBackend
  file: src/sevn/security/secrets/backends/openbao.py
  symbol: OpenBaoBackend
- name: ProtonPassCliBackend
  file: src/sevn/security/secrets/backends/proton_pass.py
  symbol: ProtonPassCliBackend
- name: ResolvedSecretsCache
  file: src/sevn/security/secrets/cache.py
  symbol: ResolvedSecretsCache
- name: SecretsChain
  file: src/sevn/security/secrets/chain.py
  symbol: SecretsChain
- name: SecretsChainWriteError
  file: src/sevn/security/secrets/chain.py
  symbol: SecretsChainWriteError
- name: get_secret_resilient
  file: src/sevn/security/secrets/chain.py
  symbol: get_secret_resilient
- name: SecretUnresolvedError
  file: src/sevn/security/secrets/errors.py
  symbol: SecretUnresolvedError
- name: SecretsBackendError
  file: src/sevn/security/secrets/errors.py
  symbol: SecretsBackendError
- name: SecretsError
  file: src/sevn/security/secrets/errors.py
  symbol: SecretsError
- name: SecretsStoreCorruptError
  file: src/sevn/security/secrets/errors.py
  symbol: SecretsStoreCorruptError
- name: is_encrypted_store_decrypt_failure
  file: src/sevn/security/secrets/errors.py
  symbol: is_encrypted_store_decrypt_failure
- name: is_encrypted_store_unlock_error
  file: src/sevn/security/secrets/errors.py
  symbol: is_encrypted_store_unlock_error
- name: default_chain_entries
  file: src/sevn/security/secrets/factory.py
  symbol: default_chain_entries
- name: parse_optional_master_key_hex
  file: src/sevn/security/secrets/factory.py
  symbol: parse_optional_master_key_hex
- name: resolve_backend
  file: src/sevn/security/secrets/factory.py
  symbol: resolve_backend
- name: resolve_primary_encrypted_store_path
  file: src/sevn/security/secrets/factory.py
  symbol: resolve_primary_encrypted_store_path
- name: secrets_chain_from_workspace
  file: src/sevn/security/secrets/factory.py
  symbol: secrets_chain_from_workspace
- name: fetch_unlock_secret_from_keychain
  file: src/sevn/security/secrets/passphrase_prime.py
  symbol: fetch_unlock_secret_from_keychain
- name: keychain_has_unlock_secret
  file: src/sevn/security/secrets/passphrase_prime.py
  symbol: keychain_has_unlock_secret
- name: log_unlock_env_conflict
  file: src/sevn/security/secrets/passphrase_prime.py
  symbol: log_unlock_env_conflict
- name: prime_unlock_env_from_keychain
  file: src/sevn/security/secrets/passphrase_prime.py
  symbol: prime_unlock_env_from_keychain
- name: reconcile_unlock_env_with_keychain
  file: src/sevn/security/secrets/passphrase_prime.py
  symbol: reconcile_unlock_env_with_keychain
- name: unlock_env_var_for
  file: src/sevn/security/secrets/passphrase_prime.py
  symbol: unlock_env_var_for
- name: SecretsBackend
  file: src/sevn/security/secrets/protocol.py
  symbol: SecretsBackend
- name: EnvUnresolvedError
  file: src/sevn/security/secrets/value_expand.py
  symbol: EnvUnresolvedError
- name: expand_env_refs
  file: src/sevn/security/secrets/value_expand.py
  symbol: expand_env_refs
- name: expand_refs_env_then_secret
  file: src/sevn/security/secrets/value_expand.py
  symbol: expand_refs_env_then_secret
- name: expand_secret_refs
  file: src/sevn/security/secrets/value_expand.py
  symbol: expand_secret_refs
---

## Purpose

Deliver a single trust boundary for credentials: backend modules + TTL cache under
`src/sevn/security/secrets/`, wired exclusively by the egress proxy (`src/sevn/proxy/`) so
agent-facing processes never see raw key material.

**Environment baseline (W0.6 / #82, verified W25):** process environment is the first-class
secret source via `${ENV:VAR}` expansion in `expand_env_refs` (`value_expand.py`). Only the
real process environ is consulted — `ProcessSettings` deliberately sets `env_file=None` and
never loads per-directory `.env` files (`settings.py`), matching the issue goal of avoiding
implicit `.env` injection.

Primary code trees: [`src/sevn/security/secrets`](src/sevn/security/secrets/__init__.py),
legacy migration helpers under [`src/sevn/secrets`](src/sevn/secrets/__init__.py).
## Public Interface

Initial draft for **Public Interface** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Public Interface — acceptance criteria and edge cases. -->

- [`fingerprint_sha256_hex`](src/sevn/secrets/fingerprint.py) — `src/sevn/secrets/fingerprint.py`
- [`PromotionResult`](src/sevn/secrets/migrate.py) — `src/sevn/secrets/migrate.py`
- [`encrypted_file_backend_for_workspace`](src/sevn/secrets/migrate.py) — `src/sevn/secrets/migrate.py`
- [`legacy_plaintext_entries`](src/sevn/secrets/migrate.py) — `src/sevn/secrets/migrate.py`
- [`non_legacy_files_present`](src/sevn/secrets/migrate.py) — `src/sevn/secrets/migrate.py`
- [`promote_legacy_plaintext_to_encrypted_store`](src/sevn/secrets/migrate.py) — `src/sevn/secrets/migrate.py`
- [`promote_legacy_plaintext_to_encrypted_store_sync`](src/sevn/secrets/migrate.py) — `src/sevn/secrets/migrate.py`
- [`remove_legacy_plaintext_artifacts`](src/sevn/secrets/migrate.py) — `src/sevn/secrets/migrate.py`
- [`secrets_dir_under_content_root`](src/sevn/secrets/migrate.py) — `src/sevn/secrets/migrate.py`
- [`store_enc_reserved_path`](src/sevn/secrets/migrate.py) — `src/sevn/secrets/migrate.py`
## Data Model

Initial draft for **Data Model** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Data Model — acceptance criteria and edge cases. -->

- [`fingerprint_sha256_hex`](src/sevn/secrets/fingerprint.py) — `src/sevn/secrets/fingerprint.py`
- [`PromotionResult`](src/sevn/secrets/migrate.py) — `src/sevn/secrets/migrate.py`
- [`encrypted_file_backend_for_workspace`](src/sevn/secrets/migrate.py) — `src/sevn/secrets/migrate.py`
- [`legacy_plaintext_entries`](src/sevn/secrets/migrate.py) — `src/sevn/secrets/migrate.py`
- [`non_legacy_files_present`](src/sevn/secrets/migrate.py) — `src/sevn/secrets/migrate.py`
- [`promote_legacy_plaintext_to_encrypted_store`](src/sevn/secrets/migrate.py) — `src/sevn/secrets/migrate.py`
- [`promote_legacy_plaintext_to_encrypted_store_sync`](src/sevn/secrets/migrate.py) — `src/sevn/secrets/migrate.py`
- [`remove_legacy_plaintext_artifacts`](src/sevn/secrets/migrate.py) — `src/sevn/secrets/migrate.py`
- [`secrets_dir_under_content_root`](src/sevn/secrets/migrate.py) — `src/sevn/secrets/migrate.py`
- [`store_enc_reserved_path`](src/sevn/secrets/migrate.py) — `src/sevn/secrets/migrate.py`
## Internal Architecture

See **Implemented by** and [`src/sevn/secrets`](src/sevn/secrets/__init__.py).
## Behavior

### Resolution precedence (deterministic)

When resolving a logical secret id, order is fixed:

1. **Process environment** — for resilient reads (`get_secret_resilient`), a non-empty
   `os.environ[logical_key]` wins before any configured backend. For config expansion,
   `${ENV:VAR}` segments substitute from process env only (`expand_env_refs`).
2. **`${SECRET:source:logical_key}`** — the `source` segment names a backend label in
   `secrets_backend.chain`; the proxy cache key is `(source, logical_key)`. When the source
   backend misses, expansion fails (`SecretUnresolvedError`) rather than falling through to
   another backend label.
3. **Chain order** — `SecretsChain.get` walks `secrets_backend.chain` top-to-bottom; the
   first backend returning a non-`None` value wins. Earlier entries shadow later ones.
4. **Default chain** — when `chain` is omitted: macOS → `[macos_keychain, encrypted_file]`;
   Linux → `[linux_secret_service, encrypted_file]`; CI (`CI=1`) → `[encrypted_file]` only.

### Provenance (no value leakage)

`resolve_secret_provenance(chain, logical_key)` returns a `SecretProvenanceReport` with
`source` (backend label) and `logical_key` only — `value` is always `None`. `ResolvedSecretsCache`
stores plaintext under TTL but records provenance separately; `provenance_for_cache_entry` and
`str(report)` never include decrypted material.

### Pluggable backends

| `chain[].type` | Implementation | Notes |
|----------------|----------------|-------|
| `encrypted_file` | `EncryptedFileBackend` | Default fallback; PBKDF2 or master-key unlock |
| `macos_keychain` | `MacOSKeychainBackend` | macOS only |
| `linux_secret_service` | `LinuxSecretServiceBackend` | libsecret / GNOME Keyring |
| `openbao` | `OpenBaoBackend` | OSS KV v2; Vault Enterprise not supported |
| `proton_pass` | `ProtonPassCliBackend` | Proton Pass CLI dialects |
| `one_password` | `OnePasswordCliBackend` | 1Password CLI (`op`); requires signed-in account or `OP_SERVICE_ACCOUNT_TOKEN` |
| `bitwarden` | `BitwardenCliBackend` | Bitwarden CLI (`bw`); requires `BW_SESSION` |

1Password and Bitwarden backends are CLI bridges validated by unit tests with fakes; live vault
resolution requires operator-installed CLIs and credentials (not exercised in CI).

Trace control flow from `secrets_chain_from_workspace` → `ResolvedSecretsCache.get_resolved` →
`expand_refs_env_then_secret` in the proxy credential path.
## Failure Modes

Initial draft for **Failure Modes** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Failure Modes — acceptance criteria and edge cases. -->

Document observable failure surfaces from the implementing modules (exceptions, logged errors, degraded modes) — cite code paths.

**Proton Pass CLI dialect:** `ProtonPassCliBackend` routes get/set/delete through `pass secrets …` via `run_proton_cli`. Share-key and item decrypt failures in `PassService` (`_decrypt_share_keys`, `_fetch_items`) must log at **warning** with share/item ids and reason — partial lists may continue, but must not be indistinguishable silent empties (see `tests/proton_cli/test_pr_verifier_w1_red.py`). Address-key unlock failures in `account/keys.py` (`_unlock_keys`) must likewise log at **warning** (partial unlock may continue; `unlock()` still raises when no address keys unlock). Pass `items create` / `items edit` / `pass secrets set` resolve secrets via `_resolve_secret_value` (explicit value, non-TTY stdin when `-`/omitted, else hidden prompt).

## Test Strategy

Initial draft for **Test Strategy** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Test Strategy — acceptance criteria and edge cases. -->

Map to existing tests under `tests/` that cover this subsystem; add Makefile-only gates where applicable.

Pass foundation reads + write paths: mocked `PassService` / Typer paths in `tests/proton_cli/test_pr_verifier_w1_red.py` (items/vault create, `pass secrets get`, unlock + item-decrypt surfacing, stdin `_resolve_secret_value`, SRP HV retry + `PROTON_HV_TOKEN`); skill bridge argv / async runner in `tests/skills/test_proton_management_skill*.py`; backend seam in `tests/security/secrets/test_proton_pass_backend.py`.

## Amendments (telegram-menu-redesign W9)

Telegram `/config` Access section lists, removes, and unlocks secrets from the menu;
``export-secrets`` bundle export uses a two-step confirm gate before writing the archive.
Host-only secret flows post copy-paste CLI cards when the gateway cannot execute them (D17).

## Human-input needed

Prose body not yet authored (W9 scope). Normative contract requires operator or
follow-up wave authoring against verified code (`sevn about-docs extract` + graphify).
Do not mark `status: done` until `make -C spec-kit-wave spec-check` scores ≥ 80.
