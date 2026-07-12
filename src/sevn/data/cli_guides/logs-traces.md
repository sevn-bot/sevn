# Logs and traces — unified observability

## Unified logs (`sevn logs`)

Merge gateway, proxy, agent, and `[cli]` activity logs with an insight summary header.

```bash
sevn logs --all --lines 80
sevn logs --follow --grep error
sevn logs --since 1h --level WARNING --json
```

Legacy entry points remain:

```bash
sevn gateway logs
sevn proxy logs
```

## Span-grouped traces (`sevn traces`)

Read `traces.db` via the same query layer Mission Control uses.

```bash
sevn traces --last 30
sevn traces --session <id> --json
```

## Workflow

1. Run `sevn logs --all --since 30m` and read the insight summary (error counts, top signatures, slow spans).
2. Drill into `sevn traces --session <id>` when a turn looks slow or failed.
3. Re-run `sevn doctor` if restarts or proxy health appear in the summary.

## See also

- `sevn turn-bundle` — export a single turn for support
- `sevn dashboard` — Mission Control SPA
