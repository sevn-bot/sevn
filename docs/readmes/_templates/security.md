<!-- template: slug=security profile=subsystem — see _templates/README.md for the markup contract -->

# <Title — "Security scanner — <one-line scope>">

<!-- fill: badge row (spec/source/index), left as the pipeline stamps them -->

> **Summary.** <one sentence; mirror the manifest summary>

## Level 1 — Overview (non-technical)

<!-- fill: 1–2 short paragraphs. What the scanner does: inspects inbound content before
     triage, blocks-and-notifies on findings, honours .llmignore. Operator terms. -->

## Level 2 — How it works (technical)

<!-- fill: subsystem-specific subsections. Expected for security:
       ### LLM Guard scan points — where scan_inbound runs in the turn
       ### Block-and-notify flow — what happens on a finding
       ### `.llmignore` layout — precedence and format
       ### Configuration (`sevn.json` → `security`) — the knobs
     Cite real symbols (LLMGuardScanner.scan_inbound, …). Do NOT describe the turn spine
     as if this subsystem routes triage — it is a guard, not the dispatcher. -->

### Key modules

<!-- fill: bullet list of load-bearing modules with a one-line role each -->

## Level 3 — Deep dive (low-level, technical)

<!-- generated: pipeline-owned below until References. Do not hand-author. -->

### Module inventory

### Extension and invariants

<!-- /generated -->

## References
