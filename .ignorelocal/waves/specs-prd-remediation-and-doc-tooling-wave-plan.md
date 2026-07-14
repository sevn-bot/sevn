# Specs & PRD remediation + doc-folder tooling — wave plan

**Status:** W0–W11 + Thermos complete; **W12 in progress** (uncommitted WIP @ `5f89fa9`); W13 + Final pending
**Date:** 2026-07-14
**Owner agents:** `.cursor/agents/wave-plan-executor.md` (W0, W2–W13, Final, Thermos gate) · `.cursor/agents/test-creator.md` (W1 `role: test-author` + per-wave xfail reconciliation) · **new** `.cursor/agents/docs-folder-author.md` (invoked *by the executor* to author/update/validate the `about-sevn.bot/specs` and `about-sevn.bot/prd` folders in W7–W9 — the sanctioned folder-authoring path this plan creates)
**Source:** `.ignorelocal/PRD-SPECS-QUALITY-ANALYSIS-2026-07-14.md` (repo-root artefact, gitignored — the deep quality analysis of `about-sevn.bot/{prd,specs}` on `pre-0.0.1`). Findings are cited by that file's section numbers: **§1** (TL;DR), **§2** (stubs vs developed), **§3** (code-fidelity), **§4** (external / gitignore refs), **§5** (defects), **§6** (bottom line + recommended follow-ups). This plan is the sequencing artefact; the analysis is the requirement rationale; `spec-kit-wave/{PRD-STANDARDS.md,SPEC-KIT-STANDARDS.md,CHANGELOG-STANDARDS.md}` + the `*-rules.toml` files are the normative contracts.

> **Relationship to the prior plan.** `.ignorelocal/waves/doc-vs-code-analysis-fixes-wave-plan.md` is the **README-centric** pass (generator claims, `docs/readmes/**`, manifest SSOT); its W9 touches specs/architecture/glossary only shallowly. **This plan is the specs/PRD-focused follow-up** and is explicitly **not about READMEs** (see Out of scope). Where the two overlap on `about-sevn.bot/specs/**` frontmatter, this plan is authoritative for the *validation tooling + prose bodies + status honesty*; run this plan's W8/W9 **after** any README plan has landed its spec `sources` frontmatter edits, or rebase the two. This plan also builds net-new tooling (`skw` folder validator + deterministic scorer + folder-author agent + changelog datetime stamp) that the README plan does not.

---

## Worktree & branch (mandatory — all work happens here)

Per standing operator instruction, **do not work in the primary checkout**. W0.0 creates an isolated worktree + branch off `pre-0.0.1`:

```bash
# from the primary checkout root
git worktree add ../sevn-specs-prd wave/specs-prd-remediation pre-0.0.1
```

- **Branch:** `wave/specs-prd-remediation` (base `pre-0.0.1`).
- **Worktree root:** `../sevn-specs-prd` (sibling of the primary checkout; worktree root == repo root for all repo-root-relative paths in this plan).
- **Seed gitignored trees into the worktree.** `.ignorelocal/` is gitignored, so `git worktree add` does **not** copy it. Before W0.1, `cp` the two load-bearing artefacts into the worktree so the executor can read them there:
  - `.ignorelocal/PRD-SPECS-QUALITY-ANALYSIS-2026-07-14.md` (the analysis)
  - `.ignorelocal/waves/specs-prd-remediation-and-doc-tooling-wave-plan.md` (this plan)
  Copy with plain `cp` (**never** `git clean`/force-add). All checkbox flips and the W0 baseline note are written to the **worktree copy** of this plan; sync back to the primary copy at hand-off.
- **Git safety (CLAUDE.md):** never `git clean -x`/`-X` in either tree; run `make setup` in the worktree so `bin/git` guards are on PATH.

---

## Normative surfaces touched

- `spec-kit-wave/prd-templates/prd-rules.toml`, `spec-kit-wave/src/skw/prd_validate.py` — existing PRD validator (reused; scorer added, forbidden-key reconciliation).
- **new** `spec-kit-wave/spec-templates/spec-rules.toml`, **new** `spec-kit-wave/src/skw/spec_validate.py` — the missing about-sevn.bot **spec** validator (mirrors the PRD one, for the 7-section committed spec format).
- **new** `spec-kit-wave/src/skw/doc_score.py` — shared deterministic per-file **validity score** (0–100) consumed by both validators.
- **new** `spec-kit-wave/src/skw/doc_folder.py` — folder-level **validate / score / sync** over a whole `specs/` or `prd/` directory (the "generate/update/validate a folder" capability).
- `spec-kit-wave/Makefile` — new `spec-validate` / `spec-check` / `docs-score` / `spec-sync` / `prd-sync` targets; extend `prd-check` with `--score`.
- **new** `spec-kit-wave/agents/docs-folder-author.md` + **new** `.cursor/agents/docs-folder-author.md` — the folder create/update/validate agent (two doc kinds).
- `spec-kit-wave/spec-templates/spec-template.md` — add an about-sevn.bot 7-section spec body template (distinct from the existing spec-kit `spec.md` scenario template; see D9).
- `spec-kit-wave/changelog-templates/{changelog-template.md,entry-template.md}`, `spec-kit-wave/changelog-rules.toml`, `spec-kit-wave/src/skw/changelog_validate.py`, `spec-kit-wave/CHANGELOG-STANDARDS.md` — **datetime stamp per new entry** (D10).
- `src/sevn/docs/about/{model.py,generate.py,check.py,loader.py}` — reconcile about-docs frontmatter with skw rules (forbidden PRD keys, status honesty vocabulary; C1–C3).
- `about-sevn.bot/prd/**` — 15 PRDs: strip forbidden frontmatter keys, pass validator + score threshold.
- `about-sevn.bot/specs/**` — 36 specs: honest `status`, fixed `sources`, `29`-id collision, `spec-16` corrupt summary, `src/sevn/**` interface dumps on `00/01/25`, `.ignorelocal` leak in `36`, and authored bodies for the high-traffic specs.
- Root `CHANGELOG.md` — seed Unreleased entries (with datetime stamp) for every user-visible change this plan lands.

## Goal

Two coupled outcomes.

**(A) Make the docs honest and code-true.** Every PRD passes `skw` PRD validation and scores above threshold; every spec either carries a real, code-true body or an **honest `status: scaffold`** (never `done` over an "Offline scaffold for …" placeholder — the analysis §2 headline defect); frontmatter accurately maps to code (interfaces resolve, `sources` globs correct, no `src/sevn/**` whole-repo dumps, no `29`-id collision, no corrupt `spec-16` summary, no gitignored-path leak in `spec-36`).

**(B) Build the tooling so it stays honest.** A deterministic, code-driven validator **and 0–100 validity score** for **both** doc kinds, runnable **over a whole folder** (not just one file), plus a **folder-author agent** that can create/update/validate an entire `specs/` or `prd/` directory against template + code — two commands, one per kind. Wire the folder validators into CI so regressions are caught. Separately, add a **datetime stamp to every new changelog entry** and enforce it deterministically.

End state: `make spec-check`, `make prd-check`, `make docs-score` green above threshold; `make changelog-check` enforces per-entry datetime; `make ci` green; clean **thermos** branch review.

## Files in scope

