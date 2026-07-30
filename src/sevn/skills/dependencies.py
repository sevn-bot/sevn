"""Manifest-declared skill dependency metadata (D7, ``specs/12-skills-system.md``).

Module: sevn.skills.dependencies
Depends: dataclasses

Exports:
    SkillDependencies — uv extras and executables declared in ``SKILL.md`` frontmatter.
    coerce_skill_dependencies — parse YAML ``dependencies:`` block.
"""

from __future__ import annotations

from dataclasses import dataclass

from sevn.skills.errors import SKILL_VALIDATION, SkillExecutionError


@dataclass(frozen=True, slots=True)
class SkillDependencies:
    """Optional setup requirements declared in skill frontmatter."""

    uv_extras: tuple[str, ...] = ()
    executables: tuple[str, ...] = ()

    @property
    def requires_setup(self) -> bool:
        """Return whether any install or PATH requirement is declared.

        Returns:
            bool: ``True`` when uv extras or executables are declared.

        Examples:
            >>> SkillDependencies(uv_extras=("job-ops",)).requires_setup
            True
        """
        return bool(self.uv_extras or self.executables)


def _coerce_str_list(raw: object, *, field: str) -> tuple[str, ...]:
    """Coerce one dependency list field to a normalized string tuple.

    Args:
        raw (object): Decoded YAML value.
        field (str): Field name for error messages.

    Returns:
        tuple[str, ...]: Non-empty stripped strings.

    Raises:
        SkillExecutionError: When the list shape is invalid.

    Examples:
        >>> _coerce_str_list([" a ", "b"], field="uv_extras")
        ('a', 'b')
    """
    if raw is None:
        return ()
    if not isinstance(raw, list) or any(not isinstance(item, str) for item in raw):
        msg = f"`dependencies.{field}` must be a list[str] when present"
        raise SkillExecutionError(msg, code=SKILL_VALIDATION)
    return tuple(str(item).strip() for item in raw if str(item).strip())


def coerce_skill_dependencies(raw: object) -> SkillDependencies:
    """Parse a ``dependencies:`` frontmatter block into :class:`SkillDependencies`.

    Args:
        raw (object): Decoded YAML value.

    Returns:
        SkillDependencies: Normalized dependency rows.

    Raises:
        SkillExecutionError: When the block shape is invalid.

    Examples:
        >>> deps = coerce_skill_dependencies({"uv_extras": ["job-ops"]})
        >>> deps.uv_extras
        ('job-ops',)
    """
    if raw is None:
        return SkillDependencies()
    if not isinstance(raw, dict):
        msg = "`dependencies` must be an object mapping when present"
        raise SkillExecutionError(msg, code=SKILL_VALIDATION)
    uv_extras = _coerce_str_list(raw.get("uv_extras"), field="uv_extras")
    executables = _coerce_str_list(raw.get("executables"), field="executables")
    return SkillDependencies(uv_extras=uv_extras, executables=executables)


__all__ = ["SkillDependencies", "coerce_skill_dependencies"]
