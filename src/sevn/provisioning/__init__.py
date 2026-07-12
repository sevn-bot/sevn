"""Host-dependency provisioning for ``sevn sync`` and gateway (re)start.

Module: sevn.provisioning

Exports:
    HostDep — one provisionable host binary/library with probe + install plan.
    ProvisionOutcome — result row for one dependency.
    ProvisionReport — aggregated provisioning results.
    HOST_DEPS — registry of the selectable host dependencies.
    host_dep_ids — sorted registry ids (config allowlist).
    provision_host_deps — install selected-and-missing host dependencies (idempotent).
    summarize_report — one-line human summary of a provisioning pass.
"""

from __future__ import annotations

from sevn.provisioning.host_deps import (
    HOST_DEPS,
    HostDep,
    ProvisionOutcome,
    ProvisionReport,
    host_dep_ids,
    provision_host_deps,
    summarize_report,
)

__all__ = [
    "HOST_DEPS",
    "HostDep",
    "ProvisionOutcome",
    "ProvisionReport",
    "host_dep_ids",
    "provision_host_deps",
    "summarize_report",
]