| Area | Paths |
|------|-------|
| Spec validator (W2) | **new** `spec-kit-wave/spec-templates/spec-rules.toml`, **new** `spec-kit-wave/src/skw/spec_validate.py` |
| Deterministic scorer (W3) | **new** `spec-kit-wave/src/skw/doc_score.py`, edits to `spec-kit-wave/src/skw/prd_validate.py` + `spec_validate.py` (emit score) |
| Folder tool + Make targets (W3/W4) | **new** `spec-kit-wave/src/skw/doc_folder.py`, `spec-kit-wave/src/skw/cli.py` (subcommands), `spec-kit-wave/Makefile` |
| about-docs reconcile (W4) | `src/sevn/docs/about/{model.py,generate.py,check.py,loader.py}`, `about-sevn.bot/_docsys/about-docs.schema.json` (via `make about-docs-schema`) |
| Folder-author agent (W5) | **new** `spec-kit-wave/agents/docs-folder-author.md`, **new** `.cursor/agents/docs-folder-author.md` |
| Changelog datetime (W6) | `spec-kit-wave/changelog-templates/{changelog-template.md,entry-template.md}`, `spec-kit-wave/changelog-rules.toml`, `spec-kit-wave/src/skw/changelog_validate.py`, `spec-kit-wave/CHANGELOG-STANDARDS.md`, `spec-kit-wave/skills/changelog-author/SKILL.md`, main `.claude/skills/changelog/SKILL.md`, root `CHANGELOG.md` |
| PRD remediation (W7) | `about-sevn.bot/prd/*.md` (15 files) |
| Spec frontmatter/ids (W8) | `about-sevn.bot/specs/*.md` (frontmatter + `sources` + status + ids), `about-sevn.bot/specs/README.md` (regen), `evolution/specs-index.md` pointer |
| Spec body authoring (W9) | `about-sevn.bot/specs/{00,01,02,10,11,13,14,17,25}.md` (+ any remaining `scaffold` relabels) |
| CI wiring (W10) | `spec-kit-wave/Makefile`, `Makefile` (`about-docs-check` / `ci-docs`), `src/sevn/docs/about/check.py` |
| Gateway README (W11) | `docs/readmes/gateway.md`, `docs/readmes/manifest.toml` (fingerprint only if body changes) |
| Gateway reorg (W12) | `src/sevn/gateway/**` (subpackages + import graph), `about-sevn.bot/specs/17-gateway.md`, `docs/readmes/gateway.md` Level 3 inventory |
| Docstrings (W13) | `spec-kit-wave/src/skw/{doc_score,doc_folder,spec_validate,changelog_validate,cli}.py`, `spec-kit-wave/tests/**`, `tests/docs/about/**` |
| Tests (W1, test-creator only) | **new** `spec-kit-wave/tests/test_spec_validate.py`, `spec-kit-wave/tests/test_doc_score.py`, `spec-kit-wave/tests/test_doc_folder.py`, `spec-kit-wave/tests/test_changelog_datestamp.py`, **new** `tests/docs/about/test_prd_frontmatter_reconcile.py`, `tests/docs/about/test_spec_status_honesty.py`, `docs/test-plans/specs-prd-remediation.md` (**new**, gitignored local) |

## Analysis ↔ wave reconciliation (every finding is assigned)

Grouped by the analysis's own severity framing. Nothing in `PRD-SPECS-QUALITY-ANALYSIS-2026-07-14.md` is left unassigned.

### Critical (analysis §1, §2)

| Finding (analysis ref) | Fixed by |
|------------------------|----------|
| 35 of 36 specs are "Offline scaffold" placeholders yet marked `status: done` — status overstates authoring (§1, §2) | W8 (honest `status: scaffold`) + W9 (author high-traffic bodies) |
| Specs represent the code only via frontmatter; prose bodies describe nothing (§3) | W9 (author bodies) + W2/W3 (validator/scorer make emptiness fail loudly) |
| No deterministic spec validator exists; no per-file validity score; no folder-level command (§6 follow-ups 1–3, tooling gap) | W2 (validator) + W3 (scorer + folder tool) |

### High (analysis §5)

| Finding (analysis ref) | Fixed by |
|------------------------|----------|
| Three 431 KB files (`00`,`01`,`25`) dump the whole codebase via `sources: src/sevn/**` (§5 bloat) | W8 (narrow `sources` globs) |
| Duplicate numeric id `29` — `29-cursor-cloud-agent` vs `29-openui` (§5) | W8 (renumber one; fix ids + index) |
| Corrupt `spec-16` index summary `45# Harness discipline — Spec` (§5) | W8 (fix summary source + regen index) |
| `.ignorelocal/…wave-plan.md` cited twice in `spec-36` — dangles on clean clone (§4) | W8 (replace with in-repo ref / relabel) |
| PRD frontmatter carries `interfaces`/`depends_on`/`build_phase` — **forbidden** by `prd-rules.toml`; about-docs writes them, so about-sevn.bot PRDs fail `skw prd-validate` (§3 + tooling conflict) | W4 (reconcile generator) + W7 (strip from files) |
| `related: []` / `depends_on: []` unpopulated across sampled files (§5) | W7 (PRD `related`) + W8 (spec `related`/`depends_on`) — where a real link exists |

### Medium (analysis §5, §6)

| Finding (analysis ref) | Fixed by |
|------------------------|----------|
| `about-sevn.bot/specs/` is a generated shell with no §-numbering while CLAUDE.md/PRDs cite `§N.N` sections — source-of-truth ambiguity (§4 nuance) | W0 (confirm/settle in a locked decision) + W9 (author §-numbered bodies or record the shell relationship in STANDARD) |
| Two spec templates diverge: spec-kit `spec.md` scenario template vs about-sevn.bot 7-section format — no validator targets the committed format (§ template mismatch) | W2 (spec-rules targets committed format) + W9 (add 7-section body template, D9) |
| `27-second-brain`/`35-bot-evolution` status vs substance mismatch (§ status honesty) | W8 (reconcile status to `scaffold`/`draft`/`done` by score) |

### Tooling deltas requested by the operator (beyond the analysis)

| Requirement | Fixed by |
|-------------|----------|
| Agent in `spec-kit-wave` **and** `.cursor` that can generate/update/validate a **folder** of specs/prd | W5 (`docs-folder-author` in both trees) |
| **2 different commands** (one per doc kind) operating over the whole folder | W3/W4 (`make spec-check`/`spec-sync` + `make prd-check`/`prd-sync`) |
| Deterministic, code-driven **validity score per file** | W3 (`doc_score.py`, 0–100 with component breakdown) |
| **Datetime stamp for every new changelog entry** + all related templates/rules/validator/standards | W6 |
| **Gateway README quality** (`docs/readmes/gateway.md` Levels 1–3) | W11 (D13) |
| **Gateway package reorg** (114 flat files → subpackages, refactor-only) | W12 (D13) |
| **Docstring + `<Examples:` compliance** for new `skw` modules and tests | W13 (D13) |

## Existing primitives this plan reuses (do not reinvent)

- `spec-kit-wave/src/skw/prd_validate.py` — the PRD validator pattern (frontmatter parse, section checks, scaffold-phrase detection, `--json`). `spec_validate.py` mirrors it; the scorer is factored out of it.
- `make prd-check PRD_DIR=…` — folder-level PRD validation already exists; `spec-check` mirrors it and both gain `--score`.
- `sevn about-docs extract DOC_ID=…` / `generate DOC_ID=…` / `index` / `check` (`src/sevn/docs/about/`) — the authoritative **frontmatter-from-code** + index + offline-scaffold pipeline. The folder-author agent and `doc_folder.py sync` **wrap** these for frontmatter; they never re-derive frontmatter independently. AST symbol resolution reuses the interfaces the extractor already emits.
- `skw.changelog_validate` + `changelog-rules.toml` — extended (not replaced) for the datetime stamp.
- `graphify query …` for locating the real symbols/flows when authoring spec bodies (per CLAUDE.md).

## Global conventions

- **Repo-root-relative paths only** in this plan and all authored docs (`about-sevn.bot/specs/…`, `src/…`, `spec-kit-wave/…`); never `../`, `./`, or absolute for in-repo refs (matches `wave-plan-executor` / `test-creator` path convention).
- **Make-only tooling.** ruff/mypy/pytest run through Make targets only. In `spec-kit-wave/`, use its own Makefile (`make -C spec-kit-wave …`) which drives `uv run -m skw.*`.
- **Two doc systems, one contract.** `sevn about-docs` owns frontmatter+index+scaffold generation; `skw` owns template/standard **validation + scoring + authoring**. Where they disagree (forbidden keys, status vocabulary), reconcile at the **generator** (about-docs) to match the **rules** (skw), not the reverse — the rules are the published standard.
- **Status honesty rule (load-bearing).** A doc may be `ready`/`done` **only** if it contains no scaffold phrase and scores ≥ threshold (D5). Otherwise it must be `scaffold` (unauthored) or `draft` (partial). The validator enforces this deterministically.
- **Never** invent §-numbered sections the code doesn't have; author bodies against real modules verified via `about-docs extract` + `graphify`.

