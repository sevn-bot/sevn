#!/usr/bin/env python3
"""Bundled ``job-ops`` skill — register the operator resume/profile text.

Stores resume text at ``<content_root>/job-ops/resume.md`` for scoring/tailoring.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from sevn.lcm.script_cli import write_error, write_ok

from lib.store import JobStore


def main(argv: list[str] | None = None) -> int:
    """Persist resume text from ``--text`` or ``--file``."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--text", default="", help="Resume/profile text (inline).")
    parser.add_argument("--file", default="", help="Path to a resume text/markdown file.")
    parser.add_argument("--show", action="store_true", help="Return the stored resume and exit.")
    args = parser.parse_args(argv)

    store = JobStore()

    if args.show:
        resume = store.read_resume()
        write_ok({"chars": len(resume.text), "text": resume.text})
        return 0

    text = args.text
    if args.file:
        path = Path(args.file).expanduser()
        if not path.is_file():
            write_error(code="VALIDATION_ERROR", error=f"resume file not found: {path}")
            return 1
        text = path.read_text(encoding="utf-8")

    if not text.strip():
        write_error(code="VALIDATION_ERROR", error="provide --text or --file with resume content")
        return 1

    stored = store.write_resume(text)
    write_ok({"path": str(stored), "chars": len(text)}, message="resume stored")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
