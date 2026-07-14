<!-- template: slug=proxy-egress profile=subsystem — see _templates/README.md for the markup contract -->

# <Title — "Egress proxy — <one-line scope>">

<!-- fill: badge row (spec/source/index), left as the pipeline stamps them -->

> **Summary.** <one sentence; mirror the manifest summary>

## Level 1 — Overview (non-technical)

<!-- fill: 1–2 short paragraphs. Shared-secret-guarded outbound proxy; tier executors
     never hold provider API keys. Routes for LLM, web fetch/search, integrations.
     Operator terms only in L1. -->

## Level 2 — How it works (technical)

<!-- fill: subsystem-specific subsections. Expected for proxy-egress:
       ### Route table — /llm/*, /web/*, /integration POST handlers
       ### Shared-secret auth — X-Sevn-Proxy-Token / SEVN_PROXY_SHARED_SECRET
       ### Credential injection — resolve_request_credential per route
       ### Client transport — agent/providers/transport.py _ProxyTransport wire shapes
       ### Configuration — proxy_url, ProcessSettings, sevn.json pairing
     Cite real symbols. D21 links throughout. -->

### Key modules

<!-- fill: bullet list of load-bearing modules with a one-line role each -->

## Level 3 — Deep dive (low-level, technical)

<!-- generated: pipeline-owned below until References. Do not hand-author. -->

### Module inventory

### Extension and invariants

<!-- /generated -->

## References
