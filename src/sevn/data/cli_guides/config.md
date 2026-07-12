# Config — `sevn.json` and Telegram parity

`sevn config` reads and validates the bound workspace `sevn.json`. Telegram `/config` sections map to the same dot-paths (D14 SSOT) — M2 adds an interactive Textual menu mirroring all 19 sections.

## Today (M1)

```bash
sevn config show
sevn config validate
sevn config validate --json
```

## Interactive menu (M2 / W8)

```bash
sevn config                  # Textual section picker on a TTY; help when piped
sevn config sections         # list 19 /config sections
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
