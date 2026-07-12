---
name: telegram
description: Telegram inline custom buttons and forum supergroup helpers (Bot API + allowlist/userbot hooks).
version: "1.0.0"
see_also:
  - load_skill
  - run_skill_script
scripts:
  - path: scripts/buttons.py
    description: Add, remove, list, or clear custom inline buttons; emit keyboard JSON (replaces telegram_buttons).
    args_overview: "--action list|add|remove|clear|keyboard [--name LABEL] [--command CMD]"
  - path: scripts/forum_create.py
    description: Create a forum topic in a supergroup via Bot API (replaces telegram_forum_create).
    args_overview: "--chat-id ID --name TOPIC [--icon-color N]"
  - path: scripts/forum_find_group.py
    description: Resolve a supergroup chat id by title via allowlist scan or userbot hook (replaces telegram_forum_find_group).
    args_overview: "--name GROUP_TITLE"
---

# telegram skill

Workspace Telegram helpers routed through native **`load_skill`** + **`run_skill_script`**:

- **`buttons.py`** — teleshell-style custom inline button store under ``.sevn/telegram_buttons.json``.
- **`forum_create.py`** — ``createForumTopic`` via Bot API (``SEVN_TELEGRAM_BOT_TOKEN`` or gateway adapter injection).
- **`forum_find_group.py`** — match ``channels.telegram.allowed_groups`` titles via ``getChat``, or a userbot hook when wired.

Set **`SEVN_WORKSPACE`** (injected by the skill runner). For Bot API scripts, set **`SEVN_TELEGRAM_BOT_TOKEN`** or configure ``channels.telegram.bot_token_ref``.
