# Curated README templates

Each **curated** README (`curated = true` in [`../manifest.toml`](../manifest.toml)) is
validated against a slug-specific template in this directory. Templates pin the
**outline** — the stable heading skeleton a good doc for that subsystem has — while
leaving prose to a human or the [`readme-curator`](../../../.claude/agents/readme-curator.md)
agent.

## How a template maps to a README

- Template path defaults to `docs/readmes/_templates/<slug>.md`. Override with a
  `template = "docs/readmes/_templates/foo.md"` key on the manifest entry.
- `sevn readme check` (→ `make readme-check`) runs `validate_against_template` for
  every curated entry: the README must contain every template heading, at the same
  level, in the same relative order (a **subsequence** — extra headings such as the
  pipeline's per-module `###` sections are allowed between anchors).

## Markup contract

| Markup | Meaning |
|---|---|
| A real markdown heading (`##  Foo`) | **Required anchor** — must appear in the README, in order. |
| A heading whose text contains `<`, `…`, or `{{` | **Wildcard** — matches any heading of that level (used for the `# <Title>` line). |
| `<!-- fill: … -->` | Guidance for the agent/author. Ignored by the validator. |
| `<!-- generated -->` … `<!-- /generated -->` | Region owned by the offline pipeline (L3 module inventory). Anchor headings inside are still required; the variable per-module headings the pipeline emits are extra and ignored. Do **not** hand-author these regions. |

## Authoring and regeneration flow

1. Source changes under a curated slug's `source_globs`.
2. The `sevn-readme-sync` pre-commit hook stamps the fingerprint and — when
   `SEVN_README_AGENT=1` (or by default per repo policy) — runs
   `sevn readme curate <slug>`, which feeds the diff + this template + the current
   README to the runner (`cursor-agent` / `claude`) to update Levels 1–2, then
   re-validates and stages the result.
3. To drive it by hand: `sevn readme curate <slug>` (add `--dry-run` to print the
   assembled prompt without calling a model).

Promote a slug-specific subsection to a hard requirement by writing it as a real
heading in that slug's template (rather than as `<!-- fill: … -->` guidance).
