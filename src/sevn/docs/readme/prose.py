"""Text normalization helpers for README prose emission.

Module: sevn.docs.readme.prose
Depends: re

Exports:
    strip_inline_code — remove inline-code backticks without doubling quotes.
    rewrite_design_doc_refs — canonical design-doc path rewrite for published READMEs.
    module_docstring_prose — narrative docstring text before structured blocks.

Examples:
    >>> from sevn.docs.readme.prose import strip_inline_code
    >>> strip_inline_code("Use `foo` here.")
    'Use foo here.'
"""

from __future__ import annotations

import re

_INLINE_CODE = re.compile(r"``([^`]+)``|`([^`]+)`")
_RST_ROLE = re.compile(r":\w+:`([^`]+)`")
_SPECS_REF = re.compile(r"(?<![\w./-])specs/")
_PLAN_PRD_REF = re.compile(r"(?<![\w./-])`?(?:plan|prd)/[^\s'`\"`,)]+`?")


def strip_inline_code(text: str) -> str:
    """Strip markdown inline-code backticks without doubling quote characters.

        Args:
    text (str): Source prose that may contain `` `x` `` or `` ``x`` `` spans.

        Returns:
            str: Prose with inline code delimiters removed.

        Examples:
            >>> strip_inline_code("Use `foo` here.")
            'Use foo here.'
            >>> strip_inline_code("Already ''doubled'' quotes.")
            'Already doubled quotes.'
    """

    def _replace(match: re.Match[str]) -> str:
        return match.group(1) or match.group(2) or ""

    cleaned = _RST_ROLE.sub(r"\1", text)
    cleaned = _INLINE_CODE.sub(_replace, cleaned)
    return cleaned.replace("''", "")


def rewrite_design_doc_refs(text: str) -> str:
    """Rewrite gitignored design-doc path cites for published README emission.

        Args:
    text (str): Docstring or markdown excerpt.

        Returns:
            str: Text with ``specs/`` retargeted and ``plan/``/``prd/`` cites genericized.

        Examples:
            >>> rewrite_design_doc_refs("('specs/17-gateway.md')")
            "('about-sevn.bot/specs/17-gateway.md')"
            >>> rewrite_design_doc_refs("'plan/foo.md'")
            "'the design docs'"
            >>> rewrite_design_doc_refs(
            ...     "(`plan/dev_eval_14062026/evolution-auto-run-import-wave-plan.md` AR-1)."
            ... )
            '(the design docs AR-1).'
    """
    if not text:
        return text
    text = _SPECS_REF.sub("about-sevn.bot/specs/", text)
    return _PLAN_PRD_REF.sub("the design docs", text)


def module_docstring_prose(docstring: str) -> str:
    """Return narrative docstring prose without structured export inventories.

        Args:
    docstring (str): Full module docstring text.

        Returns:
            str: Leading prose paragraphs before ``Module:`` / ``Exports:`` blocks.

        Examples:
            >>> module_docstring_prose("Summary.\\n\\nModule: sevn.demo\\nExports:\\n    run")
            'Summary.'
    """
    if not docstring.strip():
        return ""
    lines: list[str] = []
    for line in docstring.splitlines():
        stripped = line.strip()
        if stripped.startswith(("Module:", "Depends:", "Exports:", "Examples:")):
            break
        lines.append(line)
    return rewrite_design_doc_refs("\n".join(lines).strip())
