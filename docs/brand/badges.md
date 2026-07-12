# sevn.bot — canonical badge-button palette

shields.io `for-the-badge` buttons with **reference-style links** at EOF (MarkedDown pattern). Colors derive from `styles/sevn/style/tokens/colors.css` — do not substitute third-party greens/oranges unless documenting an external license badge.

## Palette

| Role | Hex (shields.io, no `#`) | Token | Use |
|------|--------------------------|-------|-----|
| Primary CTA | `5fb1f7` | `--sevn-primary` | Docs, Quick Start, primary nav |
| Secondary | `2a7fc6` | `--sevn-primary-dark` | Architecture, secondary nav |
| Critical | `ff3b3b` | `--sevn-accent` | Report Bug, security — **max one per row** |
| Base/dark | `0c0a09` | `--sevn-base-050` | Dark neutral badges |
| Success | `6a9c78` | `--sevn-success` | CI passing, stable channel |
| Warning | `c89a52` | `--sevn-warning` | Pre-release, WIP surfaces |

## Root README — action row (centered, below logo)

```markdown
[![Docs][docs-badge]][docs-link]
[![Quick Start][quick-badge]][quick-link]
[![Architecture][arch-badge]][arch-link]
[![Report Bug][bug-badge]][bug-link]
```

## Root README — status row

```markdown
[![CI][ci-badge]][ci-link]
[![License: MIT][license-badge]][license-link]
[![Python 3.12+][python-badge]][python-link]
[![Package][package-badge]][package-link]
```

## Subsystem README — compact row

```markdown
[![Spec][spec-badge]][spec-link]
[![Source][source-badge]][source-link]
[![Index][index-badge]][index-link]
```

## Reference definitions (EOF block)

Replace `OWNER/REPO` and paths as needed.

```markdown
[docs-badge]: https://img.shields.io/badge/Docs-5fb1f7?style=for-the-badge&logo=readthedocs&logoColor=white
[docs-link]: docs/readmes/INDEX.md

[quick-badge]: https://img.shields.io/badge/Quick_Start-5fb1f7?style=for-the-badge&logo=rocket&logoColor=white
[quick-link]: #quick-start-tldr

[arch-badge]: https://img.shields.io/badge/Architecture-2a7fc6?style=for-the-badge&logo=diagramsdotnet&logoColor=white
[arch-link]: about-sevn.bot/ARCHITECTURE.md

[bug-badge]: https://img.shields.io/badge/Report_Bug-ff3b3b?style=for-the-badge&logo=githubissues&logoColor=white
[bug-link]: https://github.com/OWNER/REPO/issues

[ci-badge]: https://img.shields.io/badge/CI-6a9c78?style=for-the-badge&logo=githubactions&logoColor=white
[ci-link]: .github/workflows/ci.yml

[license-badge]: https://img.shields.io/badge/License-MIT-5fb1f7?style=for-the-badge
[license-link]: LICENSE

[python-badge]: https://img.shields.io/badge/Python-3.12+-2a7fc6?style=for-the-badge&logo=python&logoColor=white
[python-link]: pyproject.toml

[package-badge]: https://img.shields.io/badge/package-0.0.2c-c89a52?style=for-the-badge
[package-link]: pyproject.toml

[spec-badge]: https://img.shields.io/badge/Spec-2a7fc6?style=for-the-badge&logo=readthedocs&logoColor=white
[spec-link]: specs/17-gateway.md

[source-badge]: https://img.shields.io/badge/Source-src_sevn_gateway-0c0a09?style=for-the-badge&logo=github&logoColor=white
[source-link]: src/sevn/gateway/

[index-badge]: https://img.shields.io/badge/All_READMEs-5fb1f7?style=for-the-badge&logo=markdown&logoColor=white
[index-link]: docs/readmes/INDEX.md
```

## Layout notes

- Group action buttons on one line; status badges on the next.
- Separate groups with a blank line or `---` (MarkedDown Separators pattern).
- Prefer `logoColor=white` on colored badges for contrast.
- Test in a GitHub PR preview before merging — sanitization strips unsafe HTML.

## Keyboard buttons (optional, subtle nav)

```markdown
[<kbd>sevn readme check</kbd>][readme-check-link]

[readme-check-link]: #keeping-docs-current
```

Use `<kbd>` for CLI hints; shield buttons for primary CTAs.