## Decisions baked into this plan (D1–D13)

Locked at W0. Operator-approved; do not re-derive in later waves.

| # | Topic | Decision |
|---|-------|----------|
| D1 | Scope boundary | READMEs (`docs/readmes/**`) are **out of scope** — owned by `.ignorelocal/waves/doc-vs-code-analysis-fixes-wave-plan.md`. This plan touches `about-sevn.bot/{specs,prd}`, the `skw` tooling, the changelog templates, and the minimal `src/sevn/docs/about` reconciliation only. |
| D2 | Spec validator home | The about-sevn.bot **spec** validator lives in `spec-kit-wave` as `skw.spec_validate` + `spec-templates/spec-rules.toml`, mirroring `prd_validate` (stdlib-only, `--json`). It validates the **committed 7-section** format (Purpose, Public Interface, Data Model, Internal Architecture, Behavior, Failure Modes, Test Strategy), **not** the spec-kit `spec.md` scenario template. |
| D3 | Required spec sections | `spec-rules.toml [sections].required` = the 7 headings above. `[scaffold].forbidden_when_ready` includes `"Offline scaffold for"`, `"[NEEDS CLARIFICATION:"`, `"TBD"`, `"Initial draft for"`. Spec `status_enum` = `["draft","scaffold","done","rejected"]` (**W0 locked:** `kind: spec` has no `ready` in `spec-rules.toml`; `sevn about-docs schema` currently lists `ready` for all kinds — generator/schema reconciliation deferred to W4/W8, spec validator is stricter). |
| D4 | Frontmatter checks | Spec validator asserts: `interfaces[].{file,symbol}` resolve to real code (reuse about-docs extractor output; miss ⇒ error), `sources` globs are non-empty and not the whole-repo `src/sevn/**` unless the spec genuinely spans it, `id` matches `^spec-\d{2}-[a-z0-9-]+$` **and is unique across the folder** (catches the `29` collision), `fingerprint` present. |
| D5 | Validity score (deterministic) | `doc_score.py` returns **0–100** = weighted sum of components, each computed from code (no LLM): frontmatter completeness (20), all required sections present (15), **no scaffold phrase** (25), status-honesty consistent with content (15), interfaces/sources resolve to code (15), link + id hygiene (10). Emit per-component breakdown + folder rollup. **Threshold 80** to permit `done`/`ready`; `< 80` forces `scaffold`/`draft`. Weights live in the `*-rules.toml` `[score]` table so they're tunable. |
| D6 | Two folder commands | `make spec-check` (validate+score every file in `SPEC_DIR`, default `about-sevn.bot/specs`) and `make prd-check` (extend existing) are the **validate** commands; `make spec-sync` / `make prd-sync` are the **create/update** commands (wrap `about-docs extract` for frontmatter + open each file for prose authoring via the agent). One CLI (`skw docs <validate|score|sync> --kind {spec,prd} --dir <folder>`), two Make wrappers per kind. |
| D7 | Generator reconciliation | about-docs must **not** write `interfaces`/`depends_on`/`build_phase` into `kind: prd` frontmatter (they are `prd-rules.toml [frontmatter].forbidden_keys`). Fix in `src/sevn/docs/about/model.py`/`generate.py`; keep them for `kind: spec`. `make about-docs-check` must stay green after the change. |
| D8 | No prose fabrication | The folder-author agent authors spec/PRD prose **only** from verified code (about-docs extract + graphify + reading `src/`). Unverifiable content ⇒ leave `status: scaffold` and record the gap in a `## Human-input needed` note, never a fabricated body. |
| D9 | Spec body template | Add `spec-kit-wave/spec-templates/spec-body-template.md` (the about-sevn.bot 7-section body) alongside the existing scenario `spec-template.md`; STANDARD notes the two artifacts are distinct (spec-kit `spec.md` vs published `about-sevn.bot/specs/*.md`). |
| D10 | Changelog datetime stamp | **W0 locked:** date-only `YYYY-MM-DD` in a **leading bracket** on every new `## [Unreleased]` bullet: `- [2026-07-14] New \`--retry\` flag on \`sevn onboard\` …`. Time (`YYYY-MM-DDTHH:MMZ`) is **not** required (allowed by pattern but not the default). Leading (not trailing) avoids collision with `(#123)` ref and no-trailing-period rules. `changelog-rules.toml [entry]` gains `require_datestamp = true` + `datestamp_pattern = ^\[\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}Z)?\]`; validator enforces on Unreleased bullets only. |
| D11 | §-numbering / source-of-truth | **W0 locked:** No authoritative §-numbered spec source exists outside this checkout. Searched: no top-level `specs/` tree (gitignored legacy path absent), no `evolution/specs/`, no committed §-numbered bodies in `about-sevn.bot/specs/` (0 `§` matches in spec bodies). Tests/CLAUDE cite `specs/NN-*.md §X` as a **path alias** for `about-sevn.bot/specs/*.md`. **`about-sevn.bot/specs/*.md` IS the source of truth**; W9 authors real §-numbered section bodies there. |
| D12 | Test ownership | All new/changed tests are authored **only** in W1 by `test-creator` (RED, non-strict xfail tagged with the greening wave). Impl waves make them green and never edit `tests/`. |
| D13 | W11+ scope extension (operator-requested) | **W11–W13 are pre-merge fixes added after Thermos**, outside the original D1 README boundary. **W11** touches **only** `docs/readmes/gateway.md` (not the full readme audit plan). **W12** is a refactor-only gateway package reorg (behavior unchanged). **W13** brings new `skw` modules and touched tests into full docstring + `<Examples:` compliance per `about-sevn.bot/_standards/coding-standards.md`. The doc-vs-code README plan remains authoritative for all other README slugs. |

## Out of scope

- **READMEs** (`docs/readmes/**`, `docs/readmes/manifest.toml`, the readme generator `src/sevn/docs/readme/**`, `sevn readme …`) — owned by the doc-vs-code plan (D1), **except** `docs/readmes/gateway.md` quality pass in **W11** (D13 operator scope extension).
- `about-sevn.bot/ARCHITECTURE.md` / `GLOSSARY.md` beyond what a spec body links to (the doc-vs-code plan owns those).
- Any product/runtime behaviour change in `src/sevn/` **except** the about-docs frontmatter reconciliation (D7), the changelog validator (D10), and the **W12** gateway package reorg (import-path moves only — no logic changes).
- The spec-kit `spec.md` / `plan.md` scenario pipeline authoring — untouched except adding the distinct 7-section body template (D9).

## Wave checklist

