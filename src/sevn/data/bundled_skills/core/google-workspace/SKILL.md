---
name: google-workspace
description: Gmail, Calendar, Drive, Contacts, Sheets, and Docs via OAuth2-authenticated Google Workspace APIs.
version: "0.1.0"
see_also:
  - load_skill
  - run_skill_script
  - email-management
  - browser-harness
egress:
  - gmail.googleapis.com
  - www.googleapis.com
  - oauth2.googleapis.com
  - people.googleapis.com
  - sheets.googleapis.com
  - docs.googleapis.com
  - drive.googleapis.com
  - calendar.googleapis.com
scripts:
  - path: scripts/setup.py
    description: OAuth setup, credential checks, auth URL exchange, revoke, and dependency install guidance.
    args_overview: "--check | --client-secret PATH | --auth-url [--services email|calendar|drive|sheets|docs|contacts|all] [--format json|text] | --auth-code URL_OR_CODE [--format json|text] | --revoke | --install-deps"
    abortable: false
  - path: scripts/google_api.py
    description: Hermes-compatible Google Workspace CLI for Gmail, Calendar, Drive, Contacts, Sheets, and Docs.
    args_overview: "gmail|calendar|drive|contacts|sheets|docs <operation> [args...] [--dry-run]"
    abortable: false
  - path: scripts/gws_bridge.py
    description: Thin pass-through bridge to the optional gws CLI using workspace OAuth env.
    args_overview: "<gws argv...>"
    abortable: false
---

# google-workspace

Google Workspace workflows for **Gmail**, **Calendar**, **Drive**, **Contacts**,
**Sheets**, and **Docs** using OAuth2 tokens stored under the workspace
(`.sevn/google_token.json` by default).

Prefer **`email-management`** when the operator only needs quick email access
across multiple providers or wants IMAP/SMTP without creating a Google Cloud
project. Use **`google-workspace`** when Gmail API features (labels, threading,
HTML), Calendar, Drive, Sheets, Docs, or Contacts are required.

## Setup workflow

1. Enable the Google APIs you need in a Google Cloud project and download a
   Desktop OAuth client JSON.
2. Store that client JSON in the workspace:

   ```bash
   run_skill_script("google-workspace", "scripts/setup.py", ["--client-secret", "/path/to/client_secret.json"])
   ```

3. Check auth state:

   ```bash
   run_skill_script("google-workspace", "scripts/setup.py", ["--check"])
   ```

4. Request an auth URL and have the operator complete the browser flow:

   ```bash
   run_skill_script("google-workspace", "scripts/setup.py", ["--auth-url", "--services", "all", "--format", "json"])
   ```

5. Exchange the returned redirect URL or raw code:

   ```bash
   run_skill_script("google-workspace", "scripts/setup.py", ["--auth-code", "http://localhost:1/?code=..."])
   ```

6. For plan-only validation, pass `--dry-run` to `scripts/google_api.py` or set
   `SEVN_GOOGLE_DRY_RUN=1`.

7. Install optional Python deps (when live API calls are needed):

   ```bash
   uv pip install --python "$(which python3)" 'sevn[google-workspace]'
   ```

   Or run `run_skill_script("google-workspace", "scripts/setup.py", ["--install-deps"])`
   (uses `uv pip` when `uv` is on PATH).

## Safety rules

- Ask the operator first before sending email, replying, modifying Gmail
  labels, creating or deleting calendar events, uploading or sharing Drive
  files, creating folders, deleting Drive files, or writing to Sheets/Docs.
- Prefer Drive trash over permanent delete unless the operator explicitly asks
  for irreversible removal.
- Keep client secrets, refresh tokens, and access tokens out of chat and out of
  tool output.
- Calendar timestamps must be ISO 8601 with timezone offset or `Z`.
- If the skill returns `NOT_AUTHENTICATED`, fall back to browser-based Gmail
  work or to **`email-management`** until OAuth is configured.

## Browser and email fallbacks

- **`email-management`** remains the best path for multi-account IMAP/SMTP and
  non-Google providers.
- A logged-in browser session remains the fallback for Gmail reads/search and
  other operator-driven Google web workflows when OAuth is unavailable.
- Use browser fallback rather than forcing OAuth setup in the middle of an
  urgent read-only task.

## Notes

- Preferred live backend: Google Workspace Python/OAuth stack and optional
  `gws` CLI bridge when available.
- The bundled scripts should emit a single JSON envelope on stdout using the
  standard `sevn.lcm.script_cli` contract.
