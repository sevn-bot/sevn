"""On-disk skill records (manifest + filesystem provenance).

Module: sevn.skills.models
Depends: pathlib, typing, sevn.skills.manifest

Exports:
    SkillRecord — one runnable skill directory + parsed manifest facts.

Examples:
    >>> from pathlib import Path
    >>> from sevn.skills.manifest import SkillManifest
    >>> from sevn.skills.models import SkillRecord
    >>> sr = SkillRecord(
    ...     canonical_id="a",
    ...     skill_dir=Path("/tmp"),
    ...     manifest=SkillManifest(name="a", description="d", version="1.0.0"),
    ...     provenance="user",
    ...     markdown_raw="",
    ... )
    >>> isinstance(sr.validation_errors, tuple)
    True
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from sevn.skills.manifest import SkillManifest

ProvenanceKind = Literal["core", "user", "generated", "plugin"]


@dataclass(frozen=True)
class SkillRecord:
    """Resolved skill directory and manifest."""

    canonical_id: str
    """Registry id (``plugin/skill`` when provenance is ``plugin``, else flat ``name``)."""

    skill_dir: Path
    manifest: SkillManifest
    provenance: ProvenanceKind
    markdown_raw: str
    validation_errors: tuple[str, ...] = field(default_factory=tuple)
    """Non-fatal warnings for optional downgrade paths (``user``), empty when strict."""

    @property
    def quarantine_runtime(self) -> bool:
        """Whether runs are blocked (generated quarantine semantics).

        Returns:
            bool: Effective quarantine gate for script/runnable execution.

        Examples:
            >>> from pathlib import Path
            >>> from sevn.skills.manifest import SkillManifest
            >>> from sevn.skills.models import SkillRecord
            >>> sr_gen = SkillRecord(
            ...     canonical_id="g",
            ...     skill_dir=Path("/tmp"),
            ...     manifest=SkillManifest(name="g", description="x", version="1.0.0"),
            ...     provenance="generated",
            ...     markdown_raw="",
            ... )
            >>> sr_gen.quarantine_runtime
            True
        """
        return self.manifest.effective_quarantine(self.provenance)