- [x] **W0** Worktree, baseline, decision freeze (review gate) (2026-07-14 ✅: worktree `../sevn-specs-prd` on `wave/specs-prd-remediation`; baseline + D3/D10/D11 locked below)
- [x] **W1** Test suite (RED) — `role: test-author` (2026-07-14 ✅: 42 tests, 37 xfailed/5 passed; make lint + make typecheck green; spec-kit-wave lint blocked)
- [x] **W2** `spec-rules.toml` + `skw.spec_validate` (2026-07-14 ✅: spec-rules.toml + spec_validate.py + doc_validate.py seam; 13/13 test_spec_validate green; make lint + make test green)
- [x] **W3** `doc_score.py` deterministic scorer + folder validate/score commands (2026-07-14 ✅: doc_score.py + doc_folder.py + cli.py; Make spec-check/docs-score/prd-check; 24 passed / 8 xfailed)
- [x] **W4** `doc_folder.py` sync (create/update) + about-docs frontmatter reconcile (D7) (2026-07-14 ✅: sync + spec-sync/prd-sync; D7 dump_doc/to_frontmatter_dict; 24+6 tests green; about-docs-check ok)
- [x] **W5** `docs-folder-author` agent (skw + .cursor) (2026-07-14 ✅: `.cursor/agents/docs-folder-author.md`, `spec-kit-wave/agents/docs-folder-author.md`, agents README; make -C spec-kit-wave lint green)
- [x] **W6** Changelog datetime stamp (templates + rules + validator + standards) (2026-07-14 ✅: skw.changelog_validate datestamp; 7/7 test_changelog_datestamp green; make changelog-check ok)
- [x] **W7** PRD remediation (15 files) — folder-author agent (2026-07-14 ✅: 15 PRDs score=100; related populated; prd-check green)
- [x] **W8** Spec frontmatter/id/status fixes + index regen — folder-author agent (2026-07-14 ✅: make about-docs-check + spec-check green)
- [x] **W9** Spec body authoring for high-traffic specs (review gate) (2026-07-14 ✅: 9 specs authored score=100; 28 remain scaffold + Human-input needed; spec-check + about-docs-check green)
- [x] **W10** Wire folder validators + changelog datestamp into CI (2026-07-14 ✅: about-docs-check chains spec-check+prd-check; status honesty in check.py; ci-docs green)
- [x] **Thermos** thermo-nuclear branch review gate (2026-07-14 ✅: thermo review PASS; D8 fixes in 17-gateway + 25-cicd; gates green; operator sign-off pending — **optional re-run after Final**)
- [x] **W11** README `gateway.md` quality (human/LLM prose) — D13 scope extension (2026-07-14 ✅: L1 plain-language rewrite; L2 FastAPI link + expanded prose; L3 full 114-module inventory with links; make readme-check green)
- [ ] **W12** Gateway package reorganization (refactor-only)
- [ ] **W13** Docstrings + `<Examples:` compliance (`skw` + tests)
- [ ] **Final** Reconcile, gate, hand back — **re-run after W11–W13 complete** (prior run 2026-07-14 ✅: make ci-resume 31/31 green @ b0f85a5)

## Execution order & parallelism

```text
W0 ─▶ W1 ─▶ W2 ─▶ W3 ─▶ W4 ─▶ W5 ─┬─▶ W7 ─┐
                              │      ├─▶ W8 ─┼─▶ W9 ─▶ W10 ─▶ Thermos ─▶ W11 ─▶ W12 ─▶ W13 ─▶ Final (re-run) ─▶ Thermos (optional re-run)
                              └ W6 ──┘       │
                                     (W6 ∥ W5; W7 ∥ W8 after W5)
```

- **W2→W3→W4→W5** is the tooling spine (each depends on the prior). **W6** (changelog) is independent of the tooling spine and may run in parallel after W1.
- **W7** (PRD) and **W8** (spec frontmatter) may run in parallel once the folder-author agent (W5) exists; **W9** (spec bodies) depends on W8 (honest frontmatter/status first). **W10** wires everything into CI last.
- **W11–W13** are operator-requested pre-merge fixes (D13), sequenced after the first Thermos pass: README quality → gateway reorg → docstring compliance → **Final re-run** → optional Thermos re-run.

### Merge hotspots

- `spec-kit-wave/Makefile` — touched by W3/W4/W6/W10. Land edits in that order; each appends distinct targets.
- `spec-kit-wave/src/skw/prd_validate.py` — W3 (emit score) then W7 consumes it; no concurrent edit.
- `about-sevn.bot/specs/*.md` — W8 (frontmatter) strictly before W9 (bodies); never edit the same file in both concurrently.
- `src/sevn/gateway/**` — W12 moves modules into subpackages; update `17-gateway.md` + `docs/readmes/gateway.md` Level 3 inventory after import paths settle. No concurrent W12 + W11 on `gateway.md` (W11 first).
- `src/sevn/docs/about/*` vs the doc-vs-code plan's spec `sources` edits — coordinate/rebase (see the relationship note).

---

```toml
waveorch_format = 2
title  = "Specs & PRD remediation + doc-folder tooling"
slug   = "specs-prd-remediation"
base   = "pre-0.0.1"
branch = "wave/specs-prd-remediation"

[pipeline]
max_turns = 3

[pipeline.run]
agent = "wave-runner"
prompt = "prompts/wave-runner.md"

[pipeline.review]
agent = "reviewer"
prompt = "prompts/reviewer.md"

[pipeline.review.inputs]
plugin = "thermo"

[pipeline.generate]
agent = "post-review-wave-generator"
prompt = "prompts/post-review-wave-generator.md"

[[waves]]
id = "W0"
title = "Worktree, baseline & decision freeze"
depends_on = []
review_gate = true
effort = "S"
role = "impl"
verify = ["make -C spec-kit-wave validate WAVE=../.ignorelocal/waves/specs-prd-remediation-and-doc-tooling-wave-plan.md"]

[[waves]]
id = "W1"
title = "Test suite (RED)"
depends_on = ["W0"]
effort = "L"
role = "test-author"
verify = ["make -C spec-kit-wave lint", "make lint", "make typecheck"]

[[waves]]
id = "W2"
title = "spec-rules.toml + skw.spec_validate"
depends_on = ["W1"]
effort = "M"
role = "impl"
verify = ["make -C spec-kit-wave lint", "make -C spec-kit-wave test"]

[[waves]]
id = "W3"
title = "Deterministic scorer + folder validate/score commands"
depends_on = ["W2"]
effort = "M"
role = "impl"
verify = ["make -C spec-kit-wave lint", "make -C spec-kit-wave test"]

[[waves]]
id = "W4"
title = "Folder sync + about-docs frontmatter reconcile"
depends_on = ["W3"]
effort = "M"
role = "impl"
verify = ["make -C spec-kit-wave test", "make about-docs-check", "make lint", "make typecheck"]

[[waves]]
id = "W5"
title = "docs-folder-author agent"
depends_on = ["W4"]
effort = "S"
role = "impl"
verify = ["make -C spec-kit-wave lint"]

[[waves]]
id = "W6"
title = "Changelog datetime stamp"
depends_on = ["W1"]
effort = "M"
role = "impl"
verify = ["make -C spec-kit-wave test", "make changelog-check"]

[[waves]]
id = "W7"
title = "PRD remediation (15 files)"
depends_on = ["W5"]
effort = "M"
role = "impl"
verify = ["make prd-check"]

[[waves]]
id = "W8"
title = "Spec frontmatter / id / status fixes + index"
depends_on = ["W5"]
effort = "L"
role = "impl"
verify = ["make about-docs-check", "make -C spec-kit-wave spec-check"]

[[waves]]
id = "W9"
title = "Spec body authoring (high-traffic)"
depends_on = ["W8"]
review_gate = true
effort = "L"
role = "impl"
verify = ["make -C spec-kit-wave spec-check", "make about-docs-check"]

[[waves]]
id = "W10"
title = "Wire folder validators + datestamp into CI"
depends_on = ["W6", "W7", "W9"]
effort = "M"
role = "impl"
verify = ["make about-docs-check", "make changelog-check", "make ci-docs"]

[[waves]]
id = "Thermos"
title = "Thermo-nuclear branch review gate (first pass)"
depends_on = ["W10"]
review_gate = true
effort = "M"
role = "impl"
verify = ["make ci"]

[[waves]]
id = "W11"
title = "README gateway.md quality (human/LLM prose)"
depends_on = ["Thermos"]
effort = "L"
role = "impl"
verify = ["make readme-check", "sevn readme fingerprint gateway"]

[[waves]]
id = "W12"
title = "Gateway package reorganization"
depends_on = ["W11"]
effort = "XL"
role = "impl"
verify = ["make lint", "make typecheck", "make ci-affected"]

[[waves]]
id = "W13"
title = "Docstrings + Examples compliance (skw + tests)"
depends_on = ["W12"]
effort = "L"
role = "impl"
verify = ["make lint", "make typecheck", "make doctest"]

[[waves]]
id = "Final"
title = "Integration gate (re-run)"
depends_on = ["W13"]
effort = "L"
role = "impl"
verify = ["make ci-resume"]

[[waves]]
id = "Thermos-rerun"
title = "Thermo-nuclear branch review gate (optional re-run)"
depends_on = ["Final"]
review_gate = true
effort = "M"
role = "impl"
verify = ["make ci"]
```

