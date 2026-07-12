---
name: pdf
description: Render markdown/HTML to workspace PDFs; extract text/tables; structured load/chunk.
version: "1.0.0"
see_also:
  - load_skill
  - run_skill_script
  - canvas
scripts:
  - path: scripts/pdf.py
    description: Render markdown or HTML to a PDF file in the workspace (replaces pdf).
    args_overview: "--out REL_PATH (--html STR | --html-file PATH | --markdown STR | --markdown-file PATH)"
  - path: scripts/pdf_read.py
    description: Extract text, tables, and metadata with pdfplumber (replaces pdf_read).
    args_overview: "--path REL_PATH [--no-tables]"
  - path: scripts/pdf_load.py
    description: Parse and chunk a PDF with openparse (replaces pdf_load).
    args_overview: "--path REL_PATH"
---

# pdf skill

Workspace PDF helpers routed through native **`load_skill`** + **`run_skill_script`**:

- **`pdf.py`** — render markdown or HTML to a workspace-relative PDF via WeasyPrint.
- **`pdf_read.py`** — pdfplumber text/table/metadata extraction (optional extra).
- **`pdf_load.py`** — openparse layout-aware chunking (optional extra).

## Readiness — WeasyPrint native libraries

**`pdf.py`** prefers WeasyPrint (full Unicode/CSS). It needs native **Pango/Cairo** libraries on
the host; without them the skill falls back to bundled **fpdf2** + DejaVu (ASCII-heavy pages and
simple markdown; CJK may degrade to ``?``).

Check status: **`sevn doctor`** (look for ``pdf_weasyprint`` — the detail includes the exact install
command). Gateway boot also logs ``pdf_render_degraded`` when natives are missing.

Install natives (pick your OS):

```bash
# macOS (also run via `make setup` / `make pdf-native-libs`)
brew install pango

# Debian/Ubuntu (Docker gateway image already includes these)
sudo apt-get install -y libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libcairo2 libffi8 fontconfig
```

## Turn an external web page into a PDF

Use this skill — **not** `openui_render`, which is for agent-authored HTML only.

**Pass the fetched file straight through — do NOT rewrite the content.** This is a
render job, not a writing job: feed the bytes you fetched directly to the renderer.

1. **`get_page_content`** `url=… save_to=out/page.md` → writes clean markdown of the
   page to the workspace (omit `max_length` for the full article).
2. **`run_skill_script`** `scripts/pdf.py --out out/page.pdf --markdown-file out/page.md`
   — point `--markdown-file` at the **exact file `get_page_content` wrote**.
3. **`send_file`** the resulting PDF.

Do **not** re-author, paraphrase, summarize, or "clean up" the article with the LLM
before rendering, and never type the markdown out yourself from memory. Regenerating
the body from training knowledge produces a fabricated document (wrong dates, invented
facts) that does not match the page the operator asked for. If the user wants a summary
or edited version, that is a different, explicit request — and even then the edit must be
derived from the fetched text, with anything unsupported flagged `**Unverified**`.

(If you fetched without `save_to`, the markdown may have spilled to disk — `read` the
`spill_path` and `write` those exact bytes to `out/page.md`; do not reconstruct them.)

Install optional dependencies when read/load scripts are needed:

```bash
uv pip install 'sevn[pdf]'
```

Set **`SEVN_WORKSPACE`** (injected by the skill runner). **Output paths** (`--out`, `save_to=`)
are confined to the workspace artifact directory (default **`out/<session_id>/`** via
`workspace.output_dir` in `sevn.json`). Bare filenames like `page.pdf` are rebased there
automatically — do not write generated PDFs or markdown at the workspace root.
