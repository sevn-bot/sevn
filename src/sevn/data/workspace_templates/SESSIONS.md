# Session recall — where past conversations live

Use this guide when the operator asks what you talked about earlier, to recall today's sessions, or to search past messages.

## Where sessions are stored

Past conversations exist in **two** places:

1. **`sessions/`** — append-only JSONL mirror files (one file per session when `gateway.session_mirror` is enabled).
2. **Gateway SQLite** — `gateway_sessions` table plus message rows in `.sevn/sevn.db` (see `source_code/src/sevn/storage/migrate.py` for schema).

LCM (lossless context) indexes cross-session message rows in the same database when memory/LCM is enabled.

## Recall order (try in this sequence)

1. **`history`** — primary path. Returns compact inline rows; never read the whole session file for bounded queries.
   - Example: `history --limit 20 --full` via the **`sessions_management`** skill (`run_skill_script`) or the native `history` tool when registered.
   - Default limit is 20 rows; use `--full` for untruncated content up to the limit.
2. **`glob` + paged `read`** — fallback when `history` is unavailable or returns an error.
   - `glob` with pattern `sessions/**` to locate session files.
   - `read` with `offset` / `limit` cursors for large files (do not re-issue the same read in a loop).
3. **LCM `query` / `search`** — cross-session semantic or keyword search via the **`lcm`** skill when enabled.

## Rules

- **Never** claim "fresh session" or "no history" until a retrieval tool succeeds with an empty result set.
- If a tool returns `ok=false`, report the failure and try the next step in this order — do not treat errors as "no data."
- Prefer inline `history` rows over reading raw session JSONL when both are available.