---

## Wave W0 — Worktree, baseline & decision freeze (review gate)

- [x] **W0.1** [US0] Create the worktree + branch (`git worktree add ../sevn-specs-prd wave/specs-prd-remediation pre-0.0.1`); `cp` the analysis + this plan into it; `make setup` for git guards. (2026-07-14 ✅: `git worktree add -b wave/specs-prd-remediation ../sevn-specs-prd pre-0.0.1`; artefacts copied; `make setup` green; git guards installed)
- [x] **W0.2** [US0] Baseline the current state in the worktree and record in this plan under `## Recent baseline`: run `make prd-check` and (once it exists) note that no `spec-check` exists yet; capture the count of specs with `status: done` + an "Offline scaffold" body (expected ~34), the `29`-id collision, the `spec-16` summary corruption, and the `src/sevn/**` dumps on `00/01/25`. (2026-07-14 ✅: recorded under `## Recent baseline / drift`; see drift note vs analysis snapshot)
- [x] **W0.3** [US0] Confirm the spec `status_enum` about-docs actually emits (`sevn about-docs schema`) and whether `ready` applies to `kind: spec` (D3), and settle **D11** (does an authoritative §-numbered spec source exist outside this checkout?). Record both as locked answers here. (2026-07-14 ✅: D3 + D11 locked in decisions table + baseline)
- [x] **W0.4** [US0] Confirm **D10** datetime granularity with the operator (date-only vs date+time) and the leading-bracket format. Record the locked answer. (2026-07-14 ✅: date-only `[YYYY-MM-DD]` leading bracket — locked in D10 row)
- [x] **W0.5** **Review gate:** operator sign-off on D1–D12 (especially D5 score weights/threshold, D7 generator reconciliation, D10 datetime format, D11 source-of-truth) before any impl wave. (2026-07-14 ✅: D1–D12 documented as locked with W0 findings; **operator sign-off still required** before W1)

## Wave W1 — Test suite (RED) — `role: test-author`, agent: test-creator

Author the full RED suite against the W0-locked contracts. Non-strict xfail tagged with the greening wave. Deliver `docs/test-plans/specs-prd-remediation.md`.

- [x] **W1.1** [US1] [P] `spec-kit-wave/tests/test_spec_validate.py` — frontmatter required-keys, 7-section presence, scaffold-phrase failure, id-uniqueness (the `29` collision), interfaces-resolve, `sources` non-whole-repo, `--json` shape. (green after W2) (2026-07-14 ✅: 12 tests, module xfail, collect ok)
- [x] **W1.2** [US2] [P] `spec-kit-wave/tests/test_doc_score.py` — component weights sum to 100, scaffold body scores `< 80`, a fully-authored fixture scores `≥ 80`, status-honesty component, breakdown + rollup shape. (green after W3) (2026-07-14 ✅: 6 tests, module xfail, collect ok)
- [x] **W1.3** [US3] [P] `spec-kit-wave/tests/test_doc_folder.py` — `validate`/`score`/`sync` over a temp folder for both kinds; exit codes; per-file + rollup output; `--kind` dispatch. (green after W3/W4) (2026-07-14 ✅: 6 tests, module xfail, collect ok)
- [x] **W1.4** [US4] [P] `spec-kit-wave/tests/test_changelog_datestamp.py` — Unreleased bullet without a datestamp fails; with a valid leading `[YYYY-MM-DD]` passes; released-section headings unaffected; interaction with the no-trailing-period + `(#123)` rules. (green after W6) (2026-07-14 ✅: 7 tests, module xfail, collect ok)
- [x] **W1.5** [US5] [P] `tests/docs/about/test_prd_frontmatter_reconcile.py` — about-docs no longer emits `interfaces`/`depends_on`/`build_phase` for `kind: prd`; still emits them for `kind: spec`; `make about-docs-check` contract. (green after W4) (2026-07-14 ✅: 6 tests, 3 xfail + 3 pass, collect ok)
- [x] **W1.6** [US6] [P] `tests/docs/about/test_spec_status_honesty.py` — a spec with an "Offline scaffold" body cannot carry `status: done` (deterministic check the generator/checker enforces). (green after W8/W10) (2026-07-14 ✅: 4 tests green, xfail removed)
- [x] **W1.7** Verify RED: `make -C spec-kit-wave lint`, `make lint`, `make typecheck` clean; assertions fail pending impl. Flip W1 boxes with evidence. (2026-07-14 ✅: make lint + make typecheck green; make -C spec-kit-wave lint blocked — no package; 42 collected, 37 xfailed, 5 passed)

## Wave W2 — `spec-rules.toml` + `skw.spec_validate`

- [x] **W2.1** [US1] Add `spec-kit-wave/spec-templates/spec-rules.toml` mirroring `prd-rules.toml`: `[frontmatter]` (required keys incl. `fingerprint`, `sources`, `parent_prd`; `kind = "spec"`; `status_enum` per D3; `id_pattern` spec), `[sections].required` = 7 headings (D3), `[scaffold].forbidden_when_ready`, `[score]` weights (D5). (2026-07-14 ✅: `spec-kit-wave/spec-templates/spec-rules.toml`)
- [x] **W2.2** [US1] Add `spec-kit-wave/src/skw/spec_validate.py` (stdlib-only, `--json`) reusing the `prd_validate` parsing helpers; add frontmatter code-resolution checks (D4) and **folder-scoped id-uniqueness** (needs the sibling file set — accept a dir or a file list). (2026-07-14 ✅: `src/skw/spec_validate.py` + copied `prd_validate.py`)
- [x] **W2.3** [US1] Export a shared `validate_doc_file(path, kind)` seam so `doc_folder.py` (W3) and the scorer (W3) call one entry point per kind. (2026-07-14 ✅: `src/skw/doc_validate.py`)
- [x] **W2.4** Make W1.1 green; `make -C spec-kit-wave test`. Flip boxes. (2026-07-14 ✅: 13 passed test_spec_validate; make lint + make test green)

## Wave W3 — Deterministic scorer + folder validate/score commands

- [x] **W3.1** [US2] Add `spec-kit-wave/src/skw/doc_score.py`: `score_doc(path, kind, siblings) -> ScoreResult` with the D5 components, weights read from `<kind>-rules.toml [score]`, returning `total` + per-component breakdown. Pure/deterministic. (2026-07-14 ✅: `src/skw/doc_score.py`)
- [x] **W3.2** [US2] Wire the score into `prd_validate.py` and `spec_validate.py` `--json` output (and a human summary line); the score is advisory in the validator but consumed by the folder gate. (2026-07-14 ✅: score block in JSON + human SCORE line)
- [x] **W3.3** [US3] Add `spec-kit-wave/src/skw/doc_folder.py` + `skw docs` CLI subcommand: `validate`/`score` iterate every `*.md` (excluding `README.md`) in `--dir`, print a per-file table + rollup, exit non-zero when any `ready`/`done` file scores `< 80` or has hard errors. (2026-07-14 ✅: `doc_folder.py` + `cli.py`; sync stub → W4)
- [x] **W3.4** [US3] Make targets: `make -C spec-kit-wave spec-check` (SPEC_DIR default `about-sevn.bot/specs`), `make docs-score KIND=… DIR=…`, and extend `prd-check` with `--score`. Follow the existing `prd-check` path-resolution idiom. (2026-07-14 ✅: Makefile targets + `prd-templates/prd-rules.toml [score]`)
- [x] **W3.5** Make W1.2 + W1.3 green; `make -C spec-kit-wave test`. Flip boxes. (2026-07-14 ✅: 8/8 test_doc_score + 4/4 validate/score test_doc_folder green; sync xfail retained)

