"""About-docs pipeline — public prd/specs under ``about-sevn.bot/``.

Module: sevn.docs.about
Depends: sevn.docs.about.model, sevn.docs.about.loader

Exports:
    AboutDoc — validated frontmatter model for PRD/spec docs.
    Interface — public symbol row extracted from AST.
    export_json_schema — Draft 2020-12 JSON Schema export for frontmatter.
    load_doc — read and validate one about-doc markdown file.
    dump_doc — serialise frontmatter and body back to markdown.
    split_frontmatter — split leading YAML frontmatter from markdown body.

Examples:
    >>> from sevn.docs.about import AboutDoc
    >>> AboutDoc.model_fields["kind"].annotation is not None
    True
"""

from __future__ import annotations

from sevn.docs.about.check import check_about_docs
from sevn.docs.about.extract import compute_doc_fingerprint, extract_fields
from sevn.docs.about.generate import generate_body
from sevn.docs.about.index import render_index
from sevn.docs.about.loader import dump_doc, load_doc, split_frontmatter
from sevn.docs.about.model import AboutDoc, Interface, export_json_schema

__all__ = [
    "AboutDoc",
    "Interface",
    "check_about_docs",
    "compute_doc_fingerprint",
    "dump_doc",
    "export_json_schema",
    "extract_fields",
    "generate_body",
    "load_doc",
    "render_index",
    "split_frontmatter",
]
