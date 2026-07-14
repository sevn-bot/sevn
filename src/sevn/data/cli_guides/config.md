# Config — `sevn.json` and Telegram parity

`sevn config` reads and validates the bound workspace `sevn.json`. Telegram `/config` sections map to the same dot-paths (D14 SSOT). On a TTY, bare `sevn config` opens the interactive Textual section picker (`src/sevn/cli/tui/config_menu.py`); when piped or cancelled it prints help.

## Commands

```bash
sevn config                  # Textual section picker on a TTY; help when piped
sevn config sections         # list 19 /config sections
sevn config show             # print raw sevn.json
sevn config validate
sevn config validate --json
sevn config session          # show Session dot-paths + current values
sevn config voice --json
```

Dot-path SSOT lives in `src/sevn/cli/config_paths.py` (aligned with `menu_registry.py` `cfg:section:*` and `cfg:toggle:*` rows).

## Tips

- Run `sevn doctor` after config edits that affect gateway, proxy, or secrets.
- Use `sevn secrets` for store entries — never put secret values in `sevn.json`.

## See also

- `sevn guide getting-started`
- `sevn pairing` — channel pairing flows
