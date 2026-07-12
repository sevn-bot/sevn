# Golden migrate fixtures

Trees under this directory exercise `sevn.onboarding.migrate` and `sevn migrate` (`specs/22-onboarding.md` §9).

| Path | Role |
|------|------|
| `v1_workspace/sevn.json` | Minimal valid **v1** workspace document (aligned with `tests/fixtures/config/schema_v1_min.json`). Used by pytest for `describe_schema_upgrade` / in-place upgrade paths. |
| `v2_workspace/sevn.json` | Same shape at **schema_version 2** (post-`sevn migrate` / no-op upgrade smoke). |

**Regenerate:** When `WorkspaceConfig` required fields or `SUPPORTED_SCHEMA_VERSIONS` change, update `v1_workspace/sevn.json` to stay parseable + schema-valid, then run **`make test`** (or `make ci`).

Regenerate after changing heuristics in `sevn.onboarding.migrate.import_foreign_workspace`.
