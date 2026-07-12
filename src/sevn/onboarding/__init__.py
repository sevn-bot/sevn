"""Guided onboarding library (`specs/22-onboarding.md` §2).

Module: sevn.onboarding
Depends: submodules in this package

Exports:
    merge_layers — deep-merge preset and operator layers.
    validate_workspace_document — schema gate.
    load_profile_catalog, load_profile_fragment — packaged presets.
    draft_path, read_draft, write_draft, discard_draft, DraftLock — draft lifecycle.
    promote_draft — atomic draft promotion.
    ValidationCheck, ValidationReport, run_live_validation — live probes.
    seed_narrative_templates — markdown seeding.
    seed_personality_from_wizard — personality fast-start markdown merge.
    V1_SQLITE_IMPORT_TABLE_KEYS — v1 import table allowlist.
    MigrationPlan, describe_schema_upgrade, import_foreign_workspace, upgrade_schema_inplace — migrate/import.
    create_onboarding_app — local FastAPI wizard shell.
    OnboardingDraftLockError — concurrent writer.
"""

from __future__ import annotations

from sevn.onboarding.draft_store import (
    DRAFT_FILENAME,
    DraftLock,
    discard_draft,
    draft_path,
    read_draft,
    write_draft,
)
from sevn.onboarding.errors import OnboardingDraftLockError
from sevn.onboarding.live_validate import ValidationCheck, ValidationReport, run_live_validation
from sevn.onboarding.merge import merge_layers
from sevn.onboarding.migrate import (
    V1_SQLITE_IMPORT_TABLE_KEYS,
    MigrationPlan,
    describe_schema_upgrade,
    import_foreign_workspace,
    upgrade_schema_inplace,
)
from sevn.onboarding.profiles import load_profile_catalog, load_profile_fragment
from sevn.onboarding.promote import promote_draft
from sevn.onboarding.seed import seed_narrative_templates, seed_personality_from_wizard
from sevn.onboarding.validate import validate_workspace_document
from sevn.onboarding.web_app import create_onboarding_app

__all__ = [
    "DRAFT_FILENAME",
    "V1_SQLITE_IMPORT_TABLE_KEYS",
    "DraftLock",
    "MigrationPlan",
    "OnboardingDraftLockError",
    "ValidationCheck",
    "ValidationReport",
    "create_onboarding_app",
    "describe_schema_upgrade",
    "discard_draft",
    "draft_path",
    "import_foreign_workspace",
    "load_profile_catalog",
    "load_profile_fragment",
    "merge_layers",
    "promote_draft",
    "read_draft",
    "run_live_validation",
    "seed_narrative_templates",
    "seed_personality_from_wizard",
    "upgrade_schema_inplace",
    "validate_workspace_document",
    "write_draft",
]
