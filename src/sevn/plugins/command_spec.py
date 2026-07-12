"""Plugin-registered slash commands (`specs/34-plugin-hooks.md` §2.2).

Module: sevn.plugins.command_spec
Depends: pydantic

Exports:
    PluginCommandSpec — validated pattern + dispatch_key for register_command rows.
    PluginSlashBinding — pairs command spec with owning hook for dispatcher routing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

if TYPE_CHECKING:
    from sevn.plugins.hook import PluginHook

# Slash pattern — `specs/34-plugin-hooks.md` §2.2 primary pattern field.
_SLASH_PATTERN = re.compile(r"^/[a-z][a-z0-9_]*[a-z0-9_./-]*$")


class PluginCommandSpec(BaseModel):
    """One row returned from :meth:`~sevn.plugins.hook.PluginHook.register_command`."""

    model_config = ConfigDict(extra="forbid")

    pattern: str = Field(
        description="Primary slash form, e.g. ``/corp_status`` or ``/corp_status/info``.",
    )
    dispatch_key: str = Field(min_length=1, description="Stable key passed to dispatch_tool.")
    description: str = Field(default="", description="Help / setMyCommands copy.")

    @model_validator(mode="after")
    def _validate_pattern(self) -> Self:
        """Ensure non-empty slash form, grammar, and dotted namespace.

        Returns:
            PluginCommandSpec: Model with trimmed ``pattern``.

        Examples:
            >>> PluginCommandSpec(pattern="/corp.demo.ok", dispatch_key="k").pattern
            '/corp.demo.ok'
        """
        p = self.pattern.strip()
        if not p:
            msg = "pattern must be non-empty"
            raise ValueError(msg)
        if not _SLASH_PATTERN.match(p):
            msg = f"invalid plugin command pattern: {p!r}"
            raise ValueError(msg)
        if "." not in p.removeprefix("/"):
            msg = "pattern must include a plugin namespace segment after ``/``"
            raise ValueError(msg)
        return self.model_copy(update={"pattern": p})


@dataclass(frozen=True)
class PluginSlashBinding:
    """Gateway dispatcher row for one plugin-owned slash pattern."""

    command: PluginCommandSpec
    hook: PluginHook
    trust_owner: bool


__all__ = ["PluginCommandSpec", "PluginSlashBinding"]
