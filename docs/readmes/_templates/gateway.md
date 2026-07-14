<!-- template: slug=gateway profile=subsystem — see _templates/README.md for the markup contract -->

# <Title — "Gateway — <one-line scope>">

<!-- fill: badge row (spec/source/index reference-style badges), left as the pipeline stamps them -->

> **Summary.** <one sentence; mirror the manifest summary>

## Level 1 — Overview (non-technical)

<!-- fill: 1–2 short paragraphs, operator terms. What the gateway is (the long-running
     control plane), what starts it, that every channel connects here, that it owns
     sessions/queues/scanner and dispatches to the agent tiers, and that provider keys
     never load in-process (egress proxy). No src/ paths, no spec numbers in L1. -->

## Level 2 — How it works (technical)

<!-- fill: subsystem-specific subsections. Expected for gateway:
       ### Turn spine        — numbered inbound→scan→session→dispatch→outbound flow, real symbols
       ### Queue and steer modes — gateway.queue_mode behaviour
       ### Channels and boot — adapters + boot registry
       ### Configuration (`sevn.json` → `gateway`) — the knobs
     Cite real symbols/modules (verified to exist). -->

### Key modules

<!-- fill: bullet list of load-bearing modules with a one-line role each -->

## Level 3 — Deep dive (low-level, technical)

<!-- generated: the offline pipeline owns everything below until References.
     Do not hand-author the module inventory or per-module sections. -->

### Module inventory

### Extension and invariants

<!-- /generated -->

## References
