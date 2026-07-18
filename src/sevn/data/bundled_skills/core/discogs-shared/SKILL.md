---
name: discogs-shared
description: Internal shared runtime for bundled Discogs skill scripts (_discogs_runtime.py). Not a model-facing research skill.
version: "1.0.0"
see_also:
  - discogs-database
  - discogs-marketplace
  - discogs-collection
  - discogs-wantlist
  - discogs-identity
scripts:
  - path: scripts/_discogs_runtime.py
    description: Canonical Discogs client factory, JSON envelope helpers, and error mapping.
    args_overview: "(library module — imported by sibling discogs-* skills)"
---

# discogs-shared (internal)

Runtime-quarantined helper package for the five operator-facing Discogs skills. Sibling
skills import ``scripts/_discogs_runtime.py`` via their local ``_discogs_common.py`` shim.
Not offered to the model as a research skill.
