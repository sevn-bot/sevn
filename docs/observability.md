# Observability

The host can export OpenTelemetry traces, logs and metrics over OTLP to Logfire, to Datadog, or to any OTLP collector. Each user message is one trace. Export is off until you pick an exporter or store a Logfire token. No secret value is written to any span, log record or metric.

## Turning it on

Settings live in the `[observability]` table of `$SEVN_HOME/config.toml`. Every field can also be set with a `SEVN_OBSERVABILITY__<FIELD>` environment variable, for example `SEVN_OBSERVABILITY__EXPORTER=otlp`.

| Field | Default | What it does |
|---|---|---|
| `exporter` | unset | `logfire`, `otlp` or `none`. Unset means Logfire when the secret `logfire/token` exists, otherwise off. `none` turns export off even when a token is stored. |
| `preset` | `""` | `datadog-agent` or `datadog-agentless`. Used only with `exporter = "otlp"`. |
| `endpoint` | `""` | Base OTLP URL, such as `http://localhost:4318`. sevn adds `/v1/traces`, `/v1/logs` and `/v1/metrics` for `http/protobuf`. |
| `headers` | `{}` | Extra request headers. Each value must be a `secret://<name>` reference. A plain value is a config error. |
| `protocol` | `http/protobuf` | `http/protobuf` or `grpc`. |
| `capture_content` | `false` | Record message text and tool arguments in spans. See [Message content](#message-content). |
| `sample_ratio` | `1.0` | Share of traces to keep, from `0.0` to `1.0`. |
| `datadog_site` | `datadoghq.com` | Datadog site for `datadog-agentless`. |
| `service_name` | `sevnd` | `service.name` on every span. |

Every span also carries `service.version`, `sevn.host_id`, and `deployment.environment` (also as `deployment.environment.name`, the current semantic-convention key that Datadog reads), which is `SEVN_ENV` or `local` when that is unset.

With `exporter = "otlp"` and no `endpoint`, the host reads the standard `OTEL_EXPORTER_OTLP_ENDPOINT` variable. A set `endpoint` wins. The standard variable is ignored for every other exporter.

Restart `sevn serve` after changing the table, then check it with `sevn doctor --check` (see [Checking the setup](#checking-the-setup)).

## Logfire

Store a Logfire project write token. That is all Logfire needs:

```bash
sevn secret set logfire/token
```

With `exporter` unset, the stored token turns Logfire on. Write `exporter = "logfire"` to make the choice explicit. The region (US or EU) comes from the token. The `LOGFIRE_BASE_URL` environment variable overrides it, for a self-hosted Logfire.

sevn sends spans, logs and metrics to Logfire's intake through its own exporters, so the same redaction runs on the Logfire path as on the OTLP path. Logfire's own scrubbing also runs on top.

## Datadog Agent

Use this path when a Datadog Agent runs on the same machine. The Agent holds the API key, so sevn sends no headers.

Turn on the Agent's OTLP receiver in `datadog.yaml`:

```yaml
otlp_config:
  receiver:
    protocols:
      http:
        endpoint: localhost:4318
      grpc:
        endpoint: localhost:4317
  logs:
    enabled: true
```

A containerised Agent takes the same settings as environment variables, for example `DD_OTLP_CONFIG_RECEIVER_PROTOCOLS_HTTP_ENDPOINT=0.0.0.0:4318` and `DD_OTLP_CONFIG_LOGS_ENABLED=true`.

Then point sevn at it:

```toml
[observability]
exporter = "otlp"
preset = "datadog-agent"
```

The preset sends to `http://localhost:4318`, or `http://localhost:4317` with `protocol = "grpc"`. Set `endpoint` when the Agent listens somewhere else. Traces land in APM. The `dd-otlp-source: llmobs` header that routes traces into LLM Observability is added by the agentless preset only.

## Datadog agentless

Use this path to send straight to Datadog's OTLP intake with no Agent. Store a Datadog API key:

```bash
sevn secret set datadog/api_key
```

```toml
[observability]
exporter = "otlp"
preset = "datadog-agentless"
datadog_site = "datadoghq.eu"
```

The preset sends to `https://otlp.<datadog_site>/v1/traces`, `/v1/logs` and `/v1/metrics`, for example `otlp.datadoghq.com`, `otlp.us3.datadoghq.com`, `otlp.datadoghq.eu`, `otlp.ap1.datadoghq.com` or `otlp.ddog-gov.com`. Every request carries `dd-api-key`, read from `secret://datadog/api_key`. To keep the key under another name, set `headers = { "dd-api-key" = "secret://<name>" }`.

Trace requests also carry `dd-otlp-source: llmobs`, so traces appear in LLM Observability as well as APM, and `compute_stats: true`, without which Datadog computes no trace metrics for agentless traffic and the service does not appear on the APM service pages. Datadog keeps unindexed spans in APM Live Search for 15 minutes; older spans are searchable only if a retention filter indexed them. The model call spans follow the OTel GenAI semantic conventions, which LLM Observability reads, and the LLM Observability app name is the root span's service (`service_name`).

Datadog's agentless intake accepts `http/protobuf` only. `datadog-agentless` with `protocol = "grpc"` is a config error.

## Any OTLP collector

Any collector that speaks OTLP works, such as the OpenTelemetry Collector, Grafana Alloy, Jaeger or Honeycomb:

```toml
[observability]
exporter = "otlp"
endpoint = "https://otlp.example.com"
headers = { "x-api-key" = "secret://otlp/key" }
```

Store the header value first with `sevn secret set otlp/key`. The host reads header secrets only when it builds the exporters at startup, and never prints them. For gRPC, set `protocol = "grpc"`; the endpoint is then used as written for all three signals.

## What a trace holds

One message is one trace:

- `job`: the root, opened when the message arrives. It carries `sevn.source`, `sevn.job_id` and `sevn.bot_id`.
- `route.decide`: one span per routing step (rules, jev, the fallback chain), with `sevn.decision_path`, `sevn.confidence` and `sevn.accepted`.
- `turn`: the agent's turn, with `sevn.runtime`, `gen_ai.request.model`, `gen_ai.usage.input_tokens` and `output_tokens`, `sevn.cost_usd`, `sevn.cost_source` and `sevn.stop`. A failed turn has status ERROR.
- Under the turn: Pydantic AI's `chat` and `execute_tool <name>` spans, or `tool.<name>` spans for the Claude runtime.

The trace context is stored on the job (`jobs.trace_parent`), so a turn that runs later, or after a host restart, stays in the message's trace. Span names never contain ids. HTTP requests to the host are spans too, with `http.route`.

Log records carry `trace_id` and `span_id`, in the JSON log file as well. With an exporter on, records at INFO and above are exported as OTel logs. The host also exports four gauges every 60 seconds: `sevn.jobs.queued` (per bot), `sevn.turns.running`, `sevn.agents.open` and `sevn.ollama.reachable`.

## Sampling

`sample_ratio` keeps that share of traces, chosen by trace id. A span whose parent was sampled is always kept, so a trace is never cut in half. `0.0` exports no traces. Logs and metrics are not sampled.

## Message content

With `capture_content = false`, the default, message text and tool arguments are never written to a span. sevn spans record `sevn.content.size` (UTF-8 bytes) and `sevn.content.sha256` instead, and Pydantic AI's model spans leave prompts and replies out.

With `capture_content = true`, sevn spans also record `sevn.content.text`, and the model spans include the messages sent and received. That text still goes through redaction first.

## Redaction

- Every secret the host has read is replaced with `«redacted:<name>»` wherever it appears: span attributes, span events, status messages and log records.
- Common key shapes are masked even when the host never read them: `sk-…`, `sk-ant-…`, `xox[abp]-…`, `ghp_…`, `AKIA…`, `Bearer …` and JWT-shaped strings.
- The content hash is taken of the redacted text, so it cannot be used to confirm a guessed secret.
- Header values are `secret://` references in the config and are resolved only inside the exporter. `sevn doctor` names the exporter by its preset or endpoint host, never by a header.
- No export credential enters a child CLI's environment (see below).

Redaction catches the values the host knows and the key shapes above. It cannot spot an unknown secret pasted into a message, which is one reason `capture_content` is off by default.

## CLI runtimes

A CLI runtime gets the turn's `TRACEPARENT` (and `TRACESTATE` when set), so a CLI that reads it nests its own spans under the sevn `turn`. When sevn exports to a collector on loopback (`exporter = "otlp"` with a `localhost`, `127.0.0.1` or `::1` endpoint, or the `datadog-agent` preset), the CLI also gets `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_EXPORTER_OTLP_PROTOCOL` and `OTEL_SERVICE_NAME=sevn-cli-<runtime>`. The Logfire token, a Datadog key and every `headers` value stay out of the child environment, because the CLI and every tool it runs can read it. So with Logfire, agentless Datadog or a remote collector, sevn points no CLI at a collector. The Claude runtime gets these variables today; the Codex, OpenCode and Cursor runtimes follow the same rule when they are added.

| CLI | What it exports | Nests under the turn |
|---|---|---|
| Claude Code | Metrics and log events, switched on with `CLAUDE_CODE_ENABLE_TELEMETRY=1`, which sevn sets for a loopback collector. Its traces are a beta behind `CLAUDE_CODE_ENHANCED_TELEMETRY_BETA=1` and `OTEL_TRACES_EXPORTER=otlp`, which sevn does not set. Prompts and tool details stay off. | Yes. It reads `TRACEPARENT` in Agent SDK sessions, and its Bash commands inherit it. |
| Codex | Only when `[otel]` is configured in `~/.codex/config.toml`; `OTEL_*` variables alone do not turn it on. | Yes, from `TRACEPARENT` when the request carries no trace context. |
| OpenCode | Nothing built in. Third-party plugins read `OTEL_EXPORTER_OTLP_*`. | No; sevn-side spans only. |
| Cursor | Nothing from the CLI. Enterprise admin export only (metrics and logs). | No; sevn-side spans only. |

Every runtime gets the sevn-side `turn` and `tool.<name>` spans whether or not its CLI exports anything.

## When export fails

Tracing never changes what the host does. A missing token or header secret, a bad endpoint, or an unreachable collector never fails startup, a request or a turn.

- A setup problem (a missing header secret, an endpoint that is not an `http://` or `https://` URL, or another tracer provider already installed in the process) is logged once at WARNING and leaves export off.
- An export failure is logged at WARNING at most once every 10 minutes per exporter. The exporter retries for up to 5 seconds, then drops that batch.
- At most 2,048 spans, and 2,048 log records, wait for export. Past that, new ones are dropped, and each one is counted in `sevn.otel.dropped` (`sevn.signal` is `traces` or `logs`).
- Shutdown flushes what is left and never holds the host for more than 5 seconds.

## Checking the setup

`sevn doctor` prints the effective exporter and the content setting. `--check` also sends one test span and reports whether the endpoint accepted it:

```text
observability_exporter: otlp:datadog-agentless
observability_content: off
observability_check: ok
```

`observability_exporter` is `none`, `logfire`, or `otlp:<preset or endpoint host>`. `observability_check` is `ok`, `failed: …` with the reason, or `off` when no exporter is on. `sevn doctor --json` prints the same keys.

`sevn traces test` sends one `sevn.test` span and prints its trace id. The span carries `sevn.canary`, a fresh value registered as a secret, so in the backend it must read `«redacted:traces/canary»`. Search for the trace id in Logfire or Datadog to see both the export and the redaction. With export off the command exits 1 and says why: the exporter is `none`, or `exporter = "none"` turns export off by config. A failed export exits 1 with `failed: …`.

```bash
sevn traces test
```
