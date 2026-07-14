<!-- template: slug=secrets profile=subsystem — see _templates/README.md for the markup contract -->

# <Title — "Secrets — <one-line scope>">

<!-- fill: badge row (spec/source/index), left as the pipeline stamps them -->

> **Summary.** <one sentence; mirror the manifest summary>

## Level 1 — Overview (non-technical)

<!-- fill: 1–2 short paragraphs. What secrets are for (backends, chain, TTL,
     fingerprint confirmation). Gateway-vs-proxy trust split in operator terms.
     Mission Control reveal for owner audit. No bare src/ paths in L1. -->

## Level 2 — How it works (technical)

<!-- fill: subsystem-specific subsections. Expected for secrets:
       ### Gateway vs egress proxy — which process resolves which keys
       ### Backend chain and TTL — secrets_chain_from_workspace, write_targets
       ### Mission Control reveal API — config aliases + store entries (owner+CSRF)
       ### Fingerprint confirmation — fingerprint_sha256_hex for CLI
       ### Configuration (`sevn.json` → `secrets_backend`) — the knobs
     Cite real symbols (verified). D21 links: file → top, symbol → #L<line>. -->

### Key modules

<!-- fill: bullet list of load-bearing modules with a one-line role each -->

## Level 3 — Deep dive (low-level, technical)

<!-- generated: pipeline-owned below until References. Do not hand-author. -->

### Module inventory

### Extension and invariants

<!-- /generated -->

## References
