# sevn.bot brand kit for documentation

> **Source of truth:** `styles/sevn/style/` — tokens, themes, logos. This tree documents how READMEs and generated docs **reuse** that brand; it does not define a second palette.

## Purpose

The README pipeline (`docs/readmes/STANDARD.md`) renders GitHub-safe markdown with a consistent product identity:

- **Colors** from `styles/sevn/style/tokens/colors.css`
- **Logos** from `styles/sevn/style/logos/`
- **Badge buttons** from `docs/brand/badges.md` (shields.io, reference-style links)
- **Placeholder assets** in `docs/brand/assets/` until operator-supplied media lands (tracked in `assets/MANIFEST.md`)

## Brand pair (locked)

| Role | Hex | Usage |
|------|-----|-------|
| Primary | `#5fb1f7` | Clear-sky blue — confident carrier; assistant accents, charts, primary CTAs |
| Accent | `#ff3b3b` | Signal red — **action/critical only** (security, kill-switch, Report Bug). Never decorative. |
| Base | `#0c0a09` | Warm slate-black — page/surface backgrounds, dark badges |

Extended tokens (success, warning, chart ramp, gradients) live in `colors.css`.

## Logo usage in READMEs

**Theme-aware header** (GitHub `<picture>` + `prefers-color-scheme`):

| Theme | File | Path |
|-------|------|------|
| Dark | All-white wordmark | `styles/sevn/style/logos/logo-all-white.svg` |
| Light | Primary wordmark (JPG) | `styles/sevn/style/logos/logo-primary.jpg` |

Other shipped logos (reference only — use where appropriate):

| Asset | Path | Typical use |
|-------|------|-------------|
| Mark (SVG) | `logo-mark.svg` | Narrow headers, webchat, navbars, Telegram branding ref |
| Mark (PNG) | `logo-mark.png` | Raster mark, terminal ASCII animation source |
| Primary (SVG) | `logo-primary.svg` | Scalable wordmark lockup (embeds mark) |
| Primary (JPG) | `logo-primary.jpg` | README light fallback, raster contexts |
| Dark bg | `logo-dark-bg.svg` | Mission Control / wizard dark theme |
| Avatar (SVG) | `avatar-github.svg` | GitHub avatar design source |
| Avatar (JPG) | `avatar-github.jpg` | Upload to GitHub org profile picture |
| Favicon | `favicon.svg`, `favicon-white-bg.svg` | Site/favicon slots |

**Width guidance:** root README logo ≈ 240–320px rendered width; subsystem READMEs ≈ 120–160px or badge-only.

## GitHub org + repository

Apply branding on GitHub using committed raster exports (GitHub upload UI does not accept SVG for profile pictures):

1. **Organization** ([sevn-bot](https://github.com/sevn-bot)) — Settings → Profile → upload `styles/sevn/style/logos/avatar-github.jpg` (export of `avatar-github.svg`).
2. **Repository** ([sevn.bot](https://github.com/sevn-bot/sevn)) — Settings → General → Social preview: use `logo-primary.jpg` until `docs/brand/assets/social-preview.png` replaces the placeholder.
3. **README header** — generated from `src/sevn/docs/readme/templates/root.md.j2`; uses `logo-all-white.svg` (dark) + `logo-primary.jpg` (light).

## Docs-specific assets

Committed placeholders and future media: `docs/brand/assets/` — see `assets/MANIFEST.md`.

Hero, demo, architecture diagram, and social preview are **placeholders until W5+**; the checker reports `TODO`, not failure.

## Related docs

| Doc | Role |
|-----|------|
| `docs/readmes/STANDARD.md` | Authoring contract, profiles, generation model |
| `docs/brand/badges.md` | shields.io palette and copy-paste snippets |
| `styles/sevn/style/style-guide.html` | Interactive brand reference (local) |

## Rules

1. **Never invent colors** outside `colors.css` for badges, diagrams, or buttons.
2. **Accent red sparingly** — one critical CTA per header row maximum.
3. **GitHub-safe only** — see STANDARD.md §E (no inline `style=`, no `<script>`).
4. **Broken images forbidden** — use placeholders from `assets/` until real media exists.
