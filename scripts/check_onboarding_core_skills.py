"""Verify bundled core skills land under workspace after onboarding seed.

Module: scripts.check_onboarding_core_skills
Depends: pathlib, tempfile, sevn.onboarding.seed

Exports:
    main — exit 1 when required core skill dirs are missing after seed.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from sevn.onboarding.seed import (
    expected_core_skill_ids,
    seed_bundled_skills,
    verify_core_skills_deployed,
)


def main() -> int:
    """Seed a temp workspace and assert all required core skills are present.

    Returns:
        int: ``0`` when at least 20 non-opt-in skills exist after seed; ``1`` otherwise.

    Examples:
        >>> main() in (0, 1)
        True
    """
    expected = expected_core_skill_ids()
    if len(expected) < 20:
        print(
            f"check_onboarding_core_skills: expected >=20 core skills, got {len(expected)}",
            file=sys.stderr,
        )
        return 1
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        seed_bundled_skills(root)
        missing = verify_core_skills_deployed(root)
    if missing:
        print(
            "check_onboarding_core_skills: missing after seed: " + ", ".join(missing),
            file=sys.stderr,
        )
        return 1
    print(f"check_onboarding_core_skills: ok ({len(expected)} required core skills)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
