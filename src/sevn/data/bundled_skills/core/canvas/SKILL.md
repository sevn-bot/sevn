---
name: canvas
description: Cursor Canvas and rich analytical layouts via OpenUI compose helpers (`specs/11-tools-registry.md` §3.4, `specs/29-openui.md`).
version: "1.0.0"
see_also:
  - openui_render
  - load_skill
  - run_skill_script
scripts:
  - path: scripts/compose_table.py
    description: Build a titled HTML table and openui_render payload from JSON columns/rows.
    args_overview: "--title STR --columns JSON --rows JSON [--output live|screenshot|pdf]"
  - path: scripts/compose_cards.py
    description: Build a card grid HTML fragment and openui_render payload from JSON cards.
    args_overview: "--title STR --cards JSON [--output live|screenshot|pdf]"
  - path: scripts/compose_openui_payload.py
    description: Wrap arbitrary HTML with required fallback_text for native openui_render.
    args_overview: "--html STR | --html-file PATH --fallback-text STR [--title STR] [--output live|screenshot|pdf]"
---

# Canvas (bundled)

Bundled skill for **Cursor Canvas** — rich analytical layouts, tables, and interactive
artifacts. Scripts compose sanitiser-friendly HTML fragments plus the **`fallback_text`**
required by native **`openui_render`**. After running a compose script, call
**`openui_render`** with the returned ``html`` and ``fallback_text`` fields.

Native **`canvas`** tool rows are not registered independently in v1.