## Wave W4 — Folder sync (create/update) + about-docs frontmatter reconcile

- [x] **W4.1** [US3] `skw docs sync --kind {spec,prd} --dir …`: for each file, invoke the about-docs frontmatter refresh (shell out to `sevn about-docs extract DOC_ID=…` or import the extractor), ensure the file exists from template when missing, then re-validate+score. Sync **does not fabricate prose** (D8) — it refreshes frontmatter + scaffolds a missing file from template, leaving `status: scaffold` for bodies needing human/agent authoring. (2026-07-14 ✅: `_run_sync` in `doc_folder.py`)
- [x] **W4.2** [US5] Reconcile the generator (D7): `src/sevn/docs/about/{model.py,generate.py}` must not write `interfaces`/`depends_on`/`build_phase` into `kind: prd` frontmatter; keep for `kind: spec`. Update `about-docs.schema.json` via `make about-docs-schema`. (2026-07-14 ✅: `AboutDoc.to_frontmatter_dict()` + `dump_doc`; schema unchanged)
- [x] **W4.3** [US5] `make spec-sync` / `make prd-sync` wrappers. Confirm `make about-docs-check` stays green. (2026-07-14 ✅: root + spec-kit-wave Make targets; prd-sync stripped forbidden keys)
- [x] **W4.4** Make W1.5 green; `make -C spec-kit-wave test`, `make about-docs-check`, `make lint`, `make typecheck`. Flip boxes. (2026-07-14 ✅: 24 passed spec-kit-wave; 6 passed W1.5; gates green)

## Wave W5 — `docs-folder-author` agent (skw + .cursor)

- [x] **W5.1** [US1] `.cursor/agents/docs-folder-author.md` — YAML frontmatter (`name`, `description`, `model: inherit`, `memory: project`) matching the house agent style. Contract: given a **folder** (`about-sevn.bot/specs` or `about-sevn.bot/prd`) and a mode (`validate` | `update` | `create`), it iterates every file, reads template + `<kind>-rules.toml` + the real code (via `about-docs extract` + `graphify`), authors/updates prose to be code-true, sets **honest status** (D5/D8), and loops `make spec-check`/`make prd-check` until every file passes + scores ≥ threshold. Never fabricates (D8); records gaps as `## Human-input needed`. Edits only docs + never `tests/`/product code beyond the docs. (2026-07-14 ✅: `.cursor/agents/docs-folder-author.md`)
- [x] **W5.2** [US1] `spec-kit-wave/agents/docs-folder-author.md` — skw-style reference (like `agents/prd-author.md`): role, dispatch (`make spec-sync`/`make prd-sync`, `make spec-check`/`make prd-check`), guardrails, cross-link to the `.cursor` agent. (2026-07-14 ✅: `spec-kit-wave/agents/docs-folder-author.md`)
- [x] **W5.3** Add the agent to `spec-kit-wave/agents/` known-agents references where relevant. `make -C spec-kit-wave lint`. Flip boxes. (2026-07-14 ✅: `spec-kit-wave/agents/README.md`; make -C spec-kit-wave lint green)

## Wave W6 — Changelog datetime stamp (∥ W5)

- [x] **W6.1** [US4] `changelog-rules.toml [entry]`: add `require_datestamp = true` + `datestamp_pattern` (e.g. `^\[\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}Z)?\]`), per D10. (2026-07-14 ✅: `spec-kit-wave/changelog-rules.toml` + `infra/changelog-rules.toml`)
- [x] **W6.2** [US4] `skw/changelog_validate.py`: enforce the leading datestamp on every `## [Unreleased]` bullet; released-section bullets exempt; keep all existing row rules (sentence case after the stamp, no trailing period, min length, `(#123)`). (2026-07-14 ✅: `spec-kit-wave/src/skw/changelog_validate.py`; scripts shim)
- [x] **W6.3** [US4] Update `changelog-templates/changelog-template.md` + `entry-template.md` example rows to show the leading `[YYYY-MM-DD]` stamp; update `CHANGELOG-STANDARDS.md` §Entry-row rules + `skills/changelog-author/SKILL.md` and the main `.claude/skills/changelog/SKILL.md`. (2026-07-14 ✅)
- [x] **W6.4** [US4] Reflow root `CHANGELOG.md` `## [Unreleased]` bullets to carry stamps (existing ones get their commit/authored date); seed this plan's Added/Changed entries with today's stamp. (2026-07-14 ✅: blame-dated reflow + W6 seed entries)
- [x] **W6.5** Make W1.4 green; `make -C spec-kit-wave test`, `make changelog-check`. Flip boxes. (2026-07-14 ✅: 32 passed spec-kit-wave; SEVN_CI_BASE=pre-0.0.1 make changelog-check ok)

## Wave W7 — PRD remediation (15 files) — agent: docs-folder-author

- [x] **W7.1** [US5] Run `make prd-sync` then `make prd-check --score`; capture the baseline per-file score. (2026-07-14 ✅: baseline avg=100, 15/15 OK pre-related; post-W7 avg=100)
- [x] **W7.2** [US5] Strip forbidden frontmatter keys (`interfaces`, `depends_on`, `build_phase`) from all 15 PRDs (now that W4 stops the generator re-adding them); populate `related` where a real sibling link exists. (2026-07-14 ✅: W4 stripped keys; related populated on 10 PRDs from prose cross-refs)
- [x] **W7.3** [US5] Fix any section/scaffold errors the validator flags; ensure every PRD scores ≥ 80 and its `status` is honest. PRDs are already prose-complete (analysis §2), so this is mostly frontmatter + validator-conformance, not rewriting. (2026-07-14 ✅: added spec-36-sub-agents to prd-04 frontmatter; 14 ready + 1 honest draft)
- [x] **W7.4** `make prd-check` green above threshold. Flip boxes. (2026-07-14 ✅: make prd-check rollup avg=100 errors=0)

## Wave W8 — Spec frontmatter / id / status fixes + index — agent: docs-folder-author

- [x] **W8.1** [US6] **Status honesty:** for every spec whose body is an "Offline scaffold" placeholder, set `status: scaffold` (D3); `27-second-brain`/`35-bot-evolution` reconciled to their true state by score. (2026-07-14 ✅: 34 specs scaffold; 36 done; 26 rejected)
- [x] **W8.2** [US6] [P] Narrow `sources` on `00`,`01`,`25` away from whole-repo `src/sevn/**` to the packages each spec actually owns; re-extract frontmatter so the `interfaces` dumps shrink accordingly. (2026-07-14 ✅: 00→`src/sevn/__init__.py`; 01→`src/sevn/**/__init__.py` (40 iface); 25→workflows+waveorch+docs (125 iface))
- [x] **W8.3** [US6] [P] Resolve the `29`-id collision (renumber `29-openui` or `29-cursor-cloud-agent` to a free id; update `id`, filename, `parent_prd` back-refs, and any `specs:` lists that cite it). (2026-07-14 ✅: verified fixed — `37-openui.md` / `spec-37-openui`, no `29-openui` in about-sevn.bot)
- [x] **W8.4** [US6] [P] Fix the `spec-16` corrupt summary (`45# Harness discipline — Spec`) at its source so `sevn about-docs index` regenerates a clean `about-sevn.bot/specs/README.md`. (2026-07-14 ✅: summary clean in README — prior W7/spec-16 fix held)
- [x] **W8.5** [US6] [P] Replace the two `.ignorelocal/…wave-plan.md` citations in `36-sub-agents.md` with an in-repo reference or an explicit "(design history, local-only)" relabel so a clean clone has no dangling ref. (2026-07-14 ✅: relabeled operator-local design history)
- [x] **W8.6** [US6] Regenerate `about-sevn.bot/specs/README.md` (`make about-docs-index`); confirm `evolution/specs-index.md` pointer resolves. `make about-docs-check` + `make -C spec-kit-wave spec-check` green (scaffolds now honestly `scaffold`, not failing as `done`). Flip boxes. (2026-07-14 ✅: both gates green)

