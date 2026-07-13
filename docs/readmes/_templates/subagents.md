<!-- template: slug=subagents profile=subsystem — see _templates/README.md for the markup contract -->

# <Title — "Sub-agents — <one-line scope>">

<!-- fill: badge row (spec/source/index), left as the pipeline stamps them -->

> **Summary.** <one sentence; mirror the manifest summary. Do NOT let it truncate mid-word. -->

## Level 1 — Overview (non-technical)

<!-- fill: 1–2 short paragraphs. What sub-agents are: level-1 role runs that may spawn
     level-2 workers/specialists, tracked and killable. Operator terms. -->

## Level 2 — How it works (technical)

<!-- fill: subsystem-specific subsections. Expected for subagents:
       ### Components and layout — registry, supervisor, storage, specialists, workers
       ### Level-1 and level-2 runs — spawn/track/kill lifecycle (real symbols)
       ### Multi queue mode — queue_multi behaviour
       ### Configuration (`sevn.json` → `subagents`) — the knobs
     Replace the generic "Data and control flow / turn spine" boilerplate carried over
     from the old scaffold with a real description sourced from the spec + code. -->

### Key modules

<!-- fill: bullet list of load-bearing modules with a one-line role each -->

## Level 3 — Deep dive (low-level, technical)

<!-- generated: pipeline-owned below until References. Do not hand-author. -->

### Module inventory

### Extension and invariants

<!-- /generated -->

## References
