---
name: skill_management
description: Authoring workflows for generated skills; pairs with native skill_create and promote_generated_skill (`specs/12-skills-system.md` §2.5).
version: "1.0.0"
see_also:
  - skill_create
  - promote_generated_skill
  - load_skill
  - run_skill_script
scripts:
  - path: scripts/list_inventory.py
    description: List discovered skills grouped by provenance (core, generated, user, plugin).
    args_overview: "[--provenance core|generated|user|plugin]"
  - path: scripts/validate.py
    description: Validate a skill manifest and declared script paths before promotion.
    args_overview: "--skill-name NAME"
  - path: scripts/authoring_workflow.py
    description: Return the canonical scaffold → test → promote workflow referencing native tools.
    args_overview: "[--skill-name NAME]"
---

# Skill management

Use native **`skill_create`** to scaffold quarantined skills under
``workspace/skills/generated/<name>/``. Test scripts with **`run_skill_script`**. Promote
stable skills with native **`promote_generated_skill`** (requires human acknowledgement).

These bundled scripts inventory and validate the workspace tree; they do **not** replace
the native authoring tools.
