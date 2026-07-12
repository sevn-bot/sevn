"""README pipeline — templates, prompts, and offline rendering (Wave 1+).

Module: sevn.docs.readme
Depends: sevn.docs.readme.profiles, sevn.docs.readme.render

Exports:
    PROFILE_TEMPLATES — map profile name to Jinja2 template filename.
    render_profile — render a README markdown string from profile + context.
    render_all_fixtures — render every profile with fixture data (preview/CI).
    templates_dir — path to shipped ``templates/`` directory.
    prompts_dir — path to shipped ``prompts/`` directory.

Examples:
    >>> from sevn.docs.readme import PROFILE_TEMPLATES
    >>> "root" in PROFILE_TEMPLATES
    True
"""

from __future__ import annotations

from sevn.docs.readme.profiles import PROFILE_TEMPLATES
from sevn.docs.readme.render import (
    prompts_dir,
    render_all_fixtures,
    render_profile,
    templates_dir,
)

__all__ = [
    "PROFILE_TEMPLATES",
    "prompts_dir",
    "render_all_fixtures",
    "render_profile",
    "templates_dir",
]
