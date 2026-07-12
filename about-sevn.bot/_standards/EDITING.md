# Editing the help site

## Layout

| Path | Purpose |
|------|---------|
| `_sources/*.yaml` | Hand-written titles, summaries, body HTML, and optional overrides |
| `_templates/*.html.j2` | Jinja layouts — change structure here |
| `*.html` (root) | **Generated** — do not edit by hand |
| `assets/` | **Generated** — copied from `styles/sevn/style/` on build |
| `Telegram Menu.html` | Developer reference — hand-maintained; structural sync via `make telegram-menu-docs-check` |
| `Mission Control.html` | Developer reference — hand-maintained; structural sync via `make mission-control-docs-check` |

## Commands

```bash
make about-site                 # regenerate HTML + assets
make about-site-check           # fail if committed HTML is stale or impure
make telegram-menu-docs-check   # fail if Telegram Menu.html drifts from live keyboards
make telegram-menu-docs-scaffold  # insert WIP/TODO stubs for missing sections/buttons/tiles
make mission-control-docs-check   # fail if Mission Control.html drifts from tab_registry
make mission-control-docs-scaffold  # insert WIP/TODO stubs for missing groups/tabs
make agent-context-manifest-check   # fail if slot-order manifest drifts from code
make agent-context-manifest-generate  # regenerate infra/agent-context.manifest.json
```

When agent prompt slot order changes (`context_manifest.py`, executors, triager prompt):

1. `make agent-context-manifest-generate`
2. `make about-site`
3. Commit golden manifest + generated `agent-context.html`

Pre-commit runs `telegram-menu-docs-check` when menu code or `Telegram Menu.html` changes, `sevn-mission-control-docs` when `tab_registry.py` or `Mission Control.html` changes, and `about-site-check` when catalog copy or templates change.

Agent checklists for these flows live in the local-only design docs.

## Adding a page

1. Add `_sources/new-page.yaml` and `_templates/new-page.html.j2`.
2. Register the slug in `scripts/build_about_site.py` (`USER_PAGES` and build loop).
3. Add nav entry in `_nav_pages()` inside the same script.
4. Run `make about-site` and commit.
