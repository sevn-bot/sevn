# Config fixtures

Golden `sevn.json` fragments for tests and CI.

| File | Role |
|------|------|
| `schema_v1_min.json` | Smallest shape exercised by `WorkspaceConfig` (schema version 1): `gateway`, `tracing.sinks` with `jsonl_file`. |

**Regenerate:** Edit when `SUPPORTED_SCHEMA_VERSIONS` or `WorkspaceConfig` required fields change. Verify with **`make test`** (runs `tests/config/test_workspace_config.py`).
