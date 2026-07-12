"""README profile registry — maps §C0 profiles to Jinja2 templates.

Module: sevn.docs.readme.profiles
Depends: (none)

Exports:
    PROFILE_TEMPLATES — profile name → template filename under ``templates/``.

Examples:
    >>> PROFILE_TEMPLATES["subsystem"]
    'subsystem.md.j2'
    >>> set(PROFILE_TEMPLATES) >= {"root", "index", "catalog", "guide", "freeform"}
    True
"""

from __future__ import annotations

PROFILE_TEMPLATES: dict[str, str] = {
    "root": "root.md.j2",
    "subsystem": "subsystem.md.j2",
    "index": "index.md.j2",
    "catalog": "catalog.md.j2",
    "guide": "guide.md.j2",
    "freeform": "freeform.md.j2",
}
