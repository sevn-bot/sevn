# sevn.bot brand kit for documentation

> **Source of truth:** `styles/sevn/style/` — tokens, themes, logos. This tree documents how READMEs and generated docs **reuse** that brand; it does not define a second palette.

## Purpose

The README pipeline (`docs/readmes/STANDARD.md`) renders GitHub-safe markdown with a consistent product identity:

- **Colors** from `styles/sevn/style/tokens/colors.css`
- **Logos** from `styles/sevn/style/logos/`
- **Badge buttons** from `docs/brand/badges.md` (shields.io, reference-style links)
- **Placeholder assets** in `docs/brand/assets/` until operator-supplied media lands (tracked in `assets/MANIFEST.md`)

Contributors and agents should treat this file as the human-readable brand contract. When prose, generated images, or UI copy describe sevn.bot visually, start here — not from model priors or informal mascot guesses.

## The mark — ASCII-style “7”

The sevn.bot logo mark is an **abstract, ASCII-style numeral 7** — not an animal, character, or mascot.

| Element | Color (SVG fill) | Role |
|---------|------------------|------|
| Horizontal bar (top stroke) | `#fb3535` (signal red) | Action stroke — matches accent semantics |
| Diagonal / body stroke | `#4bacfb` (logo blue) | Primary carrier stroke — slightly brighter than token `--sevn-primary` (`#5fb1f7`) for contrast on dark surfaces |
| Highlight notch | `#ffffff` | Small white accent on the diagonal — do not omit or recolor arbitrarily |

The mark reads like terminal block art: two flat ink colors plus an optional white highlight. **No gradients, glows, or fills inside the mark.** Red stays the bar; blue stays the diagonal — do not swap.

The wordmark pairs **`sevn`** in heavy **Inter Tight** with **`.bot`** in **JetBrains Mono** — a deliberate domain-style suffix, not a separate mascot name.

### What the logo is **not**

- **Not a fox, wolf, canine, or any animal mascot.** Do not describe, illustrate, or generate images of sevn.bot as a furry character, spirit animal, or cartoon creature unless official brand language explicitly adds one (it has not).
- **Not a generic “AI assistant orb” or chat bubble.** Use the committed mark or wordmark lockups.
- **Not an emoji substitute.** Telegram and menus use text labels; the mark is `logo-mark.svg`, not 🦊 or similar.

If an agent or image model “helpfully” invents a mascot, **reject and restate** the ASCII-style 7 mark from `styles/sevn/style/logos/logo-mark.svg`.

## Authoritative source paths

| Asset / concern | Canonical path | Notes |
|-----------------|----------------|-------|
| Color tokens | `styles/sevn/style/tokens/colors.css` | `--sevn-primary`, `--sevn-accent`, base ramp, gradients |
| Themes | `styles/sevn/style/tokens/theme-dark.css`, `theme-light.css` | Map tokens to semantic UI roles |
| Logos (SVG/PNG/JPG) | `styles/sevn/style/logos/` | `logo-mark.svg`, `logo-primary.svg`, `logo-all-white.svg`, … |
| Design system entry | `styles/sevn/style/README.md` | Build via `make styles-build` → `src/sevn/ui/style/` |
| Interactive reference | `styles/sevn/style/style-guide.html` | Logo lockups §12, typography §4 |
| Telegram `/config` branding | `src/sevn/gateway/menu/menu_branding.py` | `SEVN_BOT_LOGO_REL = "logos/logo-mark.svg"`; root tile label `sevn.bot` |
| Terminal ASCII animation | `src/sevn/branding/logo_mark.py`, `scripts/logo_mark_ascii.py` | Raster source: `logo-mark.png`; palette from SVG/CSS |
| README generation | `src/sevn/docs/readme/brand.py` | Intro verse from `docs/brand/root-intro.toml` |
| Docs mirror (about-site) | `about-sevn.bot/assets/logos/`, `about-sevn.bot/assets/tokens/` | Synced copies for published docs — **edit `styles/sevn/style/` first** |

Do not fork palette hex values in feature code. Import CSS tokens or reference this doc.

## Brand pair (locked)

| Role | Hex | Usage |
|------|-----|-------|
| Primary | `#5fb1f7` | Clear-sky blue — confident carrier; assistant accents, charts, primary CTAs |
| Accent | `#ff3b3b` | Signal red — **action/critical only** (security, kill-switch, Report Bug). Never decorative. |
| Base | `#0c0a09` | Warm slate-black — page/surface backgrounds, dark badges |
| Surface (cards) | `#181513` | `--sevn-base-150`; terminal ASCII background default |
| Logo ink (mark only) | `#4bacfb` / `#fb3535` | Slightly tuned fills inside `logo-mark.svg` — use for mark reproduction, not general UI |
| White highlight | `#ffffff` | Mark notch only; `--sevn-white` elsewhere |

Extended tokens (success, warning, chart ramp, gradients) live in `colors.css`.

## Typography

| Role | Family | Where defined |
|------|--------|---------------|
| UI / wordmark “sevn” | Inter Tight (600 weight for headings) | `styles/sevn/style/tokens/typography.css` |
| Code / “.bot” suffix / telemetry | JetBrains Mono | Same; `--sevn-font-mono` |
| README body | GitHub default markdown | No custom webfont in generated READMEs |

Typeset **`sevn.bot`** only as Inter Tight + JetBrains Mono lockup — not all-caps “SEVN”, not a single arbitrary sans.

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

**Minimum size:** 22px for `logo-mark`, 96px wide for full lockup (see `style-guide.html` §12).

## Agent & image-generation guardrails

When agents, skills, or `media_generation` produce images, avatars, stickers, or descriptive copy about sevn.bot:

1. **Use the mark or wordmark** from `styles/sevn/style/logos/` — embed or describe the ASCII-style 7, not an invented character.
2. **Palette only:** `#5fb1f7`, `#ff3b3b`, warm slate bases (`#0c0a09`–`#26211d`), mark inks `#4bacfb` / `#fb3535`, white highlight. No purple/orange rebrands, no rainbow gradients on the mark.
3. **Accent red is critical/action only** — not decorative backgrounds, not “make it pop” filler.
4. **No mascot narrative** — never “sevn the fox/wolf/robot companion” unless the operator explicitly requests fan art outside product branding.
5. **Prefer committed assets** over pure generation for logos; if generating, constrain prompt to “flat two-color ASCII-style numeral 7 logo, red horizontal bar, blue diagonal, dark warm-gray background, no animal, no face”.
6. **Telegram/menu surfaces** are text-only tiles; reference `menu_branding.py` for labels, not inline images.

Regenerate terminal ASCII previews: `make logo-mark-ascii` (writes under `about-sevn.bot/assets/logos/` when run from repo root).

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
| `styles/sevn/style/README.md` | Design system build + consumption rules |
| `about-sevn.bot/ARCHITECTURE.md` | Agent index — links here for visual identity |

## Rules

1. **Never invent colors** outside `colors.css` for badges, diagrams, or buttons.
2. **Accent red sparingly** — one critical CTA per header row maximum.
3. **GitHub-safe only** — see STANDARD.md §E (no inline `style=`, no `<script>`).
4. **Broken images forbidden** — use placeholders from `assets/` until real media exists.
5. **No unofficial mascots** — the mark is an abstract 7; do not fox/wolf-wash product copy or generated art.
