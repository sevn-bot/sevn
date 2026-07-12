# sevn.bot design system (source of truth)

Canonical CSS tokens and components for operator-facing web surfaces: web onboarding wizard, Mission Control, and webchat.

## Build into the wheel

```bash
make styles-build
```

Copies this tree to `src/sevn/ui/style/` (gitignored except `__init__.py`). `make test`, `make build`, and `make ci` run `styles-build` first.

## Consumption rules

1. **Load order:** `<link rel="stylesheet" href="/style/index.css">` first, then a surface-specific layout file only (`wizard/style.css`, `/mission/style.css`, `/webapp/style.css`).
2. **Layout-only overrides:** Surface CSS may set grid, spacing, and positioning. Do **not** introduce parallel palettes (`--bg`, `--panel`, `--accent`, etc.). Use semantic roles from `theme-dark.css` / `theme-light.css` (`--sevn-surface-*`, `--sevn-fg-*`, `--sevn-border`, …).
3. **Components:** Prefer classes from `components/` (`.btn`, `.card`, `.input`, `.sidebar`, `.chat`, …) before bespoke rules.
4. **Theme:** Tri-state `system` / `light` / `dark` via `data-theme` on `<html>`, persisted in `localStorage['sevn-theme']`. Shared helper: `src/sevn/ui/shared/theme.js`.
5. **Logos:** Use SVGs under `logos/` (served at `/style/logos/…`). Compact mark: `logo-mark.svg`; wordmark lockups: `logo-primary.svg` / `logo-dark-bg.svg`.

## Reference

- Live component gallery: `style-guide.html` (published to GitHub Pages from `main` via `.github/workflows/style-guide-pages.yml`).
- TypeScript tokens (for future React): `tokens/tokens.ts`.

## Editing

Change files here, run `make styles-build`, then verify onboarding (`sevn onboard --web`), Mission Control (`/mission/`), and webchat (`/webapp/`).
