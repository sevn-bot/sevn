# Changelog standards (sevn.bot)

Normative contract for root `CHANGELOG.md`. Enforced deterministically by
`skw.changelog_validate` (`make changelog-check`, pre-commit `changelog-staged-check`).

**Rules file:** [`changelog-rules.toml`](changelog-rules.toml)
**Templates:** [`changelog-templates/`](changelog-templates/)

## File shape

- [Keep a Changelog 1.1](https://keepachangelog.com/en/1.1.0/) with a rolling `## [Unreleased]` section.
- Six category subheadings under Unreleased (may be empty): **Added**, **Changed**, **Deprecated**, **Removed**, **Fixed**, **Security**.
- At release, move Unreleased bullets into a new dated version section (`## [x.y.z] - YYYY-MM-DD`). Released bullets do **not** require a datestamp.

## Entry-row rules (Unreleased only)

Every bullet under `## [Unreleased]` must:

1. **Leading datestamp** — start the body (after `- `) with `[YYYY-MM-DD]` (date-only default). Optional time suffix `[YYYY-MM-DDTHH:MMZ]` is allowed. Leading placement avoids collision with `(#123)` refs and the no-trailing-period rule.
2. **Bullet marker** — markdown list row starting with `- `.
3. **Sentence case** — uppercase first letter of the prose **after** the datestamp (unless the prose opens with a `` `code` `` span).
4. **No trailing period** — `...` ellipsis is allowed.
5. **Minimum length** — at least 12 characters in the full bullet body (stamp + prose).
6. **Issue refs** — `(#123)` at the end when citing a PR/issue; bare `#123` inside backticks is wrong.

### Good

```markdown
- [2026-07-14] New `--retry` flag on `sevn onboard` to resume an interrupted setup (#412)
- [2026-07-14] Mission Control owner login resolves `${SECRET:…}` refs at boot
```

### Bad

```markdown
- New feature without a datestamp
- [2026-07-14] added lowercase after stamp.
- [2026-07-14] Too short.
```

## Diff gate

When `src/sevn/**` or `scripts/**` changes (excluding paths in `diff_gate.exempt_globs`), the branch or staged commit must add at least one **new** Unreleased bullet vs the base/HEAD changelog.

Escape hatch: `changelog: skip` trailer in the commit message (or `SEVN_CHANGELOG_SKIP=1` for staged gate).

## Authoring workflow

1. Draft from the diff — impact first, mechanism never.
2. Pick the best Keep-a-Changelog category.
3. Prefix with today's `[YYYY-MM-DD]` stamp.
4. Stage `CHANGELOG.md` with code changes before commit.
5. Run `make changelog-check` (deterministic) before merge; `make changelog-eval` is advisory only.

See also: [`skills/changelog-author/SKILL.md`](skills/changelog-author/SKILL.md) and repo `.claude/skills/changelog/SKILL.md`.
