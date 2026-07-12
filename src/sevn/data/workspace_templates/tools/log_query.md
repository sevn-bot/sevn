# `log_query` — long description

Read, tail, or regex-filter a workspace log file under `<workspace>/logs/`,
applying operator-safe redaction. Returns a JSON envelope with matched lines,
1-based `line_numbers`, read `mode`, and `total_file_lines`. Reads gateway and
egress proxy logs (including rotated `*.log` files).

Use **only one** positioning mode per call: default tail, `starting_reading_line`,
or `ranges` (not combined with `offset_from_tail > 0`).

## Calling from `run_code` (CodeMode)

Inside the `run_code` sandbox, `log_query` is a normal async function. Call it with
**keyword arguments** and read the lines off the returned dict — do **not** translate the
JSON examples below into a JSON string.

```python
out = await log_query(pattern="ERROR|WARN", lines=100)
for line in out["data"]["lines"]:      # data.lines is a list[str]
    print(line)
```

Page backward through history without re-reading the head:

```python
out = await log_query(offset_from_tail=300, lines=50)
print(out["data"]["lines"])
```

### Common mistakes (these break the call)

| ❌ Don't | ✅ Do |
|----------|-------|
| Wrap the call in JSON: `run_code(code='{"code": "await log_query(...)"}')` | Pass raw Python as `code`: `result = await log_query(lines=100)` |
| Iterate the envelope: `for x in out: ...` (yields dict keys / chars) | Iterate the lines: `for x in out["data"]["lines"]: ...` |
| Put two statements on one line: `result = await log_query(...) result` | Use a newline: `result = await log_query(...)\nresult` |
| Stringly-typed numbers/bools still work but read oddly: `lines="100"` | Use real literals: `lines=100`, `summarize=True` |

String-typed numbers (`lines="100"`) and booleans (`summarize="true"`) are now coerced
automatically, but prefer real Python literals — they type-check on the first sandbox call.

## Parameters

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `file` | string | `gateway.log` | Bare filename under `<workspace>/logs/`. Path separators (`/`, `\`) and `..` are rejected. |
| `lines` | integer | `50` | Window size for tail/from-line modes; total return cap for `ranges` (max 500). |
| `pattern` | string | `null` | Optional regex on raw line text before selection. |
| `offset_from_tail` | integer | `0` | **Tail mode only.** Skip newest lines/matches, then return up to `lines` older entries. |
| `starting_reading_line` | integer | `null` | **From-line mode.** 1-based start line; reads forward up to `lines` lines. |
| `ranges` | array of string | `null` | **Ranges mode.** Inclusive 1-based intervals: `"10-50"` or `"100:120"`. |

## Read modes

| `mode` | Trigger | Behavior |
|--------|---------|----------|
| `tail` | default | Last `lines` physical lines (or last `lines` regex matches). |
| `tail` + offset | `offset_from_tail > 0` | Paginate backward from the end. |
| `from_line` | `starting_reading_line` set | Forward read from a 1-based line index. |
| `ranges` | `ranges` non-empty | Union of explicit intervals, file order, capped at `lines`. |

## Examples by form

Each block is a complete `log_query` **arguments** object. Pick one positioning
mode per call.

### Tail — default (newest window)

Last 50 lines of `gateway.log` (default file and line count):

```json
{}
```

Larger tail window:

```json
{"lines": 100}
```

### Tail — regex filter (still newest matches)

Last 200 lines that contain `msg=abc123` (matches raw text before redaction):

```json
{"pattern": "msg=abc123", "lines": 200}
```

### Tail — pagination (`offset_from_tail`)

Skip the newest 50 lines, return the next 50 older lines (“page 2”):

```json
{"offset_from_tail": 50, "lines": 50}
```

Skip the newest 300, return the following 50 (deeper history without reading the head):

```json
{"offset_from_tail": 300, "lines": 50}
```

Paginate through WARN/ERROR matches: skip the 20 newest matches, return the next 30:

```json
{"pattern": "ERROR|WARN", "offset_from_tail": 20, "lines": 30}
```

### From-line — read forward from a line number

Lines 100–149 (1-based, inclusive start):

```json
{"starting_reading_line": 100, "lines": 50}
```

From the top of the file, only lines mentioning `tool_call`:

```json
{"starting_reading_line": 1, "lines": 200, "pattern": "tool_call"}
```

### Ranges — explicit slices

Single interval (lines 10–50):

```json
{"ranges": ["10-50"], "lines": 500}
```

Multiple intervals (colon or dash separators):

```json
{"ranges": ["100:120", "500-520"], "lines": 500}
```

Slice plus regex inside the range:

```json
{"ranges": ["1-1000"], "lines": 500, "pattern": "session_id="}
```

### File selection (combine with any mode above)

Proxy log, default tail:

```json
{"file": "proxy.log", "lines": 80}
```

Rotated gateway log, read from the beginning:

```json
{
  "file": "gateway-20260525T143417Z.log",
  "starting_reading_line": 1,
  "lines": 100
}
```

If `file` is wrong, the failure envelope’s `data.available` lists every `*.log`
under `logs/` — pick a name from there and retry.

## Success envelope (`ok=true`)

```json
{
  "ok": true,
  "data": {
    "path": "logs/gateway.log",
    "file": "gateway.log",
    "lines": ["INFO …", "WARN …"],
    "line_numbers": [651, 652],
    "count": 2,
    "mode": "tail",
    "total_file_lines": 1200,
    "pattern": null,
    "offset_from_tail": 300,
    "starting_reading_line": null,
    "ranges": null
  }
}
```

## Failure envelopes (`ok=false`, all `VALIDATION_ERROR`)

- **File not found** — `data.available` lists every `*.log` under `<workspace>/logs/`.
- **Path-traversal rejected** — `file` contains `/`, `\`, or `..`.
- **Invalid regex** — `pattern` failed to compile.
- **Conflicting modes** — more than one of `ranges`, `starting_reading_line`, and `offset_from_tail > 0`.
- **Invalid range** — malformed `ranges` entry (use `start-end` or `start:end`, 1-based inclusive).

## Redaction

Each returned line is passed through `redact_log_line` before inclusion. Regex
`pattern` matches **raw** text before redaction.

## Related

- `process` — inspect background subprocesses.
- `terminal_run` — richer log access when tail/range windows are not enough.

## Implementation note

Canonical argument dicts for each form are defined in code as
`LOG_QUERY_ARGUMENT_FORMS` in `src/sevn/tools/log_query.py`.
