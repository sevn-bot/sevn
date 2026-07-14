<!-- template: slug=ui-mission-control profile=subsystem — see _templates/README.md for the markup contract -->

# <Title — "Mission Control UI — <one-line scope>">

<!-- fill: badge row (spec/source/index), left as the pipeline stamps them -->

> **Summary.** <one sentence; mirror the manifest summary>

## Level 1 — Overview (non-technical)

<!-- fill: 1–2 short paragraphs. Browser dashboard at /mission/*; 46 tabs in 8 groups;
     owner login; traces, ops, OpenUI canvas. Operator terms in L1. -->

## Level 2 — How it works (technical)

<!-- fill: subsystem-specific subsections. Expected for ui-mission-control:
       ### SPA shell — ui/spa/dashboard/ vanilla JS app
       ### Tab registry — DASHBOARD_GROUPS, WIRED_SLUGS, build_nav_payload
       ### Route wiring — register_dashboard_routes, create_dashboard_api_router
       ### OpenUI delivery — openui_render tool, canvas tab, delivery matrix
       ### Configuration (`sevn.json` → `dashboard`) — auth, JWT, login
     Cite real symbols. D21 links throughout. -->

### Key modules

<!-- fill: bullet list of load-bearing modules with a one-line role each -->

## Level 3 — Deep dive (low-level, technical)

<!-- generated: pipeline-owned below until References. Do not hand-author. -->

### Module inventory

### Extension and invariants

<!-- /generated -->

## References