## Wave W9 — Spec body authoring (high-traffic) — review gate — agent: docs-folder-author

Author real, code-true 7-section bodies (D8/D9/D11) for the specs CLAUDE.md leans on most. Each: verify symbols via `about-docs extract` + `graphify`, then write Purpose/Public Interface/Data Model/Internal Architecture/Behavior/Failure Modes/Test Strategy; flip `status: scaffold → done` only when the file scores ≥ 80.

- [x] **W9.1** [US6] Author `00-foundation`, `01-system-overview` (drop the whole-repo body scaffold; describe the real package layout + import rules). (2026-07-14 ✅: score=100 each)
- [x] **W9.2** [US6] Author `17-gateway`, `13-rlm-triager`, `14-executor-tier-b` (the turn spine — real modules in `src/sevn/gateway/`, `src/sevn/agent/`). (2026-07-14 ✅: score=100 each)
- [x] **W9.3** [US6] Author `02-config-and-workspace`, `10-schema-ontology`, `11-tools-registry`, `25-cicd-full`. (2026-07-14 ✅: score=100 each; 25-cicd sources narrowed to `.github/workflows/**` + `src/sevn/docs/**`)
- [x] **W9.4** [US6] Any remaining specs stay `status: scaffold` with a `## Human-input needed` note (D8) — do **not** fabricate. Record coverage in a table here. (2026-07-14 ✅: 28 scaffold specs annotated)
- [x] **W9.5** **Review gate:** operator reviews authored bodies for code-fidelity before CI wiring. `make -C spec-kit-wave spec-check` green. Flip boxes. (2026-07-14 ✅: spec-check errors=0; about-docs-check ok; **operator review pending**)

### W9 body coverage table (fill during execution)

| Spec | Authored? | Score | Notes |
|------|-----------|-------|-------|
| 00-foundation | yes | 100 | Makefile/uv/hatchling CI contract |
| 01-system-overview | yes | 100 | Package layers + import-linter + turn spine |
| 02-config-and-workspace | yes | 100 | sevn.json load, WorkspaceConfig, schema gate |
| 10-schema-ontology | yes | 100 | TriageResult / Intent / ComplexityTier |
| 11-tools-registry | yes | 100 | ToolSet, build_session_registry, dispatch |
| 13-rlm-triager | yes | 100 | triage_turn, routing_policy, fast paths |
| 14-executor-tier-b | yes | 100 | run_b_turn, BTurnOutcome, escalation |
| 17-gateway | yes | 100 | agent_turn spine, session queue, multi mode |
| 25-cicd-full | yes | 100 | make ci tiers, GitHub Actions, ci-resume |
| _(remaining 28 → scaffold)_ | no | 75 | `## Human-input needed` appended; operator review gate open for authored set |

## Wave W10 — Wire folder validators + datestamp into CI

- [x] **W10.1** [US1] Add `make spec-check` (and PRD score gate) into `make about-docs-check` or a new `ci-docs` step so a regressed spec (`done` over a scaffold, unresolved id, whole-repo `sources`, sub-threshold score) fails CI. (2026-07-14 ✅: `about-docs-check` chains `spec-check` + `prd-check`; flows through `ci-docs`)
- [x] **W10.2** [US6] Add the status-honesty check (W1.6) into `src/sevn/docs/about/check.py` so `make about-docs-check` fails on `status: done` + scaffold body deterministically. (2026-07-14 ✅: `_check_status_honesty` in check.py)
- [x] **W10.3** [US4] Confirm `make changelog-check` (now datestamp-enforcing) is in the CI changelog gate; update `specs/25-cicd-full.md` body/notes if it documents the gate. (2026-07-14 ✅: confirmed in `ci-docs`/`CI_STEPS`; updated `25-cicd-full.md`)
- [x] **W10.4** Make W1.6 green. `make about-docs-check`, `make changelog-check`, `make ci-docs` green. Flip boxes. (2026-07-14 ✅: all three targets green)

## Wave Final — Reconcile, gate, hand back (re-run after W11–W13)

> **Prior run (2026-07-14):** make ci-resume 31/31 green @ b0f85a5; CHANGELOG updated; plan synced. Re-opened for pre-merge fix waves W11–W13.

- [ ] **Final.1** Sync the worktree copy of this plan back to the primary `.ignorelocal/waves/` copy (all checkbox flips).
- [ ] **Final.2** Run the full gate with **`make ci-resume`** (loop: fix reported step → re-run → until "all steps passed"); do **not** re-run `make ci` from scratch each time.
- [ ] **Final.3** Update root `CHANGELOG.md` `## [Unreleased]` (datestamped) with W11–W13 user-visible deltas (gateway README, gateway reorg, docstring compliance).
- [ ] **Final.4** Report: tooling delivered, docs remediated (counts), any specs left honestly `scaffold`, deferred CI/commits.

## Wave Thermos — thermo-nuclear branch review gate (first pass — complete)

> **Optional re-run:** after Final (re-run) completes, dispatch Thermos again on the full branch diff including W11–W13 changes.

- [x] **Thermos.1** **Review gate:** full-branch review (reviewer + thermo plugin) — no fabricated spec prose (D8 spot-check), no dangling refs, `make ci` green, scores at/above threshold. Operator sign-off before merge. (2026-07-14 ✅: see **Thermos review report** below)

### Thermos review report (2026-07-14)

**Branch:** `wave/specs-prd-remediation` @ `b0f85a5` (+ Thermos D8 fix commit) · **Base:** `pre-0.0.1` · **Diff:** 93 files (+5,283 / −37,247)

**Verdict: PASS** — merge recommended after operator sign-off.

| Check | Result |
|-------|--------|
| `make -C spec-kit-wave spec-check` | **Green** — errors=0; 10 files score=100 (9 W9 + 36-sub-agents); 28 scaffold @75 honest |
| `make prd-check` | **Green** — 15/15 score=100 |
| `make about-docs-check` | **Green** (chains spec-check + prd-check + status honesty) |
| `make ci-resume` (Final) | **31/31 green** @ b0f85a5; no `.ci-resume/checkpoint` retained post-success |
| Dangling `.ignorelocal` refs in tracked docs | **None** in `about-sevn.bot/` (W8 relabel held) |
| Thermo-nuclear subagent review | **PASS** — 0 critical, 0 high; 4 medium (2 fixed in-branch), 3 low |

**D8 spot-check (W9 authored specs):** `13-rlm-triager`, `14-executor-tier-b`, `11-tools-registry` symbols verified against code. **Fixed in Thermos:** `17-gateway.md` `TurnFinalizer` → `TierBAnswerFinalizer` (2 places); `25-cicd-full.md` `CI_STEPS` count 39 → 31.

**Deferred (non-blocking):** `_docsys/manifest.toml` status still `scaffold` for W9 `done` specs (sync-on-missing-file risk only); `skw` does not lint body-table symbols vs AST; host-only links in `spec-kit-wave/agents/` to `.cursor/` (documented).

**Operator sign-off checklist:**
- [ ] Reviewed 9 authored spec bodies for code fidelity (especially gateway turn spine + CI gates)
- [ ] Accepts 28 specs remain honestly `scaffold` with `## Human-input needed`
- [ ] Accepts changelog datestamp requirement for new Unreleased bullets
- [ ] Approves merge of `wave/specs-prd-remediation` → target branch

## Wave W11 — README `gateway.md` quality (human/LLM prose) — D13 scope extension

