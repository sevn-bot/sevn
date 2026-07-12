# Brand assets manifest — README pipeline

Tracked inventory for `docs/brand/assets/` and wired logos under `styles/sevn/style/`. Checker treats `placeholder` as `TODO` warning; `present` must resolve to a committed file.

| Asset | Path | Status | Intended content | Dimensions / notes |
|-------|------|--------|------------------|-------------------|
| Logo primary (light) | `styles/sevn/style/logos/logo-primary.svg` | **present** | Wordmark on light backgrounds | SVG lockup; embeds `logo-mark.svg` |
| Logo primary (light JPG) | `styles/sevn/style/logos/logo-primary.jpg` | **present** | Raster wordmark for README / social | JPG; `<picture>` light fallback |
| Logo all-white (dark) | `styles/sevn/style/logos/logo-all-white.svg` | **present** | Wordmark on dark backgrounds | SVG; `<source media="(prefers-color-scheme: dark)">` |
| Logo mark (SVG) | `styles/sevn/style/logos/logo-mark.svg` | **present** | Compact ASCII-style 7 mark | SVG; navbars, webchat, favicon contexts |
| Logo mark (PNG) | `styles/sevn/style/logos/logo-mark.png` | **present** | Raster mark | PNG; terminal ASCII, bundled wheel asset |
| Logo dark bg | `styles/sevn/style/logos/logo-dark-bg.svg` | **present** | Wordmark for dark cards | SVG; Mission Control / wizard dark theme |
| Avatar GitHub (SVG) | `styles/sevn/style/logos/avatar-github.svg` | **present** | Org/repo avatar source | SVG; export to JPG for GitHub upload |
| Avatar GitHub (JPG) | `styles/sevn/style/logos/avatar-github.jpg` | **present** | Raster avatar for GitHub UI | JPG; org profile + repo social avatar |
| Favicon | `styles/sevn/style/logos/favicon.svg` | **present** | Favicon | SVG |
| Favicon white bg | `styles/sevn/style/logos/favicon-white-bg.svg` | **present** | Favicon on white | SVG |
| Color tokens | `styles/sevn/style/tokens/colors.css` | **present** | CSS custom properties | Source of truth for badge hex |
| Hero screenshot | `docs/brand/assets/hero.png` | **placeholder** | Mission Control + channel product shot | ~1280×720; W1 commits labeled SVG/PNG |
| Demo loop | `docs/brand/assets/demo.gif` | **placeholder** | Short operator workflow loop | GIF or poster + external link |
| Demo poster | `docs/brand/assets/demo-poster.png` | **placeholder** | Video poster frame | 1280×720 |
| Architecture diagram | `docs/brand/assets/architecture.svg` | **placeholder** | Turn spine from ARCHITECTURE.md | Theme-aware SVG |
| Social preview | `docs/brand/assets/social-preview.png` | **placeholder** | Repo social card | 1280×640; brand gradient + wordmark |
| Per-subsystem chart | `docs/brand/assets/charts/*.svg` | **placeholder** | Optional mono-blue charts | Chart palette from `colors.css` |

## Placeholder policy

- W1 commits real placeholder files (non-broken SVG/PNG with visible `PLACEHOLDER` label).
- W5 replaces highest-value assets; MANIFEST status flips to `present` when swapped.
- READMEs reference placeholders by stable path — never omit images until assets exist.

## Theme-aware logo wiring (README snippet)

```html
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="styles/sevn/style/logos/logo-all-white.svg">
  <img src="styles/sevn/style/logos/logo-primary.jpg" alt="sevn.bot" width="280">
</picture>
```

Paths are repo-root-relative (GitHub resolves from repository root for root `README.md`).

## GitHub org + repo branding

| Surface | Upload file | Source in repo |
|---------|-------------|----------------|
| Organization profile picture | `avatar-github.jpg` | `styles/sevn/style/logos/avatar-github.jpg` |
| Repository social preview (Settings → General) | `logo-primary.jpg` or custom 1280×640 export | `styles/sevn/style/logos/logo-primary.jpg` until `social-preview.png` lands |
| Favicon (GitHub Pages / help site) | `favicon.svg` | copied to `about-sevn.bot/assets/logos/` via `make about-site` |

SVG sources (`avatar-github.svg`, `logo-mark.svg`, `logo-primary.svg`) are authoritative for design; raster JPG/PNG variants are for platforms that require bitmap uploads.
