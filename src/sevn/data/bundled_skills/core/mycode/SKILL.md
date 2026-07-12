---
name: mycode
description: Deterministic repo scan + MYCODE.md write (`specs/28-code-understanding.md` §2.4).
version: "0.1.0"
max_wall_seconds: 25
see_also:
  - graphify
scripts:
  - path: scripts/scan.py
    description: Scan a repository root and write MYCODE.md (deterministic, no LLM).
    args_overview: "--root PATH [--output PATH] [--ignore PATTERN] ..."
---

# mycode skill

Wraps the library functions in `src/sevn/code_understanding/`:

- `scan_repo(root, ignore)` / `scan_repo_cached(root, ignore)` — deterministic walk;
  Python parsed with `ast`, JS/TS/Go/Rust use regex heuristics.
- `generate_mycode_markdown(digest, *, cgr_json=None, transport=None)` —
  deterministic markdown when `transport` is `None` (the default for bundled scan).
- `write_mycode(output_path, content)` — atomic write under `.index/mycode/MYCODE.md`.

Use native **`load_skill`** + **`run_skill_script`** to invoke `scripts/scan.py`.
The legacy index alias **`mycode_scan`** resolves to **`mycode`** for one release.

**Note:** The gateway seeds `MYCODE.md` automatically at boot (in the background).
Invoke this skill only when you explicitly need to regenerate the scan (e.g. after
large code changes). Do not invoke it reactively on every turn.
If `MYCODE.md` is already present, read it directly from
`source_code/.index/mycode/MYCODE.md` — no skill run is needed.
