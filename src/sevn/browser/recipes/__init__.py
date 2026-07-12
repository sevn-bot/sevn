"""Site recipes over the sevn CDP browser engine.

Each recipe is a thin, fixture-testable module over :class:`~sevn.browser.page.Page`
and :class:`~sevn.browser.element.Dom` that implements high-level verbs (read / post /
reply / login / …) for one site. The ``browser`` tool surfaces them as recipe actions.

Module: sevn.browser.recipes
Depends: sevn.browser.recipes.base

Exports:
    RecipeError — recipe-level failure (login required, human handoff, egress, …).
    human_required — build a HUMAN_REQUIRED handoff envelope payload.

Examples:
    >>> from sevn.browser.recipes import RecipeError
    >>> issubclass(RecipeError, RuntimeError)
    True
"""

from __future__ import annotations

from sevn.browser.recipes.base import RecipeError, human_required

__all__ = ["RecipeError", "human_required"]
