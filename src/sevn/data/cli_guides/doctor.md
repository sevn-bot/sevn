# Doctor — workspace health and safe fixes

`sevn doctor` runs ordered probes across workspace, gateway, secrets, channels, models, browser tools, and optional extras.

## Human report

Section banners group checks by subsystem. A summary line shows `N ok · M warn · K fail`.

```bash
sevn doctor
sevn doctor --strict          # warnings elevate to exit 4
```

## Machine output

```bash
sevn doctor --json
```

The envelope preserves legacy check `id` strings and `{checks[], warnings[]}` for automation. Newer waves add optional `solution`, `fixed`, and `manual` keys when using `--fix`.

## Safe auto-fix

```bash
sevn doctor --fix             # interactive whitelist fixes
sevn doctor --fix --yes       # non-interactive (CI / scripts)
```

## Diagnostic agent

```bash
sevn doctor --with-agent      # confirm each fix step
sevn doctor --with-agent --yes --model <slot>
```

## See also

- `sevn guide logs-traces` — correlate doctor warnings with logs/traces
- `sevn secrets` — secrets store operations
