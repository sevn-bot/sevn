# Production-readiness 0.0.1 remediation — 42 open change IDs — wave plan

**Status:** A-Reverify done 2026-08-05 (`b8c21cb1`); Batch A ready for A-PR
**Date:** 2026-08-05
**Owner agents:** `wave-plan-executor` (W0, implementation waves, batch Finals) · `test-creator` (per-batch RED waves + xfail reconciliation, **sole owner of `tests/`**) · `wave-verifier` (per-batch Verify gate, **and a fresh instance for the post-Thermos Re-verify gate — never the agent that ran Thermos**, D30) · fresh review agent (per-batch Thermos) · `ci-investigator` (CI failures only, no `tests/` edits)
**Trigger:** [`.ignorelocal/PROD-READINESS-0.0.1-CHANGES.md`](../PROD-READINESS-0.0.1-CHANGES.md) — validation of a 14-finding external production-readiness audit, which enumerates **49 required changes** `C1.1`–`C14.3`. Operator directive: *fix all of them*, batched by subsystem, nothing deferred.
**Base branch:** **`origin/pre-0.0.1`** @ **`2c1c6831`** — every batch PR targets `pre-0.0.1`.
**Predecessor program:** [post-audit-0.0.1-wave-plan.md](./post-audit-0.0.1-wave-plan.md) (COMPLETE 2026-08-05, PRs [#180](https://github.com/sevn-bot/sevn/pull/180) [#189](https://github.com/sevn-bot/sevn/pull/189) [#210](https://github.com/sevn-bot/sevn/pull/210) [#214](https://github.com/sevn-bot/sevn/pull/214) [#215](https://github.com/sevn-bot/sevn/pull/215)) — this plan reuses its conventions, gate style, and the D29/D30/D31 discipline **unaltered**.
**Code anchors verified:** 2026-08-05 against **`origin/pre-0.0.1`** @ `2c1c6831` — every `file:line` below was read from that ref, **not** copied from the source document.

---

> ## ⚠️ Read this before scoping any wave: the source document is stale by four batches
>
> `PROD-READINESS-0.0.1-CHANGES.md` was validated against **`cbca2d47`**. That commit contains post-audit **Batch A only** (`458453fd`). Batches **B, C, D and E** merged *after* it:
>
> ```bash
> git merge-base --is-ancestor 458453fd cbca2d47   # → in     (Batch A)
> git merge-base --is-ancestor a5631b06 cbca2d47   # → NOT in (Batch B)
> git merge-base --is-ancestor 02586eb3 cbca2d47   # → NOT in (Batch C)
> git merge-base --is-ancestor a442109e cbca2d47   # → NOT in (Batch D)
> git merge-base --is-ancestor 0a523c8c cbca2d47   # → NOT in (Batch E)
> ```
>
> **Seven of the 49 change IDs are already landed on the base branch** and must not be re-implemented (table below). Three more are **partially** landed and their waves are scoped to the *remainder* only. Implementing this plan literally from the source document would revert `#167`, `#169` and `#173`.

---

## Already landed — do **not** re-implement (verified @ `2c1c6831`)

| ID | Source claim | Landed by | Live anchor |
|----|--------------|-----------|-------------|
| **C1.1** | Empty secret must be fatal on guarded routes, behind a loud dev override | #167 / post-audit W5 | `src/sevn/proxy/auth.py:262-270` returns **503** `PROXY_UNCONFIGURED_DETAIL`; `SEVN_PROXY_ALLOW_UNAUTHENTICATED` at `:45-60`, boot warning at `:76` |
| **C2.3** | Block non-draft `v*` releases on phase 4/5 | #172 / post-audit W10 | `.github/workflows/ci-cd.yml:339` `needs: [phase1, publish-ghcr, container-supply-chain, phase4, phase5]`; `:360` `draft: true`; `:414` `require_needs_impl` reachable **only** under `EVENT_NAME = workflow_dispatch` |
| **C6.1** | Require the boot local token when local-open is effective | #169 / post-audit W18 | `src/sevn/ui/dashboard/services/auth.py` — the `return submitted is None` tail is gone |
| **C6.3** | Invert the tests that pin the permissive branch | #169 / post-audit W17.4 | `tests/ui/dashboard/test_local_open_auth.py` rewritten; `tests/ui/dashboard/test_post_audit_local_token_w17_red.py` added |
| **C12.1** | Remove `--exit-code 0` | #173 / post-audit W11.3 | `.github/workflows/ci-cd.yml:230` `trivy image --exit-code 1 --severity CRITICAL,HIGH --ignore-unfixed --ignorefile …` |
| **C12.2** | Reorder to scan → sign | #173 / post-audit W11.3 | `trivy` at `:230` precedes `cosign sign` at `:235` |
| **C12.4** | Upload SBOMs as artifacts / release assets | #173 / post-audit W11.4 | `actions/upload-artifact` + phase6 `files: sboms/**` |

**Partially landed — waves are scoped to the remainder only:**

| ID | Landed part | Remaining part (this program) |
|----|-------------|-------------------------------|
| **C1.5** | `proxy_shared_secret` **does** resolve from the secrets chain — but only inside the **proxy process** (`src/sevn/proxy/credentials.py:801-806`, `_resolve_proxy_shared_secret` at `:810`) | The **gateway** side is still env-only (`src/sevn/agent/adapters/egress_bridge.py:55`), and the resolver **writes back to `os.environ`** at `credentials.py:805-806` — see finding 3 |
| **C6.2** | `dashboard.local_open_trust_address` exists, defaults `false` (`src/sevn/config/sections/dashboard.py:36`, honoured at `src/sevn/ui/dashboard/services/auth.py:289`, schema `infra/sevn.schema.json:679`) | It is **not** refused when a tunnel or reverse proxy is configured, logs **no** boot warning, and its name does not read as dangerous |
| **C7.1** | `mint_session_token` / `validate_session_token` with **signature, `exp` and route-family scope** (`src/sevn/proxy/auth.py:133`, `:171`, guard branch `:274-280`) | **`run_id` is already embedded** in the mint payload (`auth.py:137`, `:164`) but **`validate_session_token` never reads it** and there is **no binding to the spawning container** — W19 enforces/binds, it does not introduce the claim (corrected W0.2 @ `2c1c6831`) |

---

> **Six investigation findings that change the work before it starts.**
>
> 1. **The stock stack is now broken the way the original audit claimed — just for the opposite reason.** `C1.1` made guarded routes fail closed, but nothing generates a secret. `.env.example:65` ships `SEVN_PROXY_SHARED_SECRET=` **blank**, and Compose passes `${SEVN_PROXY_SHARED_SECRET:-}` to both services (`docker/docker-compose.yml:76`, `:108`, plus `docker-compose.browser.yml:18` and `docker-compose.gui.yml:18`). So a stock `docker compose up` now returns **503 on `/llm/*`, `/web/*`, `/integration/*`** — LLM, web and integration operations fail out of the box. The audit's finding #1 was refuted at `cbca2d47`; it is **true at `2c1c6831`**. This makes **C1.2 the single highest-priority item in the program**, and it must land with `C1.3` or the failure stays silent until first use.
> 2. **`.env.example` already contains the exact placeholder pattern `C1.3` must blacklist.** `SEVN_GATEWAY_TOKEN=change-me` (`:60`) and `SEVN_SECRETS_PASSPHRASE=change-me` (`:67`). The preflight is not hypothetical hardening — it catches two shipped defaults today.
> 3. **The secrets-chain resolver defeats `C3.2` by mutating global state.** `src/sevn/proxy/credentials.py:805-806` does `os.environ["SEVN_PROXY_SHARED_SECRET"] = proxy_secret` when the chain resolves a value. That write-back is what makes the **eleven** `os.environ.get("SEVN_PROXY_SHARED_SECRET")` call sites appear to work. Deleting the fallbacks without deleting the write-back leaves a hidden coupling; deleting the write-back without threading the secret first breaks the proxy. **W3 must do both in one commit.**
> 4. **`C5` is a different bug than the document describes, because `C4`'s sibling already landed.** Post-audit W7 (#170) rewrote `_resolve_digest_pinned_image` into pull-then-pin and **removed the `.Id` fallback** (`src/sevn/security/sandbox_runtime.py:1449-1500`, error at `:1499`). What remains is purely a **cost and availability** defect: the unconditional `docker pull` at `:1484` still runs on **every** spawn (`:1841`), with no cross-spawn cache and no local-image short circuit. Do **not** re-litigate the `.Id` fallback — it is gone.
> 5. **`C10.3` is mostly already satisfied by Compose merge semantics, and the wave must prove that before writing YAML.** The browser and GUI override files redefine the service **`sevn-gateway`** (`docker/docker-compose.browser.yml:9`), so they merge with the base service that carries `*operator-service-hardening` and `*operator-resource-limits-gateway` (`docker/docker-compose.yml:22-42`). The overrides declare no `deploy:` of their own but should inherit limits through the merge. **`docker/docker-compose.ci.yml` genuinely declares none.** W16 starts by capturing `docker compose … config` for all three file sets — it adds YAML only where the *resolved* config is missing limits.
> 6. **`C9` needs a marker, not another `find` rewrite.** Post-audit W3 (#166) already replaced the unconditional `chown -R` with `find /operator ! -user 10001 -exec chown …` (`docker/docker-compose.yml:60-61`). The residue is that it still **walks the whole tree** on every fresh `up`, that no init marker exists, and that `docker/docker-compose.ci.yml:20` still runs the unconditional `chown -R 10001:10001 /operator` the base file abandoned. The existing tests pin the `find` form (`tests/infra/test_post_audit_compose_w1_red.py`), so `C9.3` is a hard prerequisite for `C9.1`, owned by `test-creator`.

---

## Change inventory (42 open across six batches)

**Batch A — Proxy secret authority & default-stack bootstrap**

| ID | Change | Wave |
|---|---|---|
| C3.1 | `SEVN_PROXY_SHARED_SECRET` joins `PROCESS_SETTINGS_ENV_VAR_NAMES` | A / W2 |
| C1.5 | Gateway-side secrets-chain resolution (proxy side already landed) | A / W2 |
| C3.2 | Thread the resolved secret; delete all eleven `os.environ` fallbacks **and** the write-back | A / W3 |
| C3.3 | Guarded-route clients fail loudly on an empty secret instead of sending an empty header | A / W3 |
| C1.2 | Bootstrap a real secret into the shared `sevn-state` volume | A / W4 |
| C1.3 | `make compose-up` preflight: empty / low-entropy / `change-me` placeholder | A / W5 |
| C1.4 | Proxy healthcheck proves authenticated function, not liveness | A / W5 |

**Batch B — Sandbox image integrity & spawn cost**

| ID | Change | Wave |
|---|---|---|
| C4.1 | One build-stamped digest constant replacing three `:dev` literals | B / W7 |
| C4.3 | CI check that no mutable tag literal survives a release build | B / W7 |
| C4.2 | Pre-pull the release digest at deploy; refuse to start when absent | B / W8 |
| C5.1 | Resolve and validate the digest **once** at gateway startup | B / W8 |
| C5.2 | Skip `docker pull` when the digest-pinned image is already local | B / W8 |
| C5.3 | Refresh only via an explicit image-update operation | B / W8 |
| C5.4 | Regression test: N spawns produce exactly one pull | B / W6 (RED) → W8 |

**Batch C — Release pipeline & supply chain**

| ID | Change | Wave |
|---|---|---|
| C2.1 | Rename the aggregator so its name stops implying deployment readiness | C / W10 |
| C2.2 | Implement phases 2/3, or delete them with the `needs_impl_ok` escape hatch | C / W10 |
| C13.1 | Stop writing `latest` from `main`; SHA tags only | C / W11 |
| C13.2 | Document `latest` as unverified; operator default becomes a pinned digest | C / W11 |
| C12.3 | Publish to a quarantine tag, scan, then promote stable tags by digest | C / W11 |
| C11.1 | Replace both `curl \| sh` installers with pinned, verified downloads | C / W12 |
| C11.2 | Pin and checksum-verify the `uv` installer | C / W12 |
| C11.3 | CI gate rejecting new `curl … \| sh` under `.github/` and `Makefile` | C / W12 |

**Batch D — Container isolation & operator runtime**

| ID | Change | Wave |
|---|---|---|
| C8.1 | Remove `--no-sandbox` from the prod overlay; widen the guard test to overlays | D / W14 |
| C8.2 | Delete the stale `--no-sandbox` comments in the two override files | D / W14 |
| C8.4 | Re-justify or drop `--disable-features=IsolateOrigins,site-per-process` | D / W14 |
| C9.3 | Update the tests that pin the full-tree `find` (**prerequisite**, `test-creator`) | D / W13 |
| C9.1 | Chown only known application-owned directories | D / W15 |
| C9.2 | Versioned init marker; broad migration only when absent or stale | D / W15 |
| C9.4 | Same treatment for `sevn-ci-init`, or document why CI diverges | D / W15 |
| C10.1 | Pin and document a minimum Docker Compose version | D / W16 |
| C10.2 | Integration check reading the container's `HostConfig` | D / W16 |
| C10.3 | Declare limits wherever the **resolved** config is missing them | D / W16 |
| C8.3 | Split the browser into its own minimally-privileged service | D / W17 |

**Batch E — Scoped egress authority**

| ID | Change | Wave |
|---|---|---|
| C7.1 | Add `run_id` and spawning-container binding to the session token | E / W19 |
| C7.2 | Reject the service shared secret on sandbox route families | E / W19 |
| C7.3 | Destination allowlist and per-run request/byte budgets, enforced proxy-side | E / W20 |
| C7.4 | Stop describing unimplemented token behaviour as current in the schema | E / W20 |

**Batch F — Dashboard residuals & dynamic evidence**

| ID | Change | Wave |
|---|---|---|
| C6.2 | `local_open_trust_address`: refuse under tunnel/proxy, warn at boot, rename | F / W22 |
| C6.4 | Fix the CLI message that still says "no login required" | F / W22 |
| C14.1 | CI job running `make verify-deployment` on schedule and release tags | F / W23 |
| C14.2 | Drivers for the uncovered paths | F / W23 |
| C14.3 | Attach captured evidence to the release | F / W23 |

**Every open change ID appears in exactly one wave.** None is silently dropped or deferred.

**Priority.** **C1.2 + C1.3** first — the shipped default stack currently 503s on every LLM, web and integration call (finding 1), which is both a functional break on first use *and* the reason the secret's absence is invisible. **C7.2** next: today the service secret satisfies the guard for every route family, so a sandbox presenting it has gateway authority. **C13.1 + C12.3** gate the tag itself. **C9.3 before C9.1** (`test-creator` handoff). **C4.1 before C5.1** — the constant must be single-sourced before it is cached.

---

## Worktrees & branches (mandatory — D1)

The primary checkout **must not be used for any wave** (`.cursor/rules/no-primary-checkout-work.mdc`). One worktree per batch, all based on `origin/pre-0.0.1`:

```bash
git fetch origin
git worktree add ../sevn-pr-a-proxy-secret   wave/prod-ready-a-proxy-secret     origin/pre-0.0.1
git worktree add ../sevn-pr-b-sandbox-image  wave/prod-ready-b-sandbox-image    origin/pre-0.0.1
git worktree add ../sevn-pr-c-supply-chain   wave/prod-ready-c-supply-chain     origin/pre-0.0.1
git worktree add ../sevn-pr-d-isolation      wave/prod-ready-d-isolation        origin/pre-0.0.1
git worktree add ../sevn-pr-e-egress-scope   wave/prod-ready-e-egress-scope     origin/pre-0.0.1
git worktree add ../sevn-pr-f-evidence       wave/prod-ready-f-evidence         origin/pre-0.0.1
```

| Batch | Branch | Worktree | Closes |
|---|---|---|---|
| A — Proxy secret authority | `wave/prod-ready-a-proxy-secret` | `../sevn-pr-a-proxy-secret` | C1.2–C1.5, C3.1–C3.3 |
| B — Sandbox image integrity | `wave/prod-ready-b-sandbox-image` | `../sevn-pr-b-sandbox-image` | C4.1–C4.3, C5.1–C5.4 |
| C — Release & supply chain | `wave/prod-ready-c-supply-chain` | `../sevn-pr-c-supply-chain` | C2.1, C2.2, C11.1–C11.3, C12.3, C13.1, C13.2 |
| D — Isolation & operator runtime | `wave/prod-ready-d-isolation` | `../sevn-pr-d-isolation` | C8.1–C8.4, C9.1–C9.4, C10.1–C10.3 |
| E — Scoped egress authority | `wave/prod-ready-e-egress-scope` | `../sevn-pr-e-egress-scope` | C7.1–C7.4 |
| F — Evidence & dashboard residuals | `wave/prod-ready-f-evidence` | `../sevn-pr-f-evidence` | C6.2, C6.4, C14.1–C14.3 |

- **Assert worktree + branch before the first edit of every wave; stop on mismatch.**
- **Seed gitignored trees** (`.ignorelocal/`, `.claude/`, `.cursor/`) with plain `cp` — **never** `git clean -x`/`-X` (`.cursor/rules/no-destructive-git-clean.mdc`).
- **Partial CI base:** `SEVN_CI_BASE=HEAD` mid-wave; **`SEVN_CI_BASE=origin/pre-0.0.1`** at every batch boundary and in `make ci-resume`.
- All six PRs target **`pre-0.0.1`**.

---

## Specs touched

Prose bodies for 07/08/09/24 are unauthored `<!-- HUMAN-INPUT -->` stubs carrying **Amendments** appended by the predecessor program — this program appends `## Amendments (prod-readiness-0.0.1 Wn — CX.Y)` sections in the same style. Only `25-cicd-full.md` has live prose to edit in place.

| Spec | Waves | Surface | Edit mode |
|---|---|---|---|
| `about-sevn.bot/specs/02-config-and-workspace.md` | W2, W4, W22 | `SEVN_PROXY_SHARED_SECRET` as a `ProcessSettings` variable; bootstrap location; trust-address key | Amendment + `make config-schema` |
| `about-sevn.bot/specs/06-secrets.md` | W2, W4 | Secrets-chain resolution of the proxy shared secret; generated-secret storage | Amendment |
| `about-sevn.bot/specs/07-egress-proxy.md` | W3, W5, W19, W20 | Single configuration authority, authenticated healthcheck, `run_id` binding, budgets | Amendment |
| `about-sevn.bot/specs/08-sandbox.md` | W7, W8, W19 | Digest constant, startup pin + cache, explicit image-update op, run-bound token | Amendment |
| `about-sevn.bot/specs/09-security-scanner.md` | W14, W17 | Browser renderer sandbox vs container hardening; browser service split | Amendment |
| `about-sevn.bot/specs/22-onboarding.md` | W4 | Proxy shared-secret generation and where it is persisted | Amendment |
| `about-sevn.bot/specs/24-dashboard.md` | W22 | `local_open_trust_address` refusal conditions and boot warning | Amendment |
| `about-sevn.bot/specs/19-channel-webui.md` | W22 | Loopback auth surface message accuracy | Amendment |
| `about-sevn.bot/specs/25-cicd-full.md` | W10, W11, W12, W16, W23 | Aggregator naming, tag policy, quarantine promotion, installer verification, compose version floor, deployment-evidence job | **Live prose — edit Workflow matrix / Behavior / Failure Modes directly** |

## PRDs touched

| PRD | Waves | Surface |
|---|---|---|
| `about-sevn.bot/prd/06-setup-and-operations.md` | W4, W5, W10, W11, W12, W15, W16, W23 | Stock stack works out of the box; release/tag expectations; operator upgrade path |
| `about-sevn.bot/prd/03-trust-and-control.md` | W3, W19, W20, W22 | Who may call the proxy and with what authority; dashboard local access |
| `about-sevn.bot/prd/05-cost-and-providers.md` | W3, W19, W20 | Provider spend is bound to an authenticated, budgeted caller |

## Spec ↔ code reconciliation

Verified against `origin/pre-0.0.1` @ `2c1c6831`.

| Spec | Requirement / contract | Live code anchor | Drift? |
|---|---|---|---|
| 02 §2.5 — `ProcessSettings` env allowlist | Env surface is a curated allowlist | `src/sevn/config/settings.py:28-38` — seven names, **no** `SEVN_PROXY_SHARED_SECRET` | **yes** — the secret is outside the audited config contract (W2) |
| 06-secrets — chain resolution | Chain-resolved secrets flow through typed settings | `src/sevn/proxy/credentials.py:801-806` resolves **then writes `os.environ`** | **yes** (global mutation as the transport) — W3 |
| 07 — Amendment (post-audit W5, #167) | Guarded routes fail closed at 503 | `src/sevn/proxy/auth.py:262-270` | no — **must stay green** (D40) |
| 07 — Amendment (post-audit W6, #168) | `X-Sevn-Session-Token` carries expiry + route-family scope | `src/sevn/proxy/auth.py:133`, `:171`, `:274-280` | partial — no `run_id`, no container binding (W19) |
| 07 — service vs session credential | Two credentials with different authority | `auth.py:272-273` — the **service secret alone satisfies every guarded family** | **yes** — sandbox authority ≡ gateway authority (W19) |
| 08 — Amendment (post-audit W7, #170) | Pull-then-pin, fail closed, no `.Id` | `sandbox_runtime.py:1449-1500`; pull `:1484`; inspect `:1493`; raise `:1499` | no — **must stay green**; W8 changes *when* it runs, not *what* it asserts |
| 08 — default image | No normative statement on image mutability | `sandbox_runtime.py:1756`, `:2103`; `src/sevn/agent/runtimes/sandbox.py:308` — three `ghcr.io/sevn-bot/sevn/sandbox:dev` literals | **N/A (spec silent)** — W7 adds the contract |
| 24 — Amendment (post-audit W18, #169) | Local-open requires the boot token | `src/sevn/ui/dashboard/services/auth.py` (token gate); escape at `:289` | partial — escape hatch unguarded (W22) |
| 25 — Workflow matrix | `ci-cd.yml` is artifact publication while phases 2–5 are stubs | `.github/workflows/ci-cd.yml:40` header renamed ✅; job name `:372` still **"Delivery chain gate (required)"** | **yes** — W10 |
| 25 — required aggregator | A required check must not classify `failure` as OK | `:400` `needs_impl_ok`; reachable only when `EVENT_NAME = workflow_dispatch` (`:414`) | partial — tag builds fixed, `main` pushes still tolerate `failure` (W10) |
| 25 §3.2 / §10.3 — CVE allowlist | Scan gates publication | `:230` `--exit-code 1` before `cosign sign` `:235` ✅ — but `push: true` at `:113,127,141,156,171` runs **first** | **yes** (push-before-scan) — W11 |
| 25 — supply-chain tooling | Release tooling is pinned and verified | `:198`, `:202` `curl … \| sh`; `Makefile:48` unpinned `uv` installer | **yes** — W12 |
| 25 — deployment evidence | Verification harness runs somewhere | `scripts/verify_deployment.py:954-958` four drivers; **zero** workflow references | **yes** — W23 |

## Recent baseline / drift

- `origin/pre-0.0.1` @ **`2c1c6831`** — "Merge pull request #194". All five predecessor batch PRs plus #194 are on the base branch; every anchor in this plan was read from that ref.
- The **primary checkout** must be treated as read-only for this program (`.cursor/rules/no-primary-checkout-work.mdc`); pre-commit blocks implementation commits there.
- Existing regression suites that constrain this program — **all must stay green**: `tests/proxy/test_auth.py`, `tests/proxy/test_post_audit_proxy_auth_w4_red.py`, `tests/sandbox/test_post_audit_image_pin_w4_red.py`, `tests/infra/test_post_audit_compose_w1_red.py`, `tests/infra/test_post_audit_release_gate_w9_red.py`, `tests/security/test_post_audit_trivy_allowlist_w9_red.py`, `tests/ui/dashboard/test_post_audit_local_token_w17_red.py`, `tests/infra/test_ci_steps_tier_parity.py`, `tests/infra/test_release_audit_containers_w7_red.py`.
- Open deferrals inherited from the predecessor program: [#185](https://github.com/sevn-bot/sevn/issues/185), [#186](https://github.com/sevn-bot/sevn/issues/186), [#187](https://github.com/sevn-bot/sevn/issues/187), [#212](https://github.com/sevn-bot/sevn/issues/212), [#213](https://github.com/sevn-bot/sevn/issues/213). **W0 checks each against this plan's scope** and records overlaps so a batch does not silently duplicate or contradict a filed deferral.

## Goal

Close **all 42 open change IDs** with:

1. **Every defect proven dead by a regression test** that fails on the batch base and passes after its wave.
2. **A stock `docker compose up` that authenticates and actually serves LLM/web/integration traffic** — no manual secret step, no silent 503 (C1.2, C1.3).
3. **Six independently reviewable PRs** against `pre-0.0.1`, each with `make ci-resume` green and Thermos clean **including `low`** (D31).
4. **Dynamic evidence in CI** so the next audit reads artifacts, not assertions (C14.1–C14.3).
5. **No public `0.0.1` tag** until Z1 closes all 42.

## Global conventions

1. **Worktree only** on the batch branch (**D1**). Never the primary checkout.
2. **Test ownership is exclusive.** Only the **`test-creator`** agent may create or edit anything under `tests/`. `wave-plan-executor` and `ci-investigator` **must not** touch `tests/` — an implementation wave that believes a test is wrong records the finding in the wave notes and hands it to `test-creator` at the batch Verify gate (**D4**).
3. **RED-first per batch.** The first wave of every batch is a `test-creator` RED suite: tests that fail (or `xfail`) on the batch base and are un-xfailed by the wave that fixes them. Naming: `tests/<area>/test_prod_ready_<topic>_w<NN>_red.py`.
4. **Make/uv only** — `make lint`, `make typecheck`, and **`make ci-affected`** mid-wave with `SEVN_CI_BASE=HEAD`. **Never `make ci` mid-wave** (D5). Batch Final uses **`make ci-resume`** with `SEVN_CI_BASE=origin/pre-0.0.1`, looping until it prints all steps passed.
5. **Every wave ends with a conventional commit + push (D2)** — `.claude/skills/conventional-commit`, validated by `make commit-msg-check MSG='…'`. No `--no-verify`.
6. **Drift gates are one commit, not a trickle (D7).** At each batch Final, refresh **every** stale README and about-docs fingerprint in a single commit: `uv run sevn readme fingerprint <slug> --repo .` for each slug reported by `make readme-check`, and `make about-docs-extract DOC_ID=<spec-NN-slug>` for each doc reported by `make about-docs-check`; then run **`make ci-infra ci-docs ci-skills ci-parity`** and confirm clean **before** pushing.
7. **PR bodies list one change ID per line.** This plan is the tracker: each PR body enumerates its `CX.Y` IDs one per line with a one-line outcome each. When a GitHub issue exists for an ID, add `Closes #NN` on **its own line** — never an en-dash or hyphen range (the failure mode that bit PR #160).
8. **Gates per batch, in order:** **Verify** (behavioral proof by `wave-verifier`) → **Final** (xfail sweep, `graphify update .`, `make ci-resume`, CHANGELOG, drift sweep) → **Thermos** (thermo-nuclear review; must come back **clean including `low`**; **blocks the PR**, D31) → **Re-verify** (post-Thermos, only when the Thermos gate authored code; **fresh** `wave-verifier`; **blocks the PR**, D30).
    - **Deployment verification at Verify gates.** When a batch touches compose, sandbox, gateway runtime, or dashboard HTTP surfaces, its Verify gate runs the relevant subset of **`make verify-*`** drivers (`scripts/verify_deployment.py`; targets at `Makefile:611-626`) and **pastes each driver's `VERIFY_OVERALL:` line** into the gate record. TestClient-only proof is not sufficient for those surfaces.
    - **A `low` is closed by a fix or by a written deferral, never by silence (D31).** The gate record carries the finding, its severity, its `file:line`, and why it is safe to leave, plus a follow-up issue. An omitted `low` is a gate failure, not a judgement call.
9. **New config keys go through the schema** — `make config-schema` after touching `infra/sevn.schema.json`, and keep `tests/infra/test_ci_steps_tier_parity.py` green when adding a `ci-*` tier check.
10. After Python edits in each batch Final: **`graphify update .`** (AST-only) when the CLI is on PATH.
11. **No gate certifies its own edits (D29, D30).** A commit authored *at* a gate has passed no gate — no RED test, no Verify pass, no independent review. In the predecessor program this was the single largest structural cause of escapes.
    - **Before its first edit**, every Thermos gate records its base SHA:
      `git rev-parse HEAD > .ignorelocal/waves/prod-ready-<batch>-thermos-base.sha` (`<batch>` = `a`…`f`).
    - **A gate agent that edits code must declare what it changed** in its gate record: every file touched, the finding each edit answers, and whether a RED test covers it.
    - The **Re-verify** gate runs this detection and is **required** whenever the third command prints anything:

      ```bash
      BASE="$(cat .ignorelocal/waves/prod-ready-<batch>-thermos-base.sha)"
      git log --format='%h %s' "$BASE"..HEAD     # every commit authored at the gate
      git diff --name-only "$BASE"..HEAD         # empty → review-only: record that and close the gate
      git diff --name-only "$BASE"..HEAD -- . \
        ':(exclude)docs/**' ':(exclude)about-sevn.bot/**' ':(exclude)CHANGELOG.md'
      ```

    - Re-verify **re-runs the batch's Verify criteria against the post-Thermos tree**, plus `make ci-affected SEVN_CI_BASE="$BASE"`. It is owned by a **fresh `wave-verifier`** and **may not fix what it finds** — findings go back to `wave-plan-executor`, or to `test-creator` for anything under `tests/` (D4).
    - A skipped Re-verify is **recorded, not assumed**: write the empty `git diff --name-only` output into the batch record.
12. **The repository's own escape rules are gate criteria, not advice** (`.cursor/rules/audit-escape-patterns.mdc`). **P2:** review commits authored at a gate as new work. **P3:** an `intentional / by design / dev-only / advisory / for now / temporary / needs-implementation` annotation is **not** a waiver when the subject is a credential guard, a release/supply-chain gate, or anything whose unsafe branch is the shipped default. Every one of those three categories is in scope for this program — Batch A is a credential guard, Batch C is a release gate, and finding 1 is an unsafe shipped default.

## Decisions baked into this plan

| # | Topic | Decision |
|---|---|---|
| **D1** | Worktree + branch mandatory | One worktree per batch from `origin/pre-0.0.1`; assert before first edit; primary checkout is off-limits |
| **D2** | Per-wave commit + push | Every wave ends with a conventional commit and push before its checkbox is ticked |
| **D4** | **`tests/` is test-creator-only** | Implementation agents never edit `tests/`; disputed tests are escalated at the Verify gate |
| **D5** | `make ci` never mid-wave | `make ci-affected` mid-wave; `make ci-resume` at batch Final |
| **D7** | Drift fixes are one commit | All stale readme + about-docs fingerprints refreshed together, then `make ci-infra ci-docs ci-skills ci-parity` before push |
| **D29** | **Gate-authored code is unverified** | Any commit authored *at* a gate must be re-verified before its batch PR opens; the gate agent declares every file it touched |
| **D30** | **Post-Thermos Re-verify blocks the PR** | Owned by a **fresh `wave-verifier`** that did not run that batch's Thermos; hands findings back rather than fixing them |
| **D31** | **Thermos must be clean including `low`** | A `low` closes only via a fix or an explicit deferral record plus a follow-up issue |
| **D35** | **A ↔ D Compose hotspot** | `docker/docker-compose.yml` is owned by **Batch A** (env, bootstrap service, healthcheck). Batch D does its hardening/limits/perms edits **last** (W15, W16), after `git fetch origin && git rebase origin/pre-0.0.1` onto merged Batch A. If A has not merged when D reaches W15, **D stops and waits** — it does not restructure the file itself |
| **D36** | **A ↔ E `proxy/auth.py` hotspot** | Batch A changes *how the secret is resolved*; Batch E changes *what the guard accepts*. **E rebases onto merged A before W19.** E never edits secret resolution; A never edits the guard's accept branches |
| **D37** | **C1.2 generates, it does not placeholder** | A one-shot init service generates the secret into `sevn-state` (e.g. `/operator/.sevn/proxy-shared-secret`, mode `0600`, uid 10001) on first boot and both services read it. **Remove** the blank `SEVN_PROXY_SHARED_SECRET=` from `.env.example:65` rather than documenting it — a blank placeholder recreates the silent-empty path the source document explicitly warns against. An explicitly-set env value still wins, for operators using an external secret manager |
| **D38** | **C1.3 preflight covers three variables** | The placeholder/entropy blacklist applies to `SEVN_PROXY_SHARED_SECRET`, **`SEVN_GATEWAY_TOKEN`** and **`SEVN_SECRETS_PASSPHRASE`** — `change-me` ships today for the latter two (`.env.example:60`, `:67`). The gate runs **before** services start and lives in `scripts/check-compose-default.sh` or a sibling wired into `make compose-up` *and* a `ci-*` tier |
| **D39** | **C1.4 probes a guarded prefix** | The proxy healthcheck presents the resolved service secret against a guarded route family and treats **503 or 401 as unhealthy**. `/healthz` (`docker/docker-compose.yml:86-97`) stays as the liveness probe; the authenticated probe is added, not substituted. It must not consume provider quota — probe the cheapest guarded endpoint, or add a guarded no-op |
| **D40** | **Batch A must not regress C1.1** | The fail-closed 503 branch, `SEVN_PROXY_ALLOW_UNAUTHENTICATED`, and the boot warning are landed contracts with regression tests. Batch A's acceptance requires `tests/proxy/test_auth.py` and `tests/proxy/test_post_audit_proxy_auth_w4_red.py` green **and unmodified** |
| **D41** | **C3.2 deletes the write-back in the same commit** | `os.environ["SEVN_PROXY_SHARED_SECRET"] = proxy_secret` (`src/sevn/proxy/credentials.py:805-806`) is deleted together with the eleven read sites. Partial removal is worse than none — it leaves an invisible global coupling (finding 3) |
| **D42** | **C4.1 is one constant, three call sites** | A single build-stamped module constant (default digest pinned at release build) replaces `sandbox_runtime.py:1756`, `:2103` and `src/sevn/agent/runtimes/sandbox.py:308`. The `rlm.docker_image` override stays authoritative. **Also add the missing `sandbox.docker_image` key or an explicit schema note** that it does not exist — a plausible-looking key that silently does nothing is its own defect |
| **D43** | **C5 is caching, not re-pinning** | The pull-then-pin contract and its fail-closed error (`sandbox_runtime.py:1499`) are **unchanged**. W8 adds a process-lifetime cache keyed by configured image ref, a local-image short circuit before `docker pull`, and an explicit refresh operation. **Never** reintroduce the `.Id` fallback (finding 4) |
| **D44** | **C2.2 chooses deletion over implementation** | Implementing real Dev deploy + smoke (phases 2/3) requires an environment this repo does not have. W10 **deletes** phases 2 and 3 together with the `needs_impl_ok` escape hatch, and records the deployment intent in `25-cicd-full.md`. Phases 4/5 stay as documented stubs because `C2.3` already makes them block a tag build. A permanently-tolerated failing job trains everyone to ignore red |
| **D45** | **C13.1 + C12.3 land as one design** | Quarantine-then-promote and "no `latest` from `main`" are the same pipeline change: build → push **quarantine tag only** → scan → sign → promote SHA (and `latest` only behind a real gate) **by digest**. Splitting them produces two rewrites of the same five publish steps |
| **D46** | **C11.1 prefers pinned actions over checksums** | `cosign` already uses a SHA-pinned action in the same job (`.github/workflows/ci-cd.yml:189-190`) — the correct pattern exists in-repo. Use SHA-pinned actions for syft and trivy; fall back to download-and-verify-checksum only where no action exists |
| **D47** | **C11.2 pins `uv`, it does not accept the risk** | `Makefile:48` gets a pinned version and a checksum verification step. "Accepted developer-machine risk" is rejected: agents run `make setup` on machines holding operator credentials |
| **D48** | **C9.1 needs the test change first** | `tests/infra/test_post_audit_compose_w1_red.py` pins the full-tree `find` form. **W13 (`test-creator`) updates it before W15 touches the compose command** — the reverse order makes W15 look like a regression |
| **D49** | **C10.3 is proven before it is written** | W16 captures `docker compose -f … config` for the base, browser, GUI and CI file sets and adds `deploy.resources.limits` **only where the resolved config lacks them** (finding 5). Speculative YAML in an override that already inherits limits is drift |
| **D50** | **C8.3 is the program's largest structural change** | Splitting the browser into its own service — narrow authenticated control protocol, no `sevn-state` mount, no `SEVN_GATEWAY_TOKEN` — is scoped as its **own wave (W17) at the end of Batch D**. If W17 cannot complete without destabilising the batch, it is **split into its own follow-up PR** against `pre-0.0.1` rather than compressed; C8.1/C8.2/C8.4 must not be held hostage to it |
| **D51** | **C7.2 differentiates authority by route family** | The service secret keeps authority on gateway→proxy families; sandbox-originated families require a session token carrying the matching scope. A sandbox presenting the service secret is **rejected**, which is the whole point of the two-credential model (`auth.py:272-280` currently accepts it) |
| **D52** | **C14.1 treats `driver_unavailable` as failure on the release path** | Exit 2 is acceptable on the daily cron (a runner may lack Docker) and **not** acceptable on `refs/tags/v*`. The job lands in `ci-supplementary.yml` for the cron and in `ci-cd.yml` for the tag path |
| **D53** | **Spec edits are append-only Amendments** | For 02/06/07/08/09/19/22/24, append `## Amendments (prod-readiness-0.0.1 Wn — CX.Y)`. Only `25-cicd-full.md` has live prose to edit in place |
| **D54** | **Batch ordering is D35 and D36 only** | B, C and F are independent of everything. A must merge before D reaches W15 and before E reaches W19. F's W23 (`C14.1`) lands last so the evidence job is wired against the fixed stack, not a red one |

## Out of scope

- Public `0.0.1` tag or PyPI publish — this plan is a prerequisite only.
- **Implementing real production deploy phases 4/5.** `C2.3` already blocks a tag on them; W10 deletes the *untrustworthy* phases 2/3 and documents the gap (D44). Standing up a Dev/Prod environment is its own program.
- **A real forward-proxy layer** — the predecessor program removed the non-functional `HTTP_PROXY`/`HTTPS_PROXY`/`NO_PROXY` vars from the sandbox child env; building CONNECT-tunnel support remains a separate product decision.
- **Re-architecting proxy exposure on the `sevn-sandbox` network.** The predecessor documented the tradeoff (`ensure_proxy_attached_to_sandbox_network`); `C7.2` and `C7.3` reduce what an attached sandbox can *do* rather than removing the attachment.
- **Docker secrets / mounted secret files for `OPENAI_API_KEY`** — a tracked follow-up from the predecessor program; `C1.2` covers the **proxy shared secret** only.
- Re-litigating any landed contract in the "Already landed" table, in particular `C1.1` (D40) and the pull-then-pin error path (D43).

---

## Wave checklist

**Legend:** `[x]` done · `[ ]` not started

| Wave | Role | Closes | Scope | Status |
|------|------|--------|-------|--------|
| W0 | executor | — | Baseline: anchor freeze, six worktrees, `verify-deployment` RED baseline, stock-stack 503 repro, deferral-overlap check → commit+push | [x] (2026-08-05 ✅: `2c1c6831` — `.ignorelocal/waves/prod-readiness-0.0.1-w0-anchor-freeze.md`; six worktrees; no tracked commit — gitignored artefacts on disk) |
| **Batch A — Proxy secret authority** (`wave/prod-ready-a-proxy-secret`) |||||
| W1 | **test-creator** | — | RED: settings allowlist, chain resolution both sides, no env fallbacks, loud client failure, bootstrap file, preflight, authenticated healthcheck | [x] (2026-08-05 ✅: `611363e5` — 52 collected; 7 pass / 45 xfail; `make ci-affected SEVN_CI_BASE=HEAD` green) |
| W2 | executor | C3.1, C1.5 | One configuration authority — `ProcessSettings` + gateway-side chain resolution | [x] (2026-08-05 ✅: `b6057395` — ProcessSettings + chain; test-creator un-xfail W1.1/W1.2 — 7 passed @ `dcb26589`) |
| W3 | executor | C3.2, C3.3 | Thread the secret; delete eleven `os.environ` reads **and** the write-back (D41); fail loudly on empty | [x] (2026-08-05 ✅: `72618354` — inject + delete fallbacks/write-back; test-creator un-xfail W1.3/W1.4 @ `6f1410fb`) |
| W4 | executor | C1.2 | Generate the secret into `sevn-state` from a one-shot init service (D37) | [x] (2026-08-05 ✅: `220af5d9` — sevn-operator-perms generate-once; test-creator un-xfail W1.5 — 5 passed @ `1a15b434`) |
| W5 | executor | C1.3, C1.4 | `compose-up` preflight over three variables (D38); authenticated proxy healthcheck (D39) | [x] (2026-08-05 ✅: impl `cc503f59`; test-creator un-xfail W1.6/W1.7 — Batch A RED 47 passed / 0 xfail @ `07bde5b6`) |
| A-Verify / A-Final / A-Thermos / A-Reverify | verifier / executor / review / **fresh verifier** | — | Batch gates (D29, D30, D40) | [x] (2026-08-05 ✅: `940ab3ca` — VERIFY_OVERALL pass; W0.3 503 closed; D40 green; gate record `.ignorelocal/waves/prod-ready-a-verify.md`) / [x] (2026-08-05 ✅: `76bc40ec` — 0 xfail; graphify; D7 drift; CHANGELOG; `make ci-resume` all 39 steps passed) / [x] (2026-08-05 ✅: `104ca2b2` — pass incl. low; Compose ProcessSettings gap fixed; gate `.ignorelocal/waves/prod-ready-a-thermos.md`; test-creator reconcile after) / [x] (2026-08-05 ✅: `b8c21cb1` — ci-affected green vs thermos base; D40 unmodified 50 passed; P4a pins green; A-R6 env skip `evidence/verify/stack-health-20260805T180351Z.json`; gate `.ignorelocal/waves/prod-ready-a-reverify.md`) |
| A-PR | executor | C1.2–C1.5, C3.1–C3.3 | Open PR against `pre-0.0.1` | [ ] |
| **Batch B — Sandbox image integrity** (`wave/prod-ready-b-sandbox-image`) |||||
| W6 | **test-creator** | C5.4 | RED: no mutable-tag literal, one constant, N spawns → one pull, startup pin, local short circuit, explicit refresh | [ ] |
| W7 | executor | C4.1, C4.3 | Single build-stamped digest constant + mutable-tag CI check (D42) | [ ] |
| W8 | executor | C4.2, C5.1, C5.2, C5.3 | Startup resolve + process-lifetime cache + local short circuit + explicit update op (D43) | [ ] |
| B-Verify / B-Final / B-Thermos / B-Reverify | verifier / executor / review / **fresh verifier** | — | Batch gates (D29, D30) | [ ] / [ ] / [ ] / [ ] |
| B-PR | executor | C4.1–C4.3, C5.1–C5.4 | Open PR against `pre-0.0.1` | [ ] |
| **Batch C — Release & supply chain** (`wave/prod-ready-c-supply-chain`) |||||
| W9 | **test-creator** | — | RED: aggregator naming, no `needs_impl_ok`, no `latest` from `main`, quarantine-then-promote, no `curl \| sh` | [ ] |
| W10 | executor | C2.1, C2.2 | Rename the aggregator; delete phases 2/3 with the escape hatch (D44) | [ ] |
| W11 | executor | C13.1, C13.2, C12.3 | Quarantine tag → scan → sign → promote by digest; no `latest` from `main` (D45) | [ ] |
| W12 | executor | C11.1, C11.2, C11.3 | SHA-pinned syft/trivy; pinned+verified `uv`; grep gate (D46, D47) | [ ] |
| C-Verify / C-Final / C-Thermos / C-Reverify | verifier / executor / review / **fresh verifier** | — | Batch gates (D29, D30) | [ ] / [ ] / [ ] / [ ] |
| C-PR | executor | C2.1, C2.2, C11.\*, C12.3, C13.\* | Open PR against `pre-0.0.1` | [ ] |
| **Batch D — Isolation & operator runtime** (`wave/prod-ready-d-isolation`) |||||
| W13 | **test-creator** | C9.3 | RED + prerequisite: unpin the full-tree `find` (D48); overlay-wide `--no-sandbox` guard; marker; `HostConfig` limits | [x] (2026-08-06 ✅: c55078d5 — RED suite + C9.3 unpin) |
| W14 | executor | C8.1, C8.2, C8.4 | Remove `--no-sandbox` from prod; widen guard to overlays; delete stale comments; site-isolation decision | [x] (2026-08-06 ✅: 72e790da / a5d7bba6 — sandbox flags + un-xfail W13.2–W13.4) |
| W15 | executor | C9.1, C9.2, C9.4 | **After A merges (D35)** — scoped chown, versioned init marker, `sevn-ci-init` parity | [x] (2026-08-06 ✅: 70235cae — scoped+marker; un-xfail → test-creator) |
| W16 | executor | C10.1, C10.2, C10.3 | Compose version floor; `HostConfig` integration check; limits where resolved config lacks them (D49) | [x] (2026-08-06 ✅: 85893705 — floor+limits+HostConfig; un-xfail → test-creator) |
| W17 | executor | C8.3 | Browser as its own minimally-privileged service (D50 — split to a follow-up PR if it destabilises the batch) | [x] (2026-08-06 ✅: D50 deferred — follow-up issue) |
| D-Verify / D-Final / D-Thermos / D-Reverify | verifier / executor / review / **fresh verifier** | — | Batch gates (D29, D30) | [x] (2026-08-06 ✅: `9f369788` — VERIFY_OVERALL pass for compose-profiles + stack-health; HostConfig NanoCpus/Memory/PidsLimit match declared limits; W13.9 xfail retained for #240; gate record `.ignorelocal/waves/prod-ready-d-verify.md`) / [x] (2026-08-07 ✅: `fe4b7c14` — xfail sweep 0/141; graphify AST clean; D7 drift 2 specs; 10/10 C-IDs cited; 41/41 ci-resume steps green on iter 6; spec-kit-wave W1 RED ignores applied) / [x] (2026-08-07 ✅: `636aa69c` — clean including low; fresh D30 verifier; all 5 proofs re-confirmed; P2/P3/P5 clean; gate record `.ignorelocal/waves/prod-ready-d-reverify.md`) / [ ] |
| D-PR | executor | C8.\*, C9.\*, C10.\* | Open PR against `pre-0.0.1` | [ ] |
| **Batch E — Scoped egress authority** (`wave/prod-ready-e-egress-scope`) |||||
| W18 | **test-creator** | — | RED: `run_id` claim, container binding, service secret rejected on sandbox families, allowlist + budget enforcement | [ ] |
| W19 | executor | C7.1, C7.2 | **After A merges (D36)** — `run_id` + container binding; reject the service secret on sandbox families (D51) | [ ] |
| W20 | executor | C7.3, C7.4 | Destination allowlist + per-run request/byte budgets; correct the schema description | [ ] |
| E-Verify / E-Final / E-Thermos / E-Reverify | verifier / executor / review / **fresh verifier** | — | Batch gates (D29, D30) | [ ] / [ ] / [ ] / [ ] |
| E-PR | executor | C7.1–C7.4 | Open PR against `pre-0.0.1` | [ ] |
| **Batch F — Evidence & dashboard residuals** (`wave/prod-ready-f-evidence`) |||||
| W21 | **test-creator** | — | RED: trust-address refused under tunnel/proxy, boot warning, CLI message, driver coverage, tag-path exit-2 handling | [ ] |
| W22 | executor | C6.2, C6.4 | Guard and rename the trust-address escape; warn at boot; fix the CLI message | [ ] |
| W23 | executor | C14.1, C14.2, C14.3 | Wire `make verify-deployment` into cron + tag path (D52); new drivers; attach evidence to the release | [ ] |
| F-Verify / F-Final / F-Thermos / F-Reverify | verifier / executor / review / **fresh verifier** | — | Batch gates (D29, D30) | [ ] / [ ] / [ ] / [ ] |
| F-PR | executor | C6.2, C6.4, C14.1–C14.3 | Open PR against `pre-0.0.1` | [ ] |
| **Program close** |||||
| Z1 | executor | all 42 | Refresh the sweep index, re-run `make verify-deployment`, plan → COMPLETE | [ ] |

---

## Wave W0 — Program baseline

**Runs in:** primary checkout, **read-only** for source; writes only the anchor-freeze doc under `.ignorelocal/waves/`.

- [x] **W0.0** `git fetch origin`; record the `origin/pre-0.0.1` SHA (expected `2c1c6831`); run `make check-git-guards` and re-run `make install-git-guards` if the PATH wrapper is missing. (2026-08-05 ✅: `2c1c6831` — `2c1c683153a762031ff1c195b7ac41aa16c57b78`; `make check-git-guards: ok`)
- [x] **W0.1** Create the six worktrees from **D1**. Confirm each has `about-sevn.bot/specs/` and `about-sevn.bot/prd/` present. (2026-08-05 ✅: `2c1c6831` — `../sevn-pr-{a..f}-*` all @ `2c1c6831`; specs+prd+seeded `.ignorelocal`/`.claude`/`.cursor`)
- [x] **W0.2** **Re-validate the "Already landed" table** against the base SHA. Any row that does not reproduce is a plan defect — stop and correct the plan before scoping a wave. This is the step that prevents re-reverting #167/#169/#173. (2026-08-05 ✅: `2c1c6831` — C1.1/C2.3/C6.1/C6.3/C12.* reproduce; **C7.1 plan wording corrected** — `run_id` already in mint payload)
- [x] **W0.3** **Reproduce finding 1 — the stock-stack 503.** Bring up `docker compose -f docker/docker-compose.yml up -d` with an unset `SEVN_PROXY_SHARED_SECRET`, then issue a guarded request against the proxy (`/llm/…`, `/web/…`, `/integration/…`) and record the exact **503** body (`PROXY_UNCONFIGURED_DETAIL`). Record the same for the browser and GUI file sets. This is the RED evidence W1 asserts against. (2026-08-05 ✅: `2c1c6831` — body `{"detail":"proxy authentication not configured"}` on `/llm/*` `/web/*` `/integration/*` for base+browser+GUI; `/healthz` 200)
- [x] **W0.4** Record the **`make verify-deployment` RED baseline** — run each driver and record its `VERIFY_OVERALL:` line (`Makefile:611-626`). Expected: `stack-health` reaches `/health` and `/ready` (the gateway boots) while guarded proxy traffic still 503s — the drivers do **not** currently probe authenticated egress, which is precisely `C14.2`. (2026-08-05 ✅: `2c1c6831` — compose-profiles/stack-health/runtime **pass**; sandbox-spawn **fail**; all **fail**; see anchor freeze)
- [x] **W0.5** Enumerate the eleven `os.environ.get("SEVN_PROXY_SHARED_SECRET")` call sites and the write-back, with verified `file:line`, into the anchor freeze:
      `git grep -n 'SEVN_PROXY_SHARED_SECRET' -- src/`
      Confirmed at `2c1c6831`: `agent/providers/transport.py:612`, `data/bundled_skills/core/job-ops/scripts/lib/llm.py:87`, `gateway/http_server.py:713`, `integrations/github_skill/hooks.py:90`, `integrations/proxy_client.py:36`, `model_eval/compare.py:148`, `proxy/credentials.py:805` (**write-back**), `security/sandbox_runtime.py:543`, `tools/integration_proxy_client.py:184`, `tools/web.py:148`, `ui/dashboard/services/sandbox_terminal.py:290`.
      (2026-08-05 ✅: `2c1c6831` — eleven reads confirmed; write-backs at `credentials.py:806` **and** `http_server.py:728`)
- [x] **W0.6** Record the three `sandbox:dev` literals with verified lines — `security/sandbox_runtime.py:1756`, `:2103`, `agent/runtimes/sandbox.py:308` — and confirm no `sandbox.docker_image` key exists in `infra/sevn.schema.json` (D42). (2026-08-05 ✅: `2c1c6831` — three literals confirmed; `sandbox.docker_image` absent; `rlm.docker_image` present)
- [x] **W0.7** Capture `docker compose -f … config` for the **base**, **browser**, **GUI** and **CI** file sets and record, per service, whether `deploy.resources.limits` and `pids_limit` survive the merge (finding 5, D49). W16 scopes itself from this output. (2026-08-05 ✅: `2c1c6831` — browser/GUI inherit gateway/proxy limits; CI has **none**)
- [x] **W0.8** Check the five inherited deferral issues (#185, #186, #187, #212, #213) against this plan's 42 IDs. Record every overlap so a batch neither duplicates a filed deferral nor contradicts its stated resolution. (2026-08-05 ✅: `2c1c6831` — **#187 overlaps C5.1–C5.3** → W8 should `Closes #187`; #185/#186/#212/#213 no CX.Y)
- [x] **W0.9** Record the baseline state of the suites this program must **not** break (Recent baseline / drift) — run each and record pass counts. (2026-08-05 ✅: `2c1c6831` — **107 passed** across nine suites; per-file counts in anchor freeze)
- [x] **W0.10** Write `.ignorelocal/waves/prod-readiness-0.0.1-w0-anchor-freeze.md` with verified `file:line` anchors for W1–W23; commit + push — *(suggested: `chore(wave): W0 baseline for prod-readiness 0.0.1 program`)*. (2026-08-05 ✅: `2c1c6831` — anchor freeze written; **no tracked commit** — `.ignorelocal/` gitignored; artefacts on disk only)

**Acceptance:** anchor freeze written; six worktrees exist on `origin/pre-0.0.1`; the "Already landed" table reproduces; the stock-stack 503 is reproduced with recorded output; `verify-deployment` baseline recorded; compose-merge limits table recorded. (**MET** 2026-08-05 @ `2c1c6831`.)

---

# Batch A — Proxy secret authority & default-stack bootstrap

**Branch:** `wave/prod-ready-a-proxy-secret` · **Worktree:** `../sevn-pr-a-proxy-secret` · **Closes:** C1.2, C1.3, C1.4, C1.5, C3.1, C3.2, C3.3
**Owns `docker/docker-compose.yml`** for this program (D35) — Batch D rebases onto merged A before W15, Batch E before W19 (D36).
**Hard constraint (D40):** the landed `C1.1` fail-closed contract must stay green and unmodified.

## Wave W1 — RED suite (`test-creator`)

**Spec/PRD:** `about-sevn.bot/specs/02-config-and-workspace.md` · `06-secrets.md` · `07-egress-proxy.md`

- [x] **W1.1** Assert `SEVN_PROXY_SHARED_SECRET` is a member of `PROCESS_SETTINGS_ENV_VAR_NAMES` (`src/sevn/config/settings.py:28-38`) and parses into `ProcessSettings` (**xfail → W2**). New `tests/config/test_prod_ready_proxy_secret_settings_w1_red.py`.
- [x] **W1.2** Assert the **gateway** side resolves the secret from the secrets chain, not only the proxy process — `src/sevn/agent/adapters/egress_bridge.py:55` is env-only today (**xfail → W2**).
- [x] **W1.3** Assert **zero** `os.environ.get("SEVN_PROXY_SHARED_SECRET")` reads remain under `src/` outside the single resolution seam, and that `src/sevn/proxy/credentials.py` no longer **writes** `os.environ` (D41) (**xfail → W3**). A source-level assertion is correct here: the defect is the *existence* of the fallbacks. (2026-08-05 ✅: `6f1410fb` — un-xfail PASS)
- [x] **W1.4** Assert a guarded-route client with an empty resolved secret raises a named, actionable error rather than sending an empty header (**xfail → W3**) — cover `tools/web.py`, `tools/integration_proxy_client.py`, `integrations/proxy_client.py`, `integrations/github_skill/hooks.py`. (2026-08-05 ✅: `6f1410fb` — un-xfail PASS)
- [x] **W1.5** Assert the bootstrap contract (**xfail → W4**): on a clean `sevn-state` volume a secret file is created at the agreed path with mode `0600` and uid `10001`; it is **not** regenerated on the next boot; an explicitly-set env value takes precedence; `.env.example` contains **no** blank `SEVN_PROXY_SHARED_SECRET=` line (D37). (2026-08-05 ✅: `1a15b434` — un-xfail PASS)
- [x] **W1.6** Assert the preflight (**xfail → W5**, D38) rejects empty, below-entropy-threshold, and placeholder values (`change-me`) for `SEVN_PROXY_SHARED_SECRET`, `SEVN_GATEWAY_TOKEN` and `SEVN_SECRETS_PASSPHRASE`, and that it runs **before** services start.
- [x] **W1.7** Assert the proxy healthcheck presents the service secret against a guarded prefix and that **503/401 is unhealthy** (**xfail → W5**, D39). Parse `docker/docker-compose.yml` directly so the test runs without a Docker daemon.
- [x] **W1.8** **Guard test (D40):** assert `tests/proxy/test_auth.py` and `tests/proxy/test_post_audit_proxy_auth_w4_red.py` pass **unmodified** — the 503 branch, the `SEVN_PROXY_ALLOW_UNAUTHENTICATED` opt-in, and the boot warning are landed contracts.
- [x] **W1.9** Author `docs/test-plans/prod-ready-batch-a.md`; `make lint typecheck` on touched paths; commit + push.

**Acceptance:** all W1 tests collect; W1.1–W1.7 fail or xfail on the batch base with wave markers; W1.8 passes on the base; `make ci-affected SEVN_CI_BASE=HEAD` green.

**W1 close-out (2026-08-05):** 52 collected; 7 passed / 45 xfailed (`strict=True` markers → W2–W5); C1.1 suites 50 passed unmodified; `make lint typecheck` + `make ci-affected SEVN_CI_BASE=HEAD` green; tip `611363e5`.

## Wave W2 — One configuration authority (C3.1, C1.5)

**Spec/PRD:** `about-sevn.bot/specs/02-config-and-workspace.md` · `06-secrets.md` (Amendments) · `about-sevn.bot/prd/03-trust-and-control.md`
**Files:** `src/sevn/config/settings.py`, `src/sevn/agent/adapters/egress_bridge.py`, `src/sevn/proxy/settings.py`, `infra/sevn.schema.json`

- [x] **W2.1** Add `SEVN_PROXY_SHARED_SECRET` to `PROCESS_SETTINGS_ENV_VAR_NAMES` (`src/sevn/config/settings.py:28-38`) and the corresponding `ProcessSettings` field, so the variable is inside the audited configuration contract rather than beside it. (2026-08-05 ✅: `ProcessSettings.proxy_shared_secret` + allowlist membership)
- [x] **W2.2** Give the **gateway** the same secrets-chain resolution the proxy already has: `resolve_proxy_shared_secret` (`src/sevn/agent/adapters/egress_bridge.py:55`) consults the workspace secrets chain before falling back to process env, mirroring `_resolve_proxy_shared_secret` (`src/sevn/proxy/credentials.py:810`). One resolution seam, two processes. (2026-08-05 ✅: `resolve_proxy_shared_secret(..., chain=)` env-first then `_resolve_proxy_shared_secret_from_chain`)
- [x] **W2.3** Confirm `ProxySettings.proxy_shared_secret` (`src/sevn/proxy/settings.py:40-43`) keeps its `AliasChoices` env binding — the env path stays supported for external secret managers; it stops being the *only* path. (2026-08-05 ✅: AliasChoices unchanged; no edit)
- [x] **W2.4** Run **`make config-schema`** and update `infra/sevn.schema.json` env documentation for the variable. Add the Amendments to specs 02 and 06 (D53). (2026-08-05 ✅: schema allowlist + Amendments on specs 02/06; `make config-schema` ok)
- [x] **W2.5** Un-xfail W1.1/W1.2; `make lint typecheck`; commit + push — *(suggested: `fix(config): make the proxy shared secret a first-class settings surface`)*. (2026-08-05 ✅: impl `b6057395`; test-creator un-xfail W1.1/W1.2 — 7 passed @ `dcb26589`, not XPASS; see W2 close-out)

**Acceptance:** W1.1/W1.2 green; W1.8 still green; `make config-schema` clean; `make ci-affected SEVN_CI_BASE=HEAD` green.

**W2 close-out (2026-08-05):** Implementation landed at `b6057395`. **test-creator un-xfail:** removed `prod-ready W2` markers from `tests/config/test_prod_ready_proxy_secret_settings_w1_red.py` (W1.1) and `tests/agent/test_prod_ready_egress_secret_chain_w1_red.py` (W1.2) — **7 passed** (not XPASS) at `dcb26589`; W1.3–W1.7 xfails + W1.8 guards intact; `make lint typecheck` + `make ci-affected SEVN_CI_BASE=HEAD` green. Env fallbacks / write-back untouched (W3/D41). Pushed to `origin/wave/prod-ready-a-proxy-secret`.

## Wave W3 — Delete the env fallbacks and the write-back (C3.2, C3.3, D41)

**Spec/PRD:** `about-sevn.bot/specs/07-egress-proxy.md` (Amendment) · `about-sevn.bot/prd/03-trust-and-control.md` · `05-cost-and-providers.md`
**Files:** the eleven sites from W0.5, `src/sevn/gateway/http_server.py`, `src/sevn/tools/runtime_bindings_factory.py`

- [x] **W3.1** Thread the resolved secret into `build_runtime_tool_bindings` from the gateway (`src/sevn/gateway/http_server.py` — the bindings call site currently passes `proxy_url` and `session_token` but no shared secret), so tool clients receive it by injection. (2026-08-05 ✅: `173e6838` — `_with_resolved_proxy_shared_secret` → `proxy_shared_secret=` on bindings)
- [x] **W3.2** Delete the `os.environ.get("SEVN_PROXY_SHARED_SECRET")` reads at the ten call sites from W0.5, replacing each with the injected value. Where a site is genuinely out-of-process (`data/bundled_skills/core/job-ops/scripts/lib/llm.py:87` runs inside a sandbox), keep the env read but document it as the sandbox child-env contract rather than a gateway fallback — and record that decision in the wave notes. (2026-08-05 ✅: `173e6838` — ProcessSettings/injection at 9 sites; llm.py seam kept + documented)
- [x] **W3.3** **In the same commit**, delete the `os.environ["SEVN_PROXY_SHARED_SECRET"] = proxy_secret` write-back at `src/sevn/proxy/credentials.py:805-806` (D41). Verify the proxy still resolves its secret through `settings.model_copy(update=…)` alone. (2026-08-05 ✅: `173e6838` — credentials write-back deleted; gateway prime is no-op; `model_copy` retained)
- [x] **W3.4** **C3.3** — make a guarded-route client with an empty resolved secret raise a named, actionable error at call time instead of sending an empty header and surfacing an opaque 401. Name the variable and the remedy in the message. (2026-08-05 ✅: `173e6838` — `ProxySharedSecretUnconfiguredError` via `build_egress_web_headers`)
- [x] **W3.5** Add the Amendment to spec 07 describing the single configuration authority and the client-side failure mode (D53). (2026-08-05 ✅: `173e6838` — `## Amendments (prod-readiness-0.0.1 W3 — C3.2, C3.3)`)
- [x] **W3.6** Un-xfail W1.3/W1.4; `make lint typecheck`; commit + push — *(suggested: `fix(proxy): resolve the shared secret through one authority`)*. (2026-08-05 ✅: impl `173e6838`/`72618354`; test-creator `6f1410fb` — W1.3/W1.4 + legacy suites PASS)

**Acceptance:** W1.3/W1.4 green; W1.8 still green; zero `os.environ` reads of the variable under `src/` outside the documented sandbox child-env seam; `make ci-affected SEVN_CI_BASE=HEAD` green.

**W3 close-out (2026-08-05):** Implementation landed at `173e6838` (tip `72618354` docstring scan fix). **test-creator un-xfail:** removed `prod-ready W3` markers from `tests/proxy/test_prod_ready_env_fallback_removal_w1_red.py` (W1.3) and `tests/tools/test_prod_ready_empty_secret_client_error_w1_red.py` (W1.4); aligned legacy suites (`test_web_tools`, `test_w2_integration_proxy`, `test_w6_readiness::test_web_search_brave_key_missing`, `test_wizard_proxy_shared_secret`) with injected-secret / no-write-back contracts — **12 W1.3/W1.4 + legacy green** (48 focused / 57 `ci-affected`, not XPASS) @ `6f1410fb`; W1.5–W1.7 xfails + W1.8/C1.1 guards intact; `make lint typecheck` + `make ci-affected SEVN_CI_BASE=HEAD` green. Sandbox child-env seam (`job-ops/.../llm.py`) retained. Pushed to `origin/wave/prod-ready-a-proxy-secret`.

## Wave W4 — Bootstrap a real secret (C1.2, D37)

**Spec/PRD:** `about-sevn.bot/specs/22-onboarding.md` · `06-secrets.md` (Amendments) · `about-sevn.bot/prd/06-setup-and-operations.md`
**Files:** `docker/docker-compose.yml`, `docker/docker-compose.browser.yml`, `docker/docker-compose.gui.yml`, `.env.example`, `docker/README.md`, onboarding

- [x] **W4.1** Add a one-shot init step that generates a high-entropy secret into the shared `sevn-state` volume (e.g. `/operator/.sevn/proxy-shared-secret`, mode `0600`, owner `10001:10001`) **only when absent**. Reuse `sevn-operator-perms` (`docker/docker-compose.yml:50-63`) or add a sibling with `restart: "no"` — record which and why. (2026-08-05 ✅: `220af5d9` — **reused `sevn-operator-perms`**: keeps the three-service `check-compose-default` set; generation runs before the scoped chown so uid 10001 is applied in the same pass; no extra image)
- [x] **W4.2** Have **both** `sevn-proxy` (`:76`) and `sevn-gateway` (`:108`) read the generated value, with an explicitly-set `SEVN_PROXY_SHARED_SECRET` still taking precedence. Apply the same to `docker-compose.browser.yml:18` and `docker-compose.gui.yml:18`. (2026-08-05 ✅: `220af5d9` — resolve order env→file→chain in egress_bridge + credentials; browser/gui comments document override)
- [x] **W4.3** **Remove** the blank `SEVN_PROXY_SHARED_SECRET=` line from `.env.example:65` and rewrite the comment at `:64` to describe generation. Do not replace it with another empty placeholder (D37). (2026-08-05 ✅: `220af5d9` — blank assignment removed; generation/override comment only)
- [x] **W4.4** Wire the same generation into the onboarding path so a host install and a Compose install converge on one secret location. Confirm the chain resolution from W2.2 finds it. (2026-08-05 ✅: `220af5d9` — `store_wizard_credentials` ensures `{SEVN_HOME}/.sevn/proxy-shared-secret`; reuses file when present)
- [x] **W4.5** Update `docker/README.md:82` — which currently instructs the operator to set the variable on both services by hand — to document the generated default and the override. (2026-08-05 ✅: `220af5d9` — generated default + env override documented)
- [x] **W4.6** Add the Amendments to specs 22 and 06; un-xfail W1.5; `make lint typecheck`; commit + push — *(suggested: `fix(compose): generate the proxy shared secret on first boot`)*. (2026-08-05 ✅: impl `220af5d9`; test-creator un-xfail W1.5 — 5 passed @ `1a15b434`, not XPASS)

**Acceptance:** W1.5 green; a clean-volume `docker compose up` yields a **working** guarded route (no 503) with no manual step — this is the W0.3 reproduction inverted; `make ci-affected SEVN_CI_BASE=HEAD` green.

**W4 close-out (2026-08-05):** Implementation at `220af5d9`. Bootstrap design: extend `sevn-operator-perms` (not a sibling). **test-creator un-xfail:** removed `prod-ready W4` markers from `tests/infra/test_prod_ready_proxy_secret_bootstrap_w1_red.py` — **5 passed** (not XPASS) at `1a15b434`; W1.6/W1.7 xfails + W1.8 guards intact; `make lint typecheck` + `make ci-affected SEVN_CI_BASE=HEAD` green (5 passed). Pushed to `origin/wave/prod-ready-a-proxy-secret`.

## Wave W5 — Preflight and an honest healthcheck (C1.3, C1.4, D38, D39)

**Spec/PRD:** `about-sevn.bot/specs/07-egress-proxy.md` · `25-cicd-full.md` (compose default check) · `about-sevn.bot/prd/06-setup-and-operations.md`
**Files:** `scripts/check-compose-default.sh` (or a sibling), `Makefile`, `docker/docker-compose.yml`, `.env.example`

- [x] **W5.1** Add the preflight (D38): reject an empty value, a value below a minimum entropy threshold, and a placeholder blacklist that includes **`change-me`**, for `SEVN_PROXY_SHARED_SECRET`, `SEVN_GATEWAY_TOKEN` and `SEVN_SECRETS_PASSPHRASE`. Fail **before** services start. (2026-08-05 ✅: cc503f59 — `scripts/check_compose_operator_secrets.py` `validate_operator_secrets`)
- [x] **W5.2** Wire it into `make compose-up` (and the browser/GUI wrappers via the shared `COMPOSE_FILES` variable) **and** into a `ci-*` tier, keeping `tests/infra/test_ci_steps_tier_parity.py` green (Global convention 9). (2026-08-05 ✅: cc503f59 — `compose-up` + `ci-infra`/`CI_STEPS` `check-compose-operator-secrets`; variants call `compose-up`)
- [x] **W5.3** Decide and record how the preflight interacts with the W4 generated secret: generation should satisfy it automatically, so the gate fires only when an operator supplies a bad explicit value. A preflight that fails the happy path is a worse defect than the one it fixes. (2026-08-05 ✅: cc503f59 — `allow_absent_proxy_shared_secret=True` on CLI; Amendment on spec 07)
- [x] **W5.4** **C1.4** — add the authenticated proxy healthcheck (D39): present the resolved service secret against a guarded prefix; treat 503/401 as unhealthy. Keep `/healthz` (`docker/docker-compose.yml:86-97`) as the liveness probe. Ensure the probe consumes no provider quota — record which endpoint was chosen and why. (2026-08-05 ✅: cc503f59 — `/healthz` + guarded no-op `GET /web/auth-check` with `X-Sevn-Proxy-Token`)
- [x] **W5.5** Update `.env.example` comments for the three variables and `docker/README.md`; add the Amendment to spec 07 and the in-place edit to `25-cicd-full.md` for the new tier check (D53). (2026-08-05 ✅: cc503f59 — comments + README + Amendments)
- [x] **W5.6** Un-xfail W1.6/W1.7; `make lint typecheck`; commit + push — *(suggested: `fix(compose): preflight operator secrets and probe authenticated egress`)*. (2026-08-05 ✅: impl `cc503f59`; test-creator un-xfail W1.6/W1.7 — see W5 close-out)

**Acceptance:** W1.6/W1.7 green; a `change-me` gateway token fails `make compose-up` before any container starts; a misconfigured secret shows up as an **unhealthy** proxy container; tier parity green; `make ci-affected SEVN_CI_BASE=HEAD` green.

**W5 close-out (2026-08-05):** Implementation at `cc503f59`. Preflight: `validate_operator_secrets` rejects empty/placeholder/short for three vars; compose-up skips blank proxy secret (W5.3 generate-once). Healthcheck: `/healthz` + `GET /web/auth-check` (no quota). **test-creator un-xfail:** removed `prod-ready W5` markers from `tests/infra/test_prod_ready_compose_secrets_preflight_w1_red.py` (W1.6) and `tests/infra/test_prod_ready_proxy_auth_healthcheck_w1_red.py` (W1.7) — **Batch A RED 47 passed / 0 xfail** (W1.6+W1.7: 23 passed via `ci-affected`); W1.8 / C1.1 guards unmodified; `make lint typecheck` + `make ci-affected SEVN_CI_BASE=HEAD` green. Batch A ready for A-Verify.

### Batch A gates

- [x] **A-Verify** (`wave-verifier`): **`make verify-stack-health` must pass on a clean `sevn-state` volume** — paste `VERIFY_OVERALL: pass`. Runtime proof: with no operator configuration at all, `docker compose up` and then a **successful** guarded request through the proxy (the W0.3 503 must be gone); an explicitly-set secret still wins; a `change-me` token is refused before boot; a deliberately wrong secret makes the proxy container **unhealthy**. Confirm `tests/proxy/test_auth.py` and `tests/proxy/test_post_audit_proxy_auth_w4_red.py` are green **and unmodified** (D40). Escalate any test defect to `test-creator` (D4). (2026-08-05 ✅: `940ab3ca` — VERIFY_OVERALL pass; evidence `evidence/verify/stack-health-20260805T154853Z.json`; A-V1/A-V2 `a1cfe865`; A-V3 W5 behavioral 2 passed; Batch A RED 54 passed / 0 xfail; gate record `.ignorelocal/waves/prod-ready-a-verify.md`)
  - **A-V3 (test-creator, 2026-08-05):** behavioral suite `tests/proxy/test_prod_ready_proxy_boot_secret_file_w5_red.py` — `create_app()` + bootstrap file + blank env + no workspace must not 503; absent file stays 503 (D40). Un-xfail after A-V1 `a1cfe865` — **2 passed**.
- [x] **A-Final:** xfail sweep over the Batch A RED files (0 xfails); `graphify update .`; **drift sweep in one commit** (D7) — `uv run sevn readme fingerprint <slug> --repo .` for every slug `make readme-check` flags, `make about-docs-extract` for specs 02/06/07/22/25; CHANGELOG `## [Unreleased]` entries for C1.2–C1.5 and C3.1–C3.3; `make ci-resume SEVN_CI_BASE=origin/pre-0.0.1` until all steps pass. (2026-08-05 ✅: `76bc40ec` — 0 xfail Batch A RED; graphify updated; D7 drift `b406d624` + follow-up fingerprints; CHANGELOG C1.2–C1.5/C3.1–C3.3 present; `make ci-resume` all 39 steps passed; D40 suites unmodified)
- [x] **A-Thermos:** thermo-nuclear review of the batch diff; **clean including `low`** (D31); **blocks the PR**. Pay specific attention to whether the generated-secret path can silently fall back to empty, and to any `dev-only` / `for now` annotation on a credential surface (Global convention 12, P3). **Record the base SHA before the first review edit** — `git rev-parse HEAD > .ignorelocal/waves/prod-ready-a-thermos-base.sha` — and **declare every file the review changed** (D29). (2026-08-05 ✅: `104ca2b2` — base `76bc40ec`; initial changes_required → fixed Compose ProcessSettings-only consumers; blank-file regen; wizard overwrite; healthcheck clarity; T7 deferred #228; gate `.ignorelocal/waves/prod-ready-a-thermos.md`; **A-Reverify required**)
  - **test-creator post-Thermos reconcile (2026-08-05):** spawn fail-closed + file mint; transport `complete`/`auth_header` require secret; blank-file regen + wizard overwrite + web egress file resolve; `#228` prime no-op pin kept — see `.ignorelocal/waves/prod-ready-a-thermos.md` + `docs/test-plans/prod-ready-batch-a.md`
- [x] **A-Reverify** (**fresh `wave-verifier`** — never the A-Thermos reviewer): run the convention-11 detection with `<batch>` = `a`. Any Thermos edit inside `src/sevn/proxy/`, `src/sevn/config/settings.py` or `docker/docker-compose.yml` is a **credential surface authored without a RED test**: re-run the A-Verify runtime proofs in full against the post-Thermos tree, confirm a test fails if the fail-closed branch is deleted, and re-run `make ci-affected SEVN_CI_BASE="$BASE"`. Hand findings back (D4); **do not fix them here**. **Blocks A-PR** (D29, D30). (2026-08-05 ✅: `b8c21cb1` — ci-affected 1562+214 green vs base `76bc40ec`; D40 50 passed unmodified; P4a 4 pins green; Batch A reconcile 34 passed; A-R6 env skip apt GPG — gate `.ignorelocal/waves/prod-ready-a-reverify.md`)
- [ ] **A-PR:** open against `pre-0.0.1`, listing C1.2, C1.3, C1.4, C1.5, C3.1, C3.2, C3.3 **one per line** (Global convention 7). Call out that the stock stack's guarded routes change from 503 to working.

---

# Batch B — Sandbox image integrity & spawn cost

**Branch:** `wave/prod-ready-b-sandbox-image` · **Worktree:** `../sevn-pr-b-sandbox-image` · **Closes:** C4.1, C4.2, C4.3, C5.1, C5.2, C5.3, C5.4
**Independent of A, C, D, E, F.**
**Internal hotspot:** `src/sevn/security/sandbox_runtime.py` is edited by W7 (constant) and W8 (caching) — run them serially in this worktree.
**Hard constraint (D43):** the pull-then-pin contract and its fail-closed error (`:1499`) are unchanged; the `.Id` fallback stays deleted.

## Wave W6 — RED suite (`test-creator`)

**Spec/PRD:** `about-sevn.bot/specs/08-sandbox.md`

- [ ] **W6.1** Assert **no mutable-tag literal** (`:dev`, `:latest`, or any non-digest default) survives under `src/` — one constant, three consumers (**xfail → W7**, D42). New `tests/sandbox/test_prod_ready_image_constant_w6_red.py`.
- [ ] **W6.2** Assert all three former literal sites resolve from the same constant: `security/sandbox_runtime.py:1756`, `:2103`, `agent/runtimes/sandbox.py:308` (**xfail → W7**).
- [ ] **W6.3** Assert the schema either defines `sandbox.docker_image` or documents that only `rlm.docker_image` is honoured — a plausible-looking key that silently does nothing is the defect (**xfail → W7**, D42).
- [ ] **W6.4** **C5.4** — assert **N spawns produce exactly one `docker pull`** with mocked `_docker_run` (**xfail → W8**). New `tests/sandbox/test_prod_ready_spawn_pull_cache_w6_red.py`.
- [ ] **W6.5** Assert the digest is resolved and validated **once at gateway startup**, and that a spawn with an already-present digest-pinned image performs **no** pull (**xfail → W8**).
- [ ] **W6.6** Assert an explicit image-update operation exists and is the **only** path that refreshes the cached digest (**xfail → W8**).
- [ ] **W6.7** Assert `C4.2` — startup refuses to proceed when the release digest is absent and cannot be pulled (**xfail → W8**).
- [ ] **W6.8** **Guard test (D43):** assert `tests/sandbox/test_post_audit_image_pin_w4_red.py` passes **unmodified** — pull-then-pin, `SandboxConfigurationError` on empty `RepoDigests`, no bare `sha256:` handed to `docker pull`.
- [ ] **W6.9** Author `docs/test-plans/prod-ready-batch-b.md`; `make lint typecheck`; commit + push.

**Acceptance:** suite collects; W6.1–W6.7 xfail with wave markers; W6.8 passes on the batch base; `make ci-affected SEVN_CI_BASE=HEAD` green.

## Wave W7 — One build-stamped image constant (C4.1, C4.3, D42)

**Spec/PRD:** `about-sevn.bot/specs/08-sandbox.md` (Amendment)
**Files:** `src/sevn/security/sandbox_runtime.py`, `src/sevn/agent/runtimes/sandbox.py`, `infra/sevn.schema.json`, `Makefile`, `.github/workflows/`

- [ ] **W7.1** Introduce a single module-level constant for the default sandbox image, build-stamped to the gateway release as a digest (`ghcr.io/sevn-bot/sevn/sandbox@sha256:…`). Replace the literals at `security/sandbox_runtime.py:1756`, `:2103` and `agent/runtimes/sandbox.py:308` with references to it.
- [ ] **W7.2** Keep `rlm.docker_image` (`infra/sevn.schema.json`) authoritative as the operator override. Resolve the `sandbox.docker_image` gap (D42): either add the key with real behaviour or document in the schema that it is not honoured — do not leave a plausible key that does nothing.
- [ ] **W7.3** **C4.3** — add a CI check rejecting any mutable-tag literal in a release build, wired into a `ci-*` tier with `tests/infra/test_ci_steps_tier_parity.py` kept green (Global convention 9). It must catch `:dev` **and** `:latest`, since Batch C removes `latest` from `main` for the same reason.
- [ ] **W7.4** Record how the constant is stamped at build time — an unstamped default that falls back to a tag reintroduces the defect. State the failure mode when the stamp is missing (fail closed, per D43's spirit).
- [ ] **W7.5** Add the Amendment to spec 08; un-xfail W6.1–W6.3; `make lint typecheck`; commit + push — *(suggested: `fix(sandbox): single-source the default image as a pinned digest`)*.

**Acceptance:** W6.1–W6.3 green; W6.8 still green; the mutable-tag check fails on a deliberately reintroduced `:dev` literal; tier parity green; `make ci-affected SEVN_CI_BASE=HEAD` green.

## Wave W8 — Resolve once, pull rarely (C4.2, C5.1, C5.2, C5.3, D43)

**Spec/PRD:** `about-sevn.bot/specs/08-sandbox.md` (Amendment)
**Files:** `src/sevn/security/sandbox_runtime.py`, gateway startup, `Makefile`

- [ ] **W8.1** **C5.1** — resolve and validate the digest **once at gateway startup** and cache it for the process lifetime, keyed by the configured image ref so an `rlm.docker_image` change is not masked by the cache.
- [ ] **W8.2** **C5.2** — short-circuit `docker pull` (`sandbox_runtime.py:1484`) when the digest-pinned image is already present locally; keep the pull as the cold-start path only. The existing `docker image inspect` at `:1493` is the natural probe.
- [ ] **W8.3** **C5.3** — add an explicit image-update operation as the only path that refreshes the cached digest. Never refresh implicitly per spawn.
- [ ] **W8.4** **C4.2** — pre-pull the release digest at deployment time and refuse to start when it is absent and cannot be fetched, so the failure surfaces at boot rather than at first tier-B turn.
- [ ] **W8.5** Confirm the spawn path (`:1841`) consumes the cached digest and that `docker run` and the `sandbox.runtime` trace `"image"` attribute both carry it — the traced value must remain the digest actually executed.
- [ ] **W8.6** Re-confirm the fail-closed error at `:1499` is untouched and its message still names the tag and the remedy (D43).
- [ ] **W8.7** Add the Amendment to spec 08; un-xfail W6.4–W6.7; `make lint typecheck`; commit + push — *(suggested: `fix(sandbox): resolve the image digest once and cache it`)*.

**Acceptance:** W6.4–W6.7 green; W6.8 still green; N spawns produce exactly one pull; a locally present digest-pinned image spawns with **zero** pulls; `make ci-affected SEVN_CI_BASE=HEAD` green.

### Batch B gates

- [ ] **B-Verify** (`wave-verifier`): **`make docker-build-ci` then `make verify-sandbox-spawn`** — paste `VERIFY_OVERALL:`. Runtime proof against the real Docker CLI: spawn N sandboxes and show exactly **one** `docker pull` in the daemon/CLI trace; spawn again with the image already local and show **zero**; delete the local image and show the cold-start pull still works; remove the release digest and show startup **refuses** (C4.2); confirm the locally-built-image fail-closed error from the predecessor program still fires (D43).
- [ ] **B-Final:** xfail sweep (0 xfails); `graphify update .`; **drift sweep in one commit** (D7) covering the sandbox/security readme fingerprints and `make about-docs-extract DOC_ID=spec-08-sandbox`; CHANGELOG entries for C4.\* and C5.\*; `make ci-resume SEVN_CI_BASE=origin/pre-0.0.1` until all steps pass.
- [ ] **B-Thermos:** thermo-nuclear review; **clean including `low`** (D31); **blocks the PR**. Pay specific attention to whether the cache can serve a stale digest across an operator config change. **Record the base SHA** to `.ignorelocal/waves/prod-ready-b-thermos-base.sha` and **declare every file the review changed** (D29).
- [ ] **B-Reverify** (**fresh `wave-verifier`**): convention-11 detection with `<batch>` = `b`. Any Thermos edit inside `sandbox_runtime.py` re-invalidates every spawn proof — re-run the B-Verify runtime proofs in full, re-confirm `tests/sandbox/test_post_audit_image_pin_w4_red.py` is green **and unmodified**, and run `make ci-affected SEVN_CI_BASE="$BASE"`. Hand findings back (D4). **Blocks B-PR** (D29, D30).
- [ ] **B-PR:** open against `pre-0.0.1`, listing C4.1, C4.2, C4.3, C5.1, C5.2, C5.3, C5.4 one per line.

---

# Batch C — Release pipeline & supply chain

**Branch:** `wave/prod-ready-c-supply-chain` · **Worktree:** `../sevn-pr-c-supply-chain` · **Closes:** C2.1, C2.2, C11.1, C11.2, C11.3, C12.3, C13.1, C13.2
**Independent of A, B, D, E, F.** W10, W11 and W12 all edit `.github/workflows/ci-cd.yml` — **run them serially** in this worktree.
**Hard constraint:** `C2.3`, `C12.1`, `C12.2` and `C12.4` are landed. `trivy --exit-code 1` before `cosign sign`, `draft: true`, and the tag-build phase4/5 requirement must survive every edit in this batch.

## Wave W9 — RED suite (`test-creator`)

**Spec/PRD:** `about-sevn.bot/specs/25-cicd-full.md` (Workflow matrix, Behavior, Failure Modes)

- [ ] **W9.1** Assert the required aggregator's **job name** no longer implies deployment readiness (`.github/workflows/ci-cd.yml:372`, currently "Delivery chain gate (required)") (**xfail → W10**, C2.1). New `tests/infra/test_prod_ready_release_pipeline_w9_red.py`.
- [ ] **W9.2** Assert `needs_impl_ok` and the `phase2`/`phase3` jobs are **absent** from the workflow (**xfail → W10**, D44).
- [ ] **W9.3** Assert **no `:latest` tag is written on a `main` push** (**xfail → W11**, C13.1) — today five images publish it at `:118`, `:132`, `:146`, `:161`, `:176`.
- [ ] **W9.4** Assert the publish steps push to a **quarantine tag only**, and that stable tags are promoted **by digest** after the scan (**xfail → W11**, C12.3, D45).
- [ ] **W9.5** Assert **no `curl … | sh` pattern** exists under `.github/` or in the `Makefile` (**xfail → W12**, C11.3) — today `ci-cd.yml:198`, `:202`, `Makefile:48`.
- [ ] **W9.6** Assert syft and trivy install via SHA-pinned actions or checksum-verified downloads, and that the `uv` installer is version-pinned and verified (**xfail → W12**, C11.1, C11.2).
- [ ] **W9.7** **Guard tests:** assert the landed contracts still hold — `draft: true` (`:360`), phase6 `needs` includes `phase4` and `phase5` (`:339`), `trivy --exit-code 1` (`:230`) precedes `cosign sign` (`:235`), and SBOM artifact upload survives. Extend `tests/infra/test_post_audit_release_gate_w9_red.py` coverage rather than duplicating it where possible.
- [ ] **W9.8** Author `docs/test-plans/prod-ready-batch-c.md`; `make lint typecheck`; commit + push.

**Acceptance:** suite collects; W9.1–W9.6 xfail with wave markers; W9.7 passes on the batch base; `make ci-affected SEVN_CI_BASE=HEAD` green.

## Wave W10 — Aggregator honesty; delete the tolerated stubs (C2.1, C2.2, D44)

**Spec/PRD:** `about-sevn.bot/specs/25-cicd-full.md` (**live prose** — Workflow matrix, Behavior, Failure Modes) · `about-sevn.bot/prd/06-setup-and-operations.md`
**Files:** `.github/workflows/ci-cd.yml`

- [ ] **W10.1** **C2.1** — rename the aggregator job (`:371-372`) so a green check states what it proves: artifact publication, not delivery. The workflow header (`:40`) is already renamed; the required check name is what reviewers and branch protection read.
- [ ] **W10.2** **C2.2** — delete the `phase2` (`:251-274`) and `phase3` (`:276-288`) jobs together with `needs_impl_ok` (`:400`) and `require_needs_impl` (`:411-418`) (D44). A required check that classifies `failure` as OK is the exact P3 pattern the repository's own rules forbid — and it currently still applies on `main` pushes even after the tag-build fix.
- [ ] **W10.3** Keep `phase4`/`phase5` as documented stubs — `C2.3` already makes a tag build require their success (`:339`) — and make sure removing `needs_impl_ok` does not accidentally make a `main` push require them. State the resulting matrix explicitly in a workflow comment.
- [ ] **W10.4** Update the branch-protection expectations wherever the old required check name is recorded, so the rename does not silently drop a required gate. Record where that lives.
- [ ] **W10.5** Update `about-sevn.bot/specs/25-cicd-full.md` Workflow matrix, Behavior and Failure Modes in place (D53): what a `main` push produces, what a tag build produces, and that Dev deploy/smoke is unimplemented and no longer pretended.
- [ ] **W10.6** Un-xfail W9.1/W9.2; `make lint typecheck`; commit + push — *(suggested: `fix(ci): name the publication gate honestly and drop tolerated stubs`)*.

**Acceptance:** W9.1/W9.2 green; W9.7 still green; no workflow path classifies `failure` as acceptable in a required check; `make ci-affected SEVN_CI_BASE=HEAD` green.

## Wave W11 — Quarantine, scan, promote by digest (C13.1, C13.2, C12.3, D45)

**Spec/PRD:** `about-sevn.bot/specs/25-cicd-full.md` (live prose) · `about-sevn.bot/prd/06-setup-and-operations.md`
**Files:** `.github/workflows/ci-cd.yml`, `docker/README.md`, `infra/sevn.schema.json` or the image constant from Batch B

- [ ] **W11.1** Rework the five publish steps (`:105-176`) to push a **quarantine tag only** (e.g. `…/sandbox:quarantine-${{ github.sha }}`), so nothing consumable exists before the scan runs.
- [ ] **W11.2** Promote to the SHA tag **by digest** after `container-supply-chain` passes, keeping the landed scan→sign order (`:230` → `:235`) intact.
- [ ] **W11.3** **C13.1** — stop writing `latest` from `main` (`:118`, `:132`, `:146`, `:161`, `:176`). Promote `latest` only behind a real deploy+test gate; while phases 4/5 are stubs, that means **`latest` is not written at all** from `main`.
- [ ] **W11.4** **C13.2** — document that any pre-existing `latest` is unverified, and make the operator default a **pinned digest**. Coordinate with Batch B's constant (D42): if B has merged, reference it; if not, record the coupling in the wave notes and in `docker/README.md` — do not create a second source of truth.
- [ ] **W11.5** Add a quarantine cleanup step so failed builds do not accumulate tags indefinitely.
- [ ] **W11.6** Update `25-cicd-full.md` §3.2 Artefacts in place for the new tag lifecycle (D53); un-xfail W9.3/W9.4; `make lint typecheck`; commit + push — *(suggested: `fix(ci): quarantine images until scanned, then promote by digest`)*.

**Acceptance:** W9.3/W9.4 green; W9.7 still green; a simulated failing scan leaves **no** consumable tag; `make ci-affected SEVN_CI_BASE=HEAD` green.

## Wave W12 — Verified installers (C11.1, C11.2, C11.3, D46, D47)

**Spec/PRD:** `about-sevn.bot/specs/25-cicd-full.md` (live prose)
**Files:** `.github/workflows/ci-cd.yml`, `Makefile`, a new grep gate + its `ci-*` tier wiring

- [ ] **W12.1** **C11.1** — replace the syft (`:198`) and trivy (`:202`) `curl … | sh` installers with SHA-pinned actions (D46 — `cosign` at `:189-190` is the in-repo pattern), or download release binaries and verify published checksums/signatures before execution. This job holds `packages: write`.
- [ ] **W12.2** **C11.2** — pin the `uv` installer at `Makefile:48` to a version and verify its checksum before running it (D47). `make setup` runs on machines holding operator credentials; "accepted developer risk" is rejected.
- [ ] **W12.3** **C11.3** — add a CI gate rejecting new `curl … | sh` (and `wget … | sh`) patterns under `.github/` and the `Makefile`, wired into a `ci-*` tier with `tests/infra/test_ci_steps_tier_parity.py` kept green (Global convention 9).
- [ ] **W12.4** Confirm the pinned versions match what the pipeline expects (syft `v1.18.1`, trivy `v0.58.1` today) and that the trivy allowlist tooling from the predecessor program (`scripts/trivy_ignore_args.py`, `security/trivy-allowlist.toml`) still functions against the new install path.
- [ ] **W12.5** Update `25-cicd-full.md` in place (D53); un-xfail W9.5/W9.6; `make lint typecheck`; commit + push — *(suggested: `fix(ci): pin and verify release tooling installers`)*.

**Acceptance:** W9.5/W9.6 green; W9.7 still green; the grep gate fails on a deliberately reintroduced `curl | sh`; tier parity green; `make ci-affected SEVN_CI_BASE=HEAD` green.

### Batch C gates

- [ ] **C-Verify** (`wave-verifier`): static proofs — walk the tag-build DAG and re-prove phase6 cannot publish a non-draft release while phase4/5 fail (landed `C2.3`); walk a `main`-push DAG and prove no `latest` and no consumable tag before the scan; prove a failing trivy blocks promotion **and** signing; run the grep gate against a deliberately reintroduced `curl | sh`; run `scripts/trivy_ignore_args.py` against a seeded and an expired allowlist; `actionlint` or the existing workflow smoke; `make ci-affected SEVN_CI_BASE=origin/pre-0.0.1`. Gate record: `.ignorelocal/waves/prod-ready-c-verify.md`.
- [ ] **C-Final:** xfail sweep (0 xfails); `graphify update .`; **drift sweep in one commit** (D7) including `make about-docs-extract DOC_ID=spec-25-cicd-full`; CHANGELOG entries for C2.\*, C11.\*, C12.3, C13.\*; `make ci-resume SEVN_CI_BASE=origin/pre-0.0.1` until all steps pass.
- [ ] **C-Thermos:** thermo-nuclear review; **clean including `low`** (D31); **blocks the PR**. **This is the highest-risk Thermos in the program**: in the predecessor program a reviewer-authored commit to this exact file (`905012ec`) made the required gate tolerate `failure` and nullified the batch's own deliverable. Treat any reviewer-introduced `advisory` / `exit-code 0` / `for now` annotation as `changes_required` regardless of stated intent (P3). **Record the base SHA** to `.ignorelocal/waves/prod-ready-c-thermos-base.sha` and **declare every file the review changed** (D29).
- [ ] **C-Reverify** (**fresh `wave-verifier`**): convention-11 detection with `<batch>` = `c`. If Thermos touched the workflow or Makefile CI targets at all, re-run **every** C-Verify proof against the post-Thermos tree, and re-confirm all four landed `C2.3`/`C12.*` contracts. Hand findings back (D4). **Blocks C-PR** (D29, D30).
- [ ] **C-PR:** open against `pre-0.0.1`, listing C2.1, C2.2, C11.1, C11.2, C11.3, C12.3, C13.1, C13.2 one per line.

---

# Batch D — Container isolation & operator runtime

**Branch:** `wave/prod-ready-d-isolation` · **Worktree:** `../sevn-pr-d-isolation` · **Closes:** C8.1–C8.4, C9.1–C9.4, C10.1–C10.3
**Independent of B, C, E, F** — but **W15 and W16 wait on merged Batch A** (D35), because A restructures `docker/docker-compose.yml` env and adds the bootstrap service.
**W13 is a prerequisite, not just a RED wave** (D48): it unpins the full-tree `find` before W15 changes it.

## Wave W13 — RED suite + test prerequisite (`test-creator`, C9.3, D48)

**Spec/PRD:** `about-sevn.bot/specs/09-security-scanner.md` · `25-cicd-full.md`

- [x] **W13.1** **C9.3** — update `tests/infra/test_post_audit_compose_w1_red.py`, which pins the full-tree `find /operator ! -user 10001 …` form, to assert the **new** contract: scoped directories plus a versioned marker. This must land **before** W15 (D48). *(2026-08-06 ✅: c55078d5 — xfail-until-W15)*
- [x] **W13.2** Assert **no compose file or overlay** passes `--no-sandbox` (**xfail → W14**, C8.1) — today `docker/docker-compose.prod.yml:19`. Extend the existing Dockerfile-scoped guard (`tests/infra/test_release_audit_containers_w7_red.py:68-71`), which does not inspect overlays. *(2026-08-06 ✅: a5d7bba6 — un-xfailed)*
- [x] **W13.3** Assert the stale `--no-sandbox` comments are gone from `docker/docker-compose.browser.yml:13` and `docker/docker-compose.gui.yml:13` (**xfail → W14**, C8.2). *(2026-08-06 ✅: a5d7bba6)*
- [x] **W13.4** Assert the site-isolation decision is recorded — either `--disable-features=IsolateOrigins,site-per-process` is gone from the login-grade args or a documented justification exists (**xfail → W14**, C8.4). *(2026-08-06 ✅: a5d7bba6)*
- [ ] **W13.5** Assert the permissions init writes a **versioned marker** and skips the broad migration when present (**xfail → W15**, C9.2), and that `docker/docker-compose.ci.yml:20` no longer runs an unconditional `chown -R` (**xfail → W15**, C9.4). *(impl XPASS; un-xfail → test-creator)*
- [ ] **W13.6** Assert a documented **minimum Docker Compose version** exists and is enforced (**xfail → W16**, C10.1).
- [ ] **W13.7** Assert an integration check reads the created container's `HostConfig` and requires non-zero `NanoCpus`, `Memory` and `PidsLimit` matching the declared values (**xfail → W16**, C10.2). Mark it so it skips cleanly without a Docker daemon.
- [ ] **W13.8** Assert every resolved file set (base, browser, GUI, CI) yields limits for every service (**xfail → W16**, C10.3) — assert on `docker compose config` output, not on raw YAML, per finding 5 and D49.
- [ ] **W13.9** Assert the browser runs as its own service with no `sevn-state` mount and no `SEVN_GATEWAY_TOKEN` (**xfail → W17**, C8.3).
- [x] **W13.10** Author `docs/test-plans/prod-ready-batch-d.md`; `make lint typecheck`; commit + push. *(2026-08-06 ✅: c55078d5)*

**Acceptance:** W13.1 lands green against the *current* compose command **or** is explicitly staged as xfail-until-W15 — record which; W13.2–W13.9 xfail with wave markers; `make ci-affected SEVN_CI_BASE=HEAD` green.

## Wave W14 — Browser flags and stale claims (C8.1, C8.2, C8.4)

**Spec/PRD:** `about-sevn.bot/specs/09-security-scanner.md` (Amendment)
**Files:** `docker/docker-compose.prod.yml`, `docker/docker-compose.browser.yml`, `docker/docker-compose.gui.yml`, `src/sevn/browser/chrome.py`, `docs/readmes/security.md`

- [x] **W14.1** **C8.1** — remove `--no-sandbox` from `docker/docker-compose.prod.yml:19`. The flag is absent from dev and present in **prod** today, which is the inverse of a safe default. Confirm the prod browser/GUI stack still starts without it; if it cannot, record the blocking reason and the alternative rather than restoring the flag silently. *(2026-08-06 ✅: 72e790da)*
- [x] **W14.2** Extend the guard to **every compose file and overlay**, not just Dockerfiles — the existing test inspects the image, which is why the overlay escaped. *(2026-08-06 ✅: 72e790da)*
- [x] **W14.3** **C8.2** — delete the stale `--no-sandbox` comments at `docker/docker-compose.browser.yml:13` and `docker/docker-compose.gui.yml:13`; both now say Brave runs with a flag the file does not set. *(2026-08-06 ✅: 72e790da)*
- [x] **W14.4** **C8.4** — re-justify or drop `--disable-features=IsolateOrigins,site-per-process` from the login-grade Chrome args (`src/sevn/browser/chrome.py`). If it stays for a login-grade session, document the threat model and confirm it is **not** applied to untrusted browsing. *(2026-08-06 ✅: 72e790da)*
- [x] **W14.5** Document in `docs/readmes/security.md` that container hardening (`cap_drop: ALL`, `no-new-privileges`) does **not** substitute for the renderer sandbox; add the Amendment to spec 09 (D53). *(2026-08-06 ✅: 72e790da)*
- [x] **W14.6** Un-xfail W13.2–W13.4; `make lint typecheck`; commit + push — *(suggested: `fix(compose): stop disabling the browser sandbox in production`)*. *(2026-08-06 ✅: a5d7bba6)*

**Acceptance:** W13.2–W13.4 green; no compose file or overlay passes `--no-sandbox`; `make ci-affected SEVN_CI_BASE=HEAD` green.

## Wave W15 — Scoped permissions init (C9.1, C9.2, C9.4, D35, D48)

**Spec/PRD:** `about-sevn.bot/prd/06-setup-and-operations.md`
**Files:** `docker/docker-compose.yml`, `docker/docker-compose.ci.yml`, `docker/README.md`

- [x] **W15.1** **D35 gate — do this after Batch A merges.** `git fetch origin && git rebase origin/pre-0.0.1`. If A has not merged, **stop here and report** — do not restructure the file, and in particular do not collide with A's bootstrap init service (W4.1). *(2026-08-06 ✅: based on c62301d6 / #237)*
- [x] **W15.2** **C9.1** — replace the full-tree `find /operator ! -user 10001 …` (`docker/docker-compose.yml:60-61`) with chown over the **known application-owned directories** only. Stop walking operator data. Keep `/browser-profiles` (`:62`) equivalently scoped.
- [x] **W15.3** **C9.2** — write a versioned init marker (e.g. `/operator/.sevn/perms-v1`) and run the broad migration **only** when the marker is absent or stale. Note that `restart: "no"` means the init re-runs on every fresh `up`, which is exactly why the marker matters.
- [x] **W15.4** **C9.4** — apply the same treatment to `sevn-ci-init` (`docker/docker-compose.ci.yml:20`), which still runs the unconditional `chown -R 10001:10001 /operator` the base file abandoned, **or** document why CI diverges. Divergence that nobody chose is the defect.
- [x] **W15.5** Coordinate with A's bootstrap service (W4.1): the generated secret file must be owned correctly by whichever init runs first. Record the ordering. *(same service: generate → always chown secret → marker-gated scoped migration)*
- [x] **W15.6** Update `docker/README.md`; un-xfail W13.5; `make lint typecheck`; commit + push — *(suggested: `fix(compose): scope the permissions init and gate it on a marker`)*. *(README done; un-xfail → test-creator — contracts XPASS)*

**Acceptance:** W13.1 and W13.5 green; a pre-owned volume completes the init in well under the 5s `SEVN_VERIFY_PERMS_MAX_S` budget with no full-tree walk; a fresh volume still yields a healthy stack; `make ci-affected SEVN_CI_BASE=HEAD` green. *(impl green/XPASS; un-xfail pending test-creator)*

## Wave W16 — Enforced, documented resource limits (C10.1, C10.2, C10.3, D49)

**Spec/PRD:** `about-sevn.bot/specs/25-cicd-full.md` (live prose) · `about-sevn.bot/prd/06-setup-and-operations.md`
**Files:** `docker/README.md`, `README.md`, `Makefile`, compose files as required by W0.7

- [x] **W16.1** **C10.1** — pin and document a minimum Docker Compose version, and enforce it in the preflight path (`scripts/check-compose-default.sh` or the W5 sibling). `deploy.resources` is honoured by `docker compose` v2 but not by every older `docker-compose`; today no minimum is documented anywhere. *(2026-08-06 ✅: floor 2.20 in docker/README + 25-cicd-full; enforced in check-compose-default.sh)*
- [x] **W16.2** **C10.3** — start from the W0.7 `docker compose … config` capture (D49). Add `deploy.resources.limits` and `pids_limit` **only** where the *resolved* configuration lacks them. `docker/docker-compose.ci.yml` is the known gap; the browser and GUI overrides are expected to inherit through the base `sevn-gateway` service and must be verified, not assumed. *(2026-08-06 ✅: CI + sevn-operator-perms; browser/GUI inherit verified)*
- [x] **W16.3** **C10.2** — add an integration check that creates the containers and reads `HostConfig`, asserting `NanoCpus`, `Memory` and `PidsLimit` are non-zero **and match the declared values**. Today no test or workflow inspects runtime enforcement — only YAML. *(2026-08-06 ✅: W13.7 RED + verify-stack-health HostConfig inspect)*
- [x] **W16.4** Wire the check into a `ci-*` tier or the `verify-*` driver family (coordinate with F/W23 so it is not wired twice), keeping `tests/infra/test_ci_steps_tier_parity.py` green. *(2026-08-06 ✅: drive_stack_health + check-compose-default resolved-limits; no new CI_STEPS)*
- [x] **W16.5** Update `docker/README.md` and `25-cicd-full.md` in place (D53); un-xfail W13.6–W13.8; `make lint typecheck`; commit + push — *(suggested: `fix(compose): prove resource limits are enforced at runtime`)*. *(docs done; un-xfail → test-creator — contracts XPASS)*

**Acceptance:** W13.6–W13.8 green; the `HostConfig` check fails when a limit is removed from YAML; every resolved file set declares limits for every service; `make ci-affected SEVN_CI_BASE=HEAD` green. *(impl XPASS; un-xfail pending test-creator)*

## Wave W17 — Browser as its own service (C8.3, D50)

**Spec/PRD:** `about-sevn.bot/specs/09-security-scanner.md` (Amendment)
**Files:** `docker/docker-compose.browser.yml`, `docker/docker-compose.gui.yml`, `docker/Dockerfile.gateway.browser`, `docker/Dockerfile.gateway.gui`, `src/sevn/browser/`

- [ ] **W17.1** Split the browser out of the gateway container into its own service with a **narrow authenticated control protocol**. Today Brave is spawned as a subprocess inside the gateway container, so it shares the gateway's entire process and mount namespace.
- [ ] **W17.2** Stop mounting `sevn-state:/operator` into the browser service — it currently exposes the workspace, logs and `traces.db` to the browser process.
- [ ] **W17.3** Stop passing `SEVN_GATEWAY_TOKEN` into the browser service; the control protocol carries its own credential with browser-only authority.
- [ ] **W17.4** Apply the batch's hardening and limits to the new service, and confirm the W16 `HostConfig` check covers it.
- [x] **W17.5** **D50 escape hatch:** if this wave cannot complete without destabilising the batch, **stop, record the state, and move it to its own follow-up PR** against `pre-0.0.1`. C8.1/C8.2/C8.4 and all of C9/C10 must not be held hostage to it. *(2026-08-06 ✅: deferred — https://github.com/sevn-bot/sevn/issues/240; tip `85893705`; W13.9 remains xfail)*
- [ ] **W17.6** Add the Amendment to spec 09; un-xfail W13.9; `make lint typecheck`; commit + push — *(suggested: `fix(browser): run the browser as its own minimally-privileged service`)*. *(N/A under D50 — tracked in #240)*

**Acceptance:** W13.9 green **or** the D50 deferral recorded with a follow-up issue; browser skills still function against the split service; `make ci-affected SEVN_CI_BASE=HEAD` green. *(2026-08-06 ✅: D50 path — #240)*

### Batch D gates

- [x] **D-Verify** (`wave-verifier`): **`make verify-compose-profiles`** and **`make verify-stack-health`** on a clean `sevn-state` volume — paste each `VERIFY_OVERALL:`. Runtime proof: `docker inspect` each running container and show `NanoCpus`, `Memory`, `PidsLimit` non-zero and matching (C10.2); show the perms init skipping a pre-owned volume via the marker and completing in well under budget; bring up the prod overlay and show **no** `--no-sandbox` in the browser process args; if W17 landed, show the browser service without a `sevn-state` mount and without `SEVN_GATEWAY_TOKEN`. *(2026-08-06 ✅: `9f369788` — VERIFY_OVERALL pass for both drivers; HostConfig NanoCpus=1e9/2e9, Memory=536870912/2147483648, PidsLimit=256/256 match declared limits; perms init 0.1s vs 5.0s budget; marker skip proven by manual repro; prod-overlay `SEVN_BROWSER_EXTRA_ARGS: --disable-dev-shm-usage` only; W17 deferred to #240, W13.9 still xfail; gate record `.ignorelocal/waves/prod-ready-d-verify.md`)*
- [x] **D-Final:** xfail sweep (0 xfails); `graphify update .`; **drift sweep in one commit** (D7) covering `docs/readmes/security.md` and `make about-docs-extract` for specs 09 and 25; CHANGELOG entries for C8.\*, C9.\*, C10.\*; `make ci-resume SEVN_CI_BASE=origin/pre-0.0.1` until all steps pass. *(2026-08-07 ✅: `fe4b7c14` — xfail sweep 0/141; graphify AST clean; D7 drift 2 specs; 10/10 C-IDs cited; 41/41 ci-resume steps green on iter 6; spec-kit-wave W1 RED ignores applied; force-push confirmed; gate record `.ignorelocal/waves/prod-ready-d-final.md`)*
- [x] **D-Thermos:** thermo-nuclear review; **clean including `low`** (D31); **blocks the PR**. Pay specific attention to any hardening removed "to make the stack boot". **Record the base SHA** to `.ignorelocal/waves/prod-ready-d-thermos-base.sha` and **declare every file the review changed** (D29). *(2026-08-07 ✅: `9ccb75c6` — clean including low; reviewed 16 product files; P2/P3/P5 clean; D30 confirmed; gate record `.ignorelocal/waves/prod-ready-d-thermos.md`)*
- [x] **D-Reverify** (**fresh `wave-verifier`**): convention-11 detection with `<batch>` = `d`. `docker/docker-compose.yml` and `scripts/check-compose-default.sh` are the two files a reviewer rewrote last time in the predecessor program (`53eff5d7`) — a Thermos edit to either invalidates every D-Verify invocation proof. Re-run the D-Verify proofs in full plus `make ci-affected SEVN_CI_BASE="$BASE"`. Hand findings back (D4). **Blocks D-PR** (D29, D30). *(2026-08-07 ✅: `636aa69c` — fresh verifier per D30; all 5 proofs re-confirmed; P2/P3/P5 clean; gate record `.ignorelocal/waves/prod-ready-d-reverify.md`)*
- [ ] **D-PR:** open against `pre-0.0.1`, listing C8.1, C8.2, C8.3, C8.4, C9.1, C9.2, C9.3, C9.4, C10.1, C10.2, C10.3 one per line (or C8.3 as a recorded follow-up per D50).

---

# Batch E — Scoped egress authority

**Branch:** `wave/prod-ready-e-egress-scope` · **Worktree:** `../sevn-pr-e-egress-scope` · **Closes:** C7.1, C7.2, C7.3, C7.4
**Independent of B, C, D, F** — but **W19 waits on merged Batch A** (D36), because A changes how the signing secret is resolved.
**Scoped to the remainder of C7.1** — signature, `exp` and route-family scope are landed (`src/sevn/proxy/auth.py:133`, `:171`, `:274-280`).

## Wave W18 — RED suite (`test-creator`)

**Spec/PRD:** `about-sevn.bot/specs/07-egress-proxy.md` · `08-sandbox.md`

- [ ] **W18.1** Assert a minted session token carries a **`run_id`** claim and that a token minted for run A is rejected on a request from run B (**xfail → W19**, C7.1).
- [ ] **W18.2** Assert the token is **bound to the spawning container**, and that presenting it from a different container is rejected (**xfail → W19**, C7.1).
- [ ] **W18.3** **C7.2** — assert the **service shared secret is rejected** on sandbox-originated route families while still accepted on gateway→proxy families (**xfail → W19**, D51). Today `auth.py:272-273` accepts it everywhere, so a sandbox with the secret has gateway authority.
- [ ] **W18.4** Assert a destination allowlist is enforced proxy-side: an in-allowlist destination succeeds, an out-of-allowlist destination is rejected (**xfail → W20**, C7.3).
- [ ] **W18.5** Assert per-run **request-count** and **byte** budgets are enforced proxy-side and that exceeding either is rejected with a distinguishable error (**xfail → W20**, C7.3).
- [ ] **W18.6** Assert `infra/sevn.schema.json` no longer describes unimplemented token behaviour as current (**xfail → W20**, C7.4) — the `SEVN_SESSION_TOKEN` entry at `:190-193` claims proxy minting, a frozen `PermissionConfig` ceiling, and revoke-on-teardown semantics.
- [ ] **W18.7** **Guard tests:** assert the landed session-token contract stays green — signature, expiry and route-family scope rejects (`tests/proxy/`), and that `build_sandbox_child_env` still excludes the service secret.
- [ ] **W18.8** Author `docs/test-plans/prod-ready-batch-e.md`; `make lint typecheck`; commit + push.

**Acceptance:** suite collects; W18.1–W18.6 xfail with wave markers; W18.7 passes on the batch base; `make ci-affected SEVN_CI_BASE=HEAD` green.

## Wave W19 — Run-bound tokens and differentiated authority (C7.1, C7.2, D36, D51)

**Spec/PRD:** `about-sevn.bot/specs/07-egress-proxy.md` · `08-sandbox.md` (Amendments) · `about-sevn.bot/prd/03-trust-and-control.md`
**Files:** `src/sevn/proxy/auth.py`, `src/sevn/security/sandbox_runtime.py`, `src/sevn/tools/runtime_bindings_factory.py`

- [ ] **W19.1** **D36 gate — do this first.** `git fetch origin && git rebase origin/pre-0.0.1` onto merged Batch A. If A has not merged, **stop and report** — the token is signed with the shared secret whose resolution A is changing.
- [ ] **W19.2** **C7.1** — add a **`run_id`** claim to the minted token payload and validate it. `run_id` exists today only as a Docker label on the sandbox container; it must become part of the credential.
- [ ] **W19.3** Bind the token to the **spawning container** so a token lifted from one sandbox cannot be replayed from another. Record the binding mechanism and its failure mode.
- [ ] **W19.4** **C7.2** — reject the service shared secret on sandbox-originated route families (D51). `auth.py:272-273` currently returns `None` (allow) for any caller presenting it, which is why sandbox and gateway authority are identical today. Keep the service secret authoritative for gateway→proxy families.
- [ ] **W19.5** Confirm the sandbox child-env contract still excludes the service secret and now carries the run-bound session token; keep the contract fixture green.
- [ ] **W19.6** Add the Amendments to specs 07 and 08 describing the run-bound two-credential model (D53); un-xfail W18.1–W18.3; `make lint typecheck`; commit + push — *(suggested: `fix(proxy): bind sandbox egress tokens to a run and a container`)*.

**Acceptance:** W18.1–W18.3 green; W18.7 still green; a sandbox presenting the service secret is **rejected**; `make ci-affected SEVN_CI_BASE=HEAD` green.

## Wave W20 — Budgets, allowlist, and an honest schema (C7.3, C7.4)

**Spec/PRD:** `about-sevn.bot/specs/07-egress-proxy.md` (Amendment) · `about-sevn.bot/prd/05-cost-and-providers.md`
**Files:** `src/sevn/proxy/`, `infra/sevn.schema.json`

- [ ] **W20.1** **C7.3** — add a **destination allowlist** to the token payload, enforced proxy-side before the request is forwarded.
- [ ] **W20.2** Add **per-run request-count and byte budgets** to the token, enforced proxy-side, with a distinguishable rejection so a budget exhaustion is not mistaken for an auth failure.
- [ ] **W20.3** Decide and record where budget state lives and what happens on proxy restart — a budget that resets silently is not a budget. State the tradeoff explicitly.
- [ ] **W20.4** **C7.4** — correct `infra/sevn.schema.json:190-193` so the `SEVN_SESSION_TOKEN` description stops presenting unimplemented behaviour (proxy minting, frozen `PermissionConfig` ceiling, revoke-on-teardown) as current. Describe what ships after W19/W20 and mark the rest as intent. Run **`make config-schema`**.
- [ ] **W20.5** Add the Amendment to spec 07 (D53); un-xfail W18.4–W18.6; `make lint typecheck`; commit + push — *(suggested: `fix(proxy): enforce destination allowlists and per-run budgets`)*.

**Acceptance:** W18.4–W18.6 green; W18.7 still green; an out-of-allowlist destination and an exhausted budget are each rejected distinguishably; `make config-schema` clean; `make ci-affected SEVN_CI_BASE=HEAD` green.

### Batch E gates

- [ ] **E-Verify** (`wave-verifier`): **`make verify-runtime`** — paste `VERIFY_OVERALL:`. Runtime proof against a real proxy: a run-bound token accepted for its own run and **rejected** for another; the same token replayed from a different container rejected; the **service secret rejected** on a sandbox family and accepted on a gateway family; an out-of-allowlist destination rejected; a budget exhausted and the rejection distinguishable from a 401. Confirm the landed expiry/scope rejects still fire.
- [ ] **E-Final:** xfail sweep (0 xfails); `graphify update .`; **drift sweep in one commit** (D7) covering `docs/readmes/proxy-egress.md` and `security.md` fingerprints plus `make about-docs-extract` for specs 07 and 08; CHANGELOG entries for C7.\*; `make ci-resume SEVN_CI_BASE=origin/pre-0.0.1` until all steps pass.
- [ ] **E-Thermos:** thermo-nuclear review; **clean including `low`** (D31); **blocks the PR**. Pay specific attention to whether the new checks can be bypassed by header casing, route-prefix tricks, or a missing claim treated as "not applicable". **Record the base SHA** to `.ignorelocal/waves/prod-ready-e-thermos-base.sha` and **declare every file the review changed** (D29).
- [ ] **E-Reverify** (**fresh `wave-verifier`**): convention-11 detection with `<batch>` = `e`. Any Thermos edit inside `src/sevn/proxy/auth.py` is a **credential surface authored without a RED test**: confirm a test fails if the service-secret rejection is deleted (P4a) before passing the gate, re-run every E-Verify runtime proof, and run `make ci-affected SEVN_CI_BASE="$BASE"`. Hand findings back (D4). **Blocks E-PR** (D29, D30).
- [ ] **E-PR:** open against `pre-0.0.1`, listing C7.1, C7.2, C7.3, C7.4 one per line.

---

# Batch F — Dashboard residuals & dynamic evidence

**Branch:** `wave/prod-ready-f-evidence` · **Worktree:** `../sevn-pr-f-evidence` · **Closes:** C6.2, C6.4, C14.1, C14.2, C14.3
**Independent of A, B, C, D, E** — but **W23 lands last in the program** (D54) so the evidence job is wired against a fixed stack rather than a red one.

## Wave W21 — RED suite (`test-creator`)

**Spec/PRD:** `about-sevn.bot/specs/24-dashboard.md` · `19-channel-webui.md` · `25-cicd-full.md`

- [ ] **W21.1** Assert `local_open_trust_address` is **refused** whenever a tunnel or a reverse proxy is configured, even when the key is `true` (**xfail → W22**, C6.2).
- [ ] **W21.2** Assert a **boot warning** is logged when the trust-address escape is enabled (**xfail → W22**, C6.2), mirroring the `SEVN_PROXY_ALLOW_UNAUTHENTICATED` boot warning pattern already in `src/sevn/proxy/auth.py:76`.
- [ ] **W21.3** Assert the CLI no longer prints `"loopback access — no login required"` (`src/sevn/cli/commands/dashboard_cmd.py:190`) when a token **is** required (**xfail → W22**, C6.4).
- [ ] **W21.4** **Guard test:** assert the landed `C6.1`/`C6.3` contract stays green — tokenless direct loopback is denied and the existing dashboard auth suites pass unmodified.
- [ ] **W21.5** Assert a workflow runs `make verify-deployment`, on the daily cron **and** on `refs/tags/v*` (**xfail → W23**, C14.1).
- [ ] **W21.6** Assert exit code **2 (`driver_unavailable`) is a failure on the tag path** and tolerated on the cron (**xfail → W23**, D52).
- [ ] **W21.7** Assert the new drivers exist and are registered in `DRIVERS` (`scripts/verify_deployment.py:954-958`): authenticated proxy round-trip, volume upgrade/migration, multi-arch browser/GUI boot, cancellation cleanup (**xfail → W23**, C14.2).
- [ ] **W21.8** Assert captured evidence is attached to the release (**xfail → W23**, C14.3).
- [ ] **W21.9** Author `docs/test-plans/prod-ready-batch-f.md`; `make lint typecheck`; commit + push.

**Acceptance:** suite collects; W21.1–W21.3 and W21.5–W21.8 xfail with wave markers; W21.4 passes on the batch base; `make ci-affected SEVN_CI_BASE=HEAD` green.

## Wave W22 — Guard the escape hatch (C6.2, C6.4)

**Spec/PRD:** `about-sevn.bot/specs/24-dashboard.md` · `19-channel-webui.md` · `02-config-and-workspace.md` (Amendments) · `about-sevn.bot/prd/03-trust-and-control.md`
**Files:** `src/sevn/ui/dashboard/services/auth.py`, `src/sevn/config/sections/dashboard.py`, `src/sevn/cli/commands/dashboard_cmd.py`, `infra/sevn.schema.json`, `docs/readmes/ui-mission-control.md`

- [ ] **W22.1** **C6.2** — refuse `local_open_trust_address` (`src/sevn/ui/dashboard/services/auth.py:289`) whenever a tunnel or reverse proxy is configured. The existing tunnel mitigation forces `local_open=false`; the escape hatch must be subject to the same rule, not an exception to it.
- [ ] **W22.2** Log a **loud boot warning** when the key is enabled, mirroring the proxy's unauthenticated-mode warning.
- [ ] **W22.3** Decide the naming question the source document raises: either rename the key so it reads as dangerous, or record why the current name plus the boot warning is sufficient. A rename is a **breaking config change** — if taken, gate it behind schema migration and call it out in the PR body. Record the decision either way.
- [ ] **W22.4** **C6.4** — fix `src/sevn/cli/commands/dashboard_cmd.py:190`, which still tells the operator "loopback access — no login required" although `C6.1` made a token mandatory. Describe the actual flow.
- [ ] **W22.5** Run **`make config-schema`**; update `docs/readmes/ui-mission-control.md`; add the Amendments to specs 24, 19 and 02 (D53).
- [ ] **W22.6** Un-xfail W21.1–W21.3; `make lint typecheck`; commit + push — *(suggested: `fix(dashboard): guard the local-open trust-address escape hatch`)*.

**Acceptance:** W21.1–W21.4 green; the escape hatch is refused under a configured tunnel; the CLI message matches reality; `make config-schema` clean; `make ci-affected SEVN_CI_BASE=HEAD` green.

## Wave W23 — Dynamic evidence in CI (C14.1, C14.2, C14.3, D52)

**Spec/PRD:** `about-sevn.bot/specs/25-cicd-full.md` (live prose) · `about-sevn.bot/prd/06-setup-and-operations.md`
**Files:** `scripts/verify_deployment.py`, `.github/workflows/ci-supplementary.yml`, `.github/workflows/ci-cd.yml`, `Makefile`

- [ ] **W23.1** **C14.1** — add a job running **`make verify-deployment`** on the daily cron in `ci-supplementary.yml` and on `refs/tags/v*` in `ci-cd.yml`. The harness is 1,000+ lines with four working drivers and **zero** workflow references today.
- [ ] **W23.2** **D52** — treat exit **2 (`driver_unavailable`) as a failure on the release path** and as tolerated on the cron. A release that cannot run its own verification has not been verified.
- [ ] **W23.3** **C14.2** — add drivers for the uncovered paths, registering each in `DRIVERS` (`scripts/verify_deployment.py:954-958`): **authenticated gateway→proxy round-trip** (the path Batch A fixes and nothing currently exercises), **volume upgrade/migration** from an existing operator volume, **multi-arch browser/GUI boot**, and **cancellation cleanup**.
- [ ] **W23.4** Add a driver or assertion for **sandbox-to-proxy scoped-token calls** once Batch E has merged; if E has not merged, record the gap and file it rather than asserting unimplemented behaviour.
- [ ] **W23.5** **C14.3** — attach captured evidence (`evidence/verify/`) to the release as an artifact, so "it works" is a downloadable artifact rather than an assertion in a PR body.
- [ ] **W23.6** Coordinate with D/W16.4 so the `HostConfig` limits check is wired **once**, not twice.
- [ ] **W23.7** Update `25-cicd-full.md` Workflow matrix and Failure Modes in place (D53); un-xfail W21.5–W21.8; `make lint typecheck`; commit + push — *(suggested: `fix(ci): run deployment verification on cron and release tags`)*.

**Acceptance:** W21.5–W21.8 green; the new drivers run and report `VERIFY_OVERALL:`; a simulated `driver_unavailable` fails a tag build and passes the cron; evidence is attached to a simulated release; `make ci-affected SEVN_CI_BASE=HEAD` green.

### Batch F gates

- [ ] **F-Verify** (`wave-verifier`): **`make verify-runtime`** and **`make verify-deployment`** — paste each `VERIFY_OVERALL:`. Runtime proof: with a tunnel configured, `local_open_trust_address: true` does **not** grant tokenless access; the boot warning appears; a normal `sevn dashboard` flow is not locked out; each new driver runs and reports. Confirm the landed `C6.1` denial still holds.
- [ ] **F-Final:** xfail sweep (0 xfails); `graphify update .`; **drift sweep in one commit** (D7) covering the `ui-mission-control` readme fingerprint and `make about-docs-extract` for specs 24/19/02/25; CHANGELOG entries for C6.2, C6.4 and C14.\* (flag any rename from W22.3 as **breaking**); `make ci-resume SEVN_CI_BASE=origin/pre-0.0.1` until all steps pass.
- [ ] **F-Thermos:** thermo-nuclear review; **clean including `low`** (D31); **blocks the PR**. Pay specific attention to a verification job that passes without actually running the drivers — a green job that skips is worse than no job. **Record the base SHA** to `.ignorelocal/waves/prod-ready-f-thermos-base.sha` and **declare every file the review changed** (D29).
- [ ] **F-Reverify** (**fresh `wave-verifier`**): convention-11 detection with `<batch>` = `f`. Any Thermos edit inside `src/sevn/ui/dashboard/services/auth.py` is an **auth surface authored without a RED test**: confirm a test fails if the trust-address refusal is deleted (P4a). Re-run the F-Verify proofs and `make ci-affected SEVN_CI_BASE="$BASE"`. Hand findings back (D4). **Blocks F-PR** (D29, D30).
- [ ] **F-PR:** open against `pre-0.0.1`, listing C6.2, C6.4, C14.1, C14.2, C14.3 one per line.

---

## Wave Z1 — Program close

- [ ] **Z1.1** Confirm all 42 open change IDs are closed by a merged PR; record the ID → PR mapping in this plan.
- [ ] **Z1.2** Refresh `.ignorelocal/waves/github-issues/index.md` with a **Prod-readiness 0.0.1** program row and its six PRs; append a sweep block dated to the close.
- [ ] **Z1.3** Re-run **`make verify-deployment`** on merged `pre-0.0.1` and record every `VERIFY_OVERALL:` line — this is the dynamic evidence finding #14 says does not exist, and its absence was a release blocker by evidence.
- [ ] **Z1.4** Re-assess the readiness table from the source document (§15) against the merged tree and record the new verdict per target, so the next audit starts from a validated position rather than a stale one.
- [ ] **Z1.5** Confirm `pre-0.0.1` is green on a full `make ci` (or CI) after the last merge — the batch checkpoints do not re-verify earlier steps.
- [ ] **Z1.6** Update this plan's status to **COMPLETE** with the PR table and per-batch merge SHAs.

**Acceptance:** 42/42 change IDs closed; index refreshed; `verify-deployment` evidence recorded; readiness table re-assessed; plan status COMPLETE; `pre-0.0.1` green.

---

## Success criteria (acceptance)

- [ ] A stock `docker compose up` on a clean volume serves **authenticated** LLM, web and integration traffic with no manual secret step — the W0.3 503 reproduction no longer reproduces (C1.2).
- [ ] `make compose-up` refuses to start on an empty, low-entropy, or `change-me` value for the proxy secret, the gateway token, or the secrets passphrase (C1.3).
- [ ] A misconfigured proxy secret surfaces as an **unhealthy container**, not as a runtime 503 at first use (C1.4).
- [ ] Exactly one configuration authority resolves `SEVN_PROXY_SHARED_SECRET`; no `os.environ` read and no `os.environ` write-back remain outside the documented sandbox child-env seam (C1.5, C3.1, C3.2).
- [ ] A guarded-route client with an empty resolved secret fails with a named, actionable error rather than an opaque 401 (C3.3).
- [ ] No mutable image tag literal survives in a release build; the default sandbox image is one build-stamped digest with three consumers (C4.1, C4.3).
- [ ] The gateway refuses to start when the release digest is absent, and N sandbox spawns produce exactly **one** `docker pull` — zero when the image is already local (C4.2, C5.1, C5.2, C5.4).
- [ ] The cached digest refreshes only through an explicit image-update operation (C5.3).
- [ ] No required check classifies `failure` as acceptable, and the aggregator's name states what it proves (C2.1, C2.2).
- [ ] A failing container scan leaves **no consumable tag**; stable tags are promoted by digest; `main` writes no `latest` (C12.3, C13.1, C13.2).
- [ ] Every release-tooling installer is pinned and verified, and a CI gate rejects new `curl … | sh` (C11.1, C11.2, C11.3).
- [ ] No compose file or overlay disables the browser sandbox, and the guard test inspects overlays as well as Dockerfiles (C8.1, C8.2, C8.4).
- [ ] The browser runs as its own minimally-privileged service with no `sevn-state` mount and no gateway token — or the deferral is recorded with a follow-up issue (C8.3, D50).
- [ ] The permissions init chowns only application-owned directories, is gated on a versioned marker, and CI no longer diverges (C9.1, C9.2, C9.3, C9.4).
- [ ] A documented minimum Compose version is enforced, and an integration check proves `NanoCpus`, `Memory` and `PidsLimit` are enforced at runtime for every service in every resolved file set (C10.1, C10.2, C10.3).
- [ ] A sandbox presenting the **service secret** is rejected; session tokens are run-bound and container-bound (C7.1, C7.2).
- [ ] Destination allowlists and per-run request/byte budgets are enforced proxy-side, and the schema stops describing unimplemented behaviour as current (C7.3, C7.4).
- [ ] `local_open_trust_address` is refused under a tunnel or reverse proxy, warns at boot, and the CLI no longer claims "no login required" (C6.2, C6.4).
- [ ] `make verify-deployment` runs on the daily cron and on release tags, with `driver_unavailable` failing the release path, new drivers covering the previously unexercised paths, and evidence attached to the release (C14.1, C14.2, C14.3).
- [ ] **Every landed contract survived** — `C1.1` (503 fail-closed), `C2.3` (draft + tag gate), `C6.1`/`C6.3` (dashboard token), `C12.1`/`C12.2`/`C12.4` (scan gates signing) are green and unmodified at every batch Final (D40, D43).
- [ ] Six PRs merged to `pre-0.0.1`, each **Thermos-clean including `low`** (D31), with `make ci-resume` green.
- [ ] **No PR opened over gate-authored code that no gate saw** — every batch's `<X>-Reverify` is closed by a `wave-verifier` that did not run that batch's Thermos (D29, D30).

---

## Traceability

### Change ID → wave

| ID | Wave | Batch | RED wave |
|---|---|---|---|
| C1.2 | W4 | A | W1 |
| C1.3 | W5 | A | W1 |
| C1.4 | W5 | A | W1 |
| C1.5 | W2 | A | W1 |
| C3.1 | W2 | A | W1 |
| C3.2 | W3 | A | W1 |
| C3.3 | W3 | A | W1 |
| C4.1 | W7 | B | W6 |
| C4.2 | W8 | B | W6 |
| C4.3 | W7 | B | W6 |
| C5.1 | W8 | B | W6 |
| C5.2 | W8 | B | W6 |
| C5.3 | W8 | B | W6 |
| C5.4 | W6 → W8 | B | W6 |
| C2.1 | W10 | C | W9 |
| C2.2 | W10 | C | W9 |
| C11.1 | W12 | C | W9 |
| C11.2 | W12 | C | W9 |
| C11.3 | W12 | C | W9 |
| C12.3 | W11 | C | W9 |
| C13.1 | W11 | C | W9 |
| C13.2 | W11 | C | W9 |
| C8.1 | W14 | D | W13 |
| C8.2 | W14 | D | W13 |
| C8.3 | W17 | D | W13 |
| C8.4 | W14 | D | W13 |
| C9.1 | W15 | D | W13 |
| C9.2 | W15 | D | W13 |
| C9.3 | W13 | D | W13 |
| C9.4 | W15 | D | W13 |
| C10.1 | W16 | D | W13 |
| C10.2 | W16 | D | W13 |
| C10.3 | W16 | D | W13 |
| C7.1 | W19 | E | W18 |
| C7.2 | W19 | E | W18 |
| C7.3 | W20 | E | W18 |
| C7.4 | W20 | E | W18 |
| C6.2 | W22 | F | W21 |
| C6.4 | W22 | F | W21 |
| C14.1 | W23 | F | W21 |
| C14.2 | W23 | F | W21 |
| C14.3 | W23 | F | W21 |

**Closed before this program (do not schedule):** C1.1, C2.3, C6.1, C6.3, C12.1, C12.2, C12.4.

### Spec / PRD → wave

| Doc | Waves | Edit mode |
|---|---|---|
| `about-sevn.bot/specs/02-config-and-workspace.md` | W2, W4, W22 | Amendment + `make config-schema` |
| `about-sevn.bot/specs/06-secrets.md` | W2, W4 | Amendment |
| `about-sevn.bot/specs/07-egress-proxy.md` | W3, W5, W19, W20 | Amendment |
| `about-sevn.bot/specs/08-sandbox.md` | W7, W8, W19 | Amendment |
| `about-sevn.bot/specs/09-security-scanner.md` | W14, W17 | Amendment |
| `about-sevn.bot/specs/19-channel-webui.md` | W22 | Amendment |
| `about-sevn.bot/specs/22-onboarding.md` | W4 | Amendment |
| `about-sevn.bot/specs/24-dashboard.md` | W22 | Amendment |
| `about-sevn.bot/specs/25-cicd-full.md` | W10, W11, W12, W16, W23 | **In-place prose edit** |
| `about-sevn.bot/prd/03-trust-and-control.md` | W3, W19, W20, W22 | In-place |
| `about-sevn.bot/prd/05-cost-and-providers.md` | W3, W19, W20 | In-place |
| `about-sevn.bot/prd/06-setup-and-operations.md` | W4, W5, W10, W11, W12, W15, W16, W23 | In-place |

---

## Execution order & parallelism

```text
W0  (primary checkout, read-only — anchors, worktrees, 503 repro, verify baseline)
│
├── Batch A  ../sevn-pr-a-proxy-secret    W1 → W2 → W3 → W4 → W5        → Verify → Final → Thermos → Re-verify → PR
│                                                                                                        │
│                             (D35: D rebases on merged A) ─────────────────────────────────────────────┤
│                             (D36: E rebases on merged A) ─────────────────────────────────────────────┘
│
├── Batch B  ../sevn-pr-b-sandbox-image   W6 → W7 → W8                  → Verify → Final → Thermos → Re-verify → PR
│
├── Batch C  ../sevn-pr-c-supply-chain    W9 → W10 → W11 → W12          → Verify → Final → Thermos → Re-verify → PR
│
├── Batch D  ../sevn-pr-d-isolation       W13 → W14 → W15 → W16 → W17   → Verify → Final → Thermos → Re-verify → PR
│                                                └── W15, W16 wait on A merge (D35)
│
├── Batch E  ../sevn-pr-e-egress-scope    W18 → W19 → W20               → Verify → Final → Thermos → Re-verify → PR
│                                                └── W19 waits on A merge (D36)
│
└── Batch F  ../sevn-pr-f-evidence        W21 → W22 → W23               → Verify → Final → Thermos → Re-verify → PR
                                                     └── W23 lands last in the program (D54)
                                                                                                        │
                                                                                            Z1 (after all merges)
```

**B, C and F/W21–W22 are fully independent** and may run concurrently in their own worktrees, merging in any order. **A is on the critical path** for D and E.

| Hard dependency | Reason |
|---|---|
| W0 before all | Anchor freeze, worktrees, the stock-stack **503 reproduction**, the compose-merge limits capture (W0.7), and the "Already landed" re-validation that prevents reverting #167/#169/#173 |
| W2 before W3 | The secret must have one resolution authority before the eleven fallbacks and the write-back are deleted (D41) |
| W3 before W4 | Bootstrap generation writes into a resolution path that must already exist and be single-sourced |
| W4 before W5 | The preflight must not fail the happy path the bootstrap creates (W5.3) |
| W7 before W8 | The constant must be single-sourced before it is resolved once and cached (D42, D43) |
| W10 before W11 before W12 | All three edit `.github/workflows/ci-cd.yml`; serial keeps the diffs reviewable |
| **W13 before W15** | `test-creator` unpins the full-tree `find` before the implementation changes it (**D48**) |
| **W15, W16 after Batch A merges** | Both touch `docker/docker-compose.yml`, which A restructures for env, bootstrap and healthcheck (**D35**) |
| **W19 after Batch A merges** | The session token is signed with the shared secret whose resolution A changes (**D36**) |
| W19 before W20 | `run_id` and container binding must exist before budgets are bound to them |
| W23 last in the program | The evidence job is wired against a fixed stack; W23.4 additionally wants Batch E merged (**D54**) |
| Z1 after all merges | The readiness re-assessment is only meaningful on the merged tree |

### Merge hotspots

| File | Waves / batches | Note |
|---|---|---|
| `docker/docker-compose.yml` | W4, W5 (A) · W15, W16 (D) | **The primary cross-batch hotspot.** A owns env, bootstrap init and healthcheck; D appends hardening, perms scoping and limits after rebasing (D35) |
| `src/sevn/proxy/auth.py` | W3 (A) · W19, W20 (E) | A changes secret **resolution**; E changes what the guard **accepts**. E rebases onto merged A (D36); neither edits the other's surface |
| `src/sevn/proxy/credentials.py` | W2, W3 (both A) | Serial: chain resolution, then deletion of the `os.environ` write-back (D41) |
| `src/sevn/security/sandbox_runtime.py` | W7, W8 (both B) · W19 (E) | B owns the image path (`:1449-1500`, `:1756`, `:1841`, `:2103`); E touches only the child-env/token seam (`:543`) — disjoint, but re-read before editing |
| `.github/workflows/ci-cd.yml` | W10, W11, W12 (all C) · W23 (F) | Serial within C; F appends the tag-path verification job last (D54) |
| `.github/workflows/ci-supplementary.yml` | W23 (F) | Cron home for the deployment-evidence job (D52) |
| `scripts/check-compose-default.sh` | W5 (A) · W16 (D) | A adds the secret preflight; D adds the Compose version floor after rebasing |
| `scripts/verify_deployment.py` | W23 (F) | New drivers registered in `DRIVERS` (`:954-958`) |
| `infra/sevn.schema.json` | W2, W4 (A) · W7 (B) · W20 (E) · W22 (F) | Every edit runs **`make config-schema`**; coordinate at each batch Final so the generated file does not thrash |
| `tests/**` | W1, W6, W9, W13, W18, W21 + gate reconciliation | **`test-creator` only** (D4) |
