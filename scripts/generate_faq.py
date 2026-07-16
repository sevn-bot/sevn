#!/usr/bin/env python3
"""Generate/validate ``docs/FAQ.md`` from ``docs/faq/qa_input.json``.

Module: scripts.generate_faq
Depends: argparse, json, pathlib, sys, sevn.docs.faq

Operators edit ``docs/faq/qa_input.json`` (sections -> questions -> answer with
``{{ref:<id>}}`` placeholders resolved via that question's ``references`` map).
This script validates the JSON (formatting, minimum word counts, and that every
answer carries at least one reference to a real repo file) and renders
``docs/FAQ.md``. Wired into ``make faq-generate`` (write) and ``make faq-check``
(validate + fail on drift, no write) / ``ci-docs``.

Exports:
    generate — Validate the input JSON and render markdown.
    main — CLI entry: ``--check`` validates only; default writes the output file.

Examples:
    >>> main(["--input", "docs/faq/qa_input.json", "--check"])
    faq: ok (docs/faq/qa_input.json -> docs/FAQ.md)
    0
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from sevn.docs.faq import load_document, render_markdown, validate_document  # noqa: E402

DEFAULT_INPUT = "docs/faq/qa_input.json"
DEFAULT_OUTPUT = "docs/FAQ.md"


def generate(
    *,
    repo_root: Path,
    input_path: Path,
    output_path: str = DEFAULT_OUTPUT,
) -> tuple[str | None, list[str]]:
    """Validate ``input_path`` and render markdown for it.

    Args:
        repo_root (Path): Repository root used to resolve reference paths.
        input_path (Path): Path to the ``qa_input.json`` source file.
        output_path (str): Repo-relative path the markdown will be written to;
            used to compute working relative links from repo-root-relative refs.

    Returns:
        tuple[str | None, list[str]]: Rendered markdown (``None`` on validation
        failure) and a list of validation errors (empty when valid).

    Examples:
        >>> import tempfile, json
        >>> td = Path(tempfile.mkdtemp())
        >>> src = td / "qa_input.json"
        >>> _ = src.write_text(json.dumps({"title": "FAQ", "sections": []}), encoding="utf-8")
        >>> markdown, errors = generate(repo_root=td, input_path=src)
        >>> bool(markdown is None and errors)
        True
    """
    raw = json.loads(input_path.read_text(encoding="utf-8"))
    document = load_document(raw)
    errors = validate_document(document, repo_root=repo_root)
    if errors:
        return None, errors
    return render_markdown(document, output_path=output_path), []


def main(argv: list[str] | None = None, *, repo_root: Path | None = None) -> int:
    """Validate ``qa_input.json`` and write or check ``FAQ.md``.

    Args:
        argv (list[str] | None): CLI arguments (``--input``, ``--output``, ``--check``).
        repo_root (Path | None): Repository root; defaults to the parent of ``scripts/``.

    Returns:
        int: ``0`` on success; ``1`` when validation fails or (with ``--check``)
        the rendered output would differ from the file on disk.

    Examples:
        >>> main(["--check"])
        faq: ok (docs/faq/qa_input.json -> docs/FAQ.md)
        0
    """
    root = (repo_root or REPO).resolve()
    parser = argparse.ArgumentParser(description="Generate/validate docs/FAQ.md.")
    parser.add_argument("--input", default=DEFAULT_INPUT, help="Path to qa_input.json.")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="Path to write FAQ.md.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate and diff only; do not write, exit 1 on error or drift.",
    )
    args = parser.parse_args(argv)

    input_path = (root / args.input).resolve()
    output_path = (root / args.output).resolve()

    if not input_path.is_relative_to(root) or not output_path.is_relative_to(root):
        print("faq: paths must resolve within the repository root", file=sys.stderr)
        return 1

    if not input_path.is_file():
        print(f"faq: input not found: {input_path}", file=sys.stderr)
        return 1

    output_rel = output_path.relative_to(root).as_posix()
    markdown, errors = generate(repo_root=root, input_path=input_path, output_path=output_rel)
    if errors or markdown is None:
        print("faq: validation failed:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    if args.check:
        existing = output_path.read_text(encoding="utf-8") if output_path.is_file() else None
        if existing != markdown:
            print(f"faq: {args.output} is stale; run `make faq-generate`", file=sys.stderr)
            return 1
        print(f"faq: ok ({args.input} -> {args.output})")
        return 0

    output_path.write_text(markdown, encoding="utf-8")
    print(f"faq: wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