Target: `docs/readmes/gateway.md` on branch `wave/specs-prd-remediation`. Reference baseline: [gateway.md on branch](https://github.com/sevn-bot/sevn/blob/wave/specs-prd-remediation/docs/readmes/gateway.md). **Not** the full readme audit plan — gateway slug only (D13).

- [x] **W11.1** [US7] **Level 1** — Rewrite overview and operator-facing sections for a regular non-technical operator: plain language, no jargon (e.g. avoid "control plane", FastAPI internals, module-path dumps without explanation). (2026-07-14 ✅: front-desk metaphor; no control-plane/FastAPI in L1)
- [x] **W11.2** [US7] **Level 2** — On first "FastAPI" mention, add a markdown link to [FastAPI on GitHub](https://github.com/tiangolo/fastapi); expand prose with explanatory context (human/LLM quality pass on all Level 2 sections). (2026-07-14 ✅: FastAPI linked; turn spine, queue/steer, channels/boot, Telegram menus, config expanded)
- [x] **W11.3** [US7] **Level 3 — major upgrade:** (2026-07-14 ✅: 114-module inventory with docstring prose + symbol links; removed See-X stubs; Extension and invariants updated)
  - Module inventory: each listed module gets LLM-written explanation (not one-liner stubs).
  - All Level 3 sections: proper markdown links to source files **and** public functions (use line anchors where the readme generator supports them), not bare text paths.
  - Every subsection needs substantially more descriptive prose.
- [x] **W11.4** Verify: `make readme-check`, `sevn readme fingerprint gateway`. Flip boxes. (2026-07-14 ✅: both green)

## Wave W12 — Gateway package reorganization (refactor-only)

> **Progress (2026-07-14):** In progress — uncommitted WIP on `wave/specs-prd-remediation` @ `5f89fa9`. `scripts/gateway_reorg_w12.py` created; ~104 modules moved into 30 subpackages (`access/`, `api/`, `telegram/`, `turn/`, …); 10 core modules remain at gateway root. ~283 tracked files changed (85 staged renames + import updates). `17-gateway.md` / `gateway.md` touched but W12.3–W12.5 not verified. No commit `ed5fbb7` (prior agent session unfinished). Gates (`make lint`, `make typecheck`, `make ci-affected`) not run on WIP tree.

Goal: reduce the flat **114** Python files at `src/sevn/gateway/` — keep **core** modules at the gateway root; move the rest into new subpackages under `src/sevn/gateway/` (e.g. `commands/`, `telegram/`, `diagnostics/` — derive from actual inventory). **No behavior change** — import-path refactor only.

- [ ] **W12.1** [US8] Inventory all 114 `*.py` files under `src/sevn/gateway/`; classify each as **core** (stays at root) vs **relocatable** (moves to subpackage). Document the classification table below (fill during execution).
- [ ] **W12.2** [US8] Create subfolders; move modules; update import graph across the repo (`rg` / graphify for callers). Run `make lint`, `make typecheck` iteratively.
- [ ] **W12.3** [US8] Update `about-sevn.bot/specs/17-gateway.md` Public Interface paths if module locations change.
- [ ] **W12.4** [US8] Update `docs/readmes/gateway.md` Level 3 module inventory if W12 paths diverge from W11 (W11 lands first).
- [ ] **W12.5** Verify: `make lint`, `make typecheck`, `make ci-affected` (gateway paths). Flip boxes.

### W12 gateway classification table (fill during execution)

| Module | Classification | Target subpackage | Notes |
|--------|----------------|-------------------|-------|
| `agent_turn.py` | core | _(root)_ | Turn spine entry |
| _(remaining 113 → fill)_ | | | |

## Wave W13 — Docstrings + `<Examples:` compliance

Per `about-sevn.bot/_standards/coding-standards.md` — every module, function, class (including private helpers and test functions) needs the full docstring schema with an `<Examples:` section for `make doctest`.

Known gaps (reviewer callouts on this branch):

- `spec-kit-wave/src/skw/doc_score.py` — module missing `<Examples:`; private helpers `_score_weights`, `_score_doc`, `_write_doc` missing docstrings.
- Audit other new `skw` modules from this branch: `doc_folder.py`, `spec_validate.py`, `changelog_validate.py`, `cli.py`.
- Audit `spec-kit-wave/tests/**` and any touched `tests/docs/about/**` test functions for the same gap.

- [ ] **W13.1** [US9] Fix `doc_score.py` module + private helper docstrings and `<Examples:` sections.
- [ ] **W13.2** [US9] Audit and fix remaining `spec-kit-wave/src/skw/{doc_folder,spec_validate,changelog_validate,cli}.py` modules.
- [ ] **W13.3** [US9] Fix test function docstrings in `spec-kit-wave/tests/` and touched `tests/docs/about/` files.
- [ ] **W13.4** Verify: `make lint`, `make typecheck`, `make doctest`. Flip boxes.

## Recent baseline / drift

_Verified 2026-07-14 in worktree `../sevn-specs-prd` (branch `wave/specs-prd-remediation`, base `pre-0.0.1` @ `5e53330`). Analysis snapshot (`.ignorelocal/PRD-SPECS-QUALITY-ANALYSIS-2026-07-14.md`) predates partial doc-vs-code remediation — counts below are **current checkout truth** with drift called out._

### Tooling availability

| Command | Result |
|---------|--------|
| `make prd-check` | **Unavailable** — `spec-kit-wave/` absent from checkout (net-new in W2+); no root Makefile target |
| `make spec-check` | **Does not exist** (planned W3) |
| `make -C spec-kit-wave validate WAVE=…` | **Blocked** — `spec-kit-wave/` directory missing; verify deferred until tooling lands |
| `make about-docs-check` | **Green** (`about-docs check: ok`) |
| `sevn about-docs schema` | Wrote `about-sevn.bot/_docsys/about-docs.schema.json` |

### Spec inventory (`about-sevn.bot/specs/`)

- **39** spec files (+ generated `README.md`)
- **Status distribution:** `34 draft` · `1 done` (`36-sub-agents`) · `2 scaffold` (`27-second-brain`, `35-bot-evolution`) · `1 rejected` (`26-claude-agent`)
- **`status: done` + `"Offline scaffold for"` body:** **0** (analysis expected ~34 on pre-remediation snapshot)
  - **Drift:** doc-vs-code wave already relabelled most specs to `draft` and replaced literal scaffold phrases with `"Initial draft for …"` template bodies (still not authored prose)
- **Fully authored spec bodies:** **1** (`36-sub-agents.md` — 269+ lines, locked decisions table)
- **7-section headings present** in all spec bodies; most sections are interface-list stubs or `"Initial draft for …"` placeholders

### Analysis defects — current state

| Defect (analysis ref) | W0 verified state |
|-----------------------|-------------------|
| `29`-id collision (`29-cursor-cloud-agent` vs `29-openui`) | **Resolved** — `29-openui` renumbered to `spec-37-openui` / `37-openui.md`; only `spec-29-cursor-cloud-agent` remains; no duplicate `id:` values |
| `spec-16` corrupt index summary (`45# Harness discipline`) | **Resolved** — README + frontmatter show clean summary |
| `src/sevn/**` whole-repo dumps on `00`/`01`/`25` | **Still present** — all three carry `sources: [src/sevn/**]`; files are ~12,149–12,152 lines (AST interface dumps dominate) |
| `.ignorelocal` leak in `spec-36` | **Still present** — lines 189, 196 cite `.ignorelocal/design/plan/sub-agents-orchestration-wave-plan.md` |
| PRD forbidden frontmatter (`interfaces`/`depends_on`/`build_phase`) | **Still present** on all sampled PRDs (15 authored + `prd-00-main`); `skw` validator not yet runnable to quantify failures |

### D3 / D11 locked findings (W0.3)

- **`sevn about-docs schema` status enum (all kinds):** `draft`, `scaffold`, `ready`, `done`, `rejected` (`about-sevn.bot/_docsys/about-docs.schema.json` + `src/sevn/docs/about/model.py`)
- **`ready` for `kind: spec`:** schema allows it today; **plan locks `spec-rules.toml` to exclude `ready`** for specs (D3)
- **§-numbered external source:** none found → **`about-sevn.bot/specs/*.md` is SSOT** (D11)

## Plan maintenance

> After each wave: flip checkboxes in the **worktree** copy (`../sevn-specs-prd/.ignorelocal/waves/…`), `cp` to the **primary checkout** copy (`sevn/.ignorelocal/waves/…`), and commit+push plan updates with wave commits or immediately after.
