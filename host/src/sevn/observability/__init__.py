"""OTel tracing export to Logfire or an OTLP collector (spec D27, §12; plan 0015).

- ``presets``: endpoints and headers per signal, including the Datadog presets.
- ``setup``: install or skip the exporter at startup; the handle flushes at close.
- ``redact``: secret scrubbing for every exported span, and content hashing.

Submodules are imported directly; this package re-exports nothing so importing it
stays cheap and ``sevn.observability.setup`` always names the module.
"""
