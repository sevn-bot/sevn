# Second Brain fixtures

Ephemeral vault trees for tests live under `tmp_path` (no committed binary fixtures).

## Default layout

```text
<workspace>/
  sevn.json
  second_brain/
    users/<scope>/
      raw/...
      wiki/index.md, wiki/log.md, wiki/ingests/...
      outputs/
    shared/wiki/   # optional overlay topology
```

## Custom vault fixture

When testing `second_brain.paths.vault`, point config at a workspace-relative folder:

```json
"second_brain": {
  "enabled": true,
  "paths": { "vault": "obsidian/alex_AI" }
}
```

Use `resolve_scope_root(content_root, cfg, scope)` from `sevn.second_brain.paths` (preferred) or legacy `vault_root` / `user_scope_root` for default-layout tests only.
