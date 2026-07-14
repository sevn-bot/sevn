<!-- template: slug=agent profile=subsystem — see _templates/README.md for the markup contract -->

# <Title — "Agent runtime — <one-line scope>">

<!-- fill: badge row (spec/source/index), left as the pipeline stamps them -->

> **Summary.** <one sentence; mirror the manifest summary>

## Level 1 — Overview (non-technical)

<!-- fill: 1–2 short paragraphs. What the agent runtime is: triage decides how hard a
     message is, then routes to the right executor tier. Operator terms, no src/ paths. -->

## Level 2 — How it works (technical)

<!-- fill: subsystem-specific subsections. Expected for agent:
       ### Triage (`src/sevn/agent/triager/`) — how triage classifies and replies at tier A
       ### Executor tiers — tier B vs C/D, what each is for, key entry symbols
       ### Harness discipline and sandbox — limits, isolation
       ### Configuration — sevn.json knobs
       ### Honest status (selected paths) — live/partial/stub table where wiring is incomplete
     Cite real symbols (run_b_turn, run_cd_turn, triage_turn, …). -->

### Key modules

<!-- fill: bullet list of load-bearing modules with a one-line role each -->

## Level 3 — Deep dive (low-level, technical)

<!-- generated: pipeline-owned below until References. Do not hand-author. -->

### Module inventory

### Extension and invariants

<!-- /generated -->

## References
