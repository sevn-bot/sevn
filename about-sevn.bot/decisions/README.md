# Decisions (ADRs)

Architecture Decision Records for sevn.bot, numbered `NNNN-slug.md` in
chronological order.

**This directory is intentionally non-published.** The about-site
(`about-sevn.bot/`) only builds pages explicitly registered as an `[[entry]]`
in [`_docsys/manifest.toml`](../_docsys/manifest.toml); this directory has no
manifest entry. Its paths are also kept **out of**
[`_docsys/allowed-refs.txt`](../_docsys/allowed-refs.txt) so published docs
cannot cite ADRs into the public site. Do not add either — see
[`0001-adopt-mattpocock-skills-into-spec-kit-wave.md`](0001-adopt-mattpocock-skills-into-spec-kit-wave.md)
(decision D3) and `docs/mattpocock-skills-integration.md` §5.5.3 for why.

Paths are resolved by `spec-kit-wave/scripts/context_paths.py` and
`skw.toml [context].decisions_dir` — never hardcoded in a skill.
