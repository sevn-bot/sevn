"""Security policy and sandboxing (``specs/08-sandbox.md``).

Module: sevn.security
Depends: sevn.security.egress_firewall, sevn.security.sandbox_errors, sevn.security.sandbox_runtime,
    sevn.security.sandbox_sweeper

Exports:
    SandboxError — base sandbox failure type.
    SandboxConfigurationError — misconfiguration/missing prerequisites.
    SandboxPolicyViolationError — denylist rejection.
    SandboxDriver — driver enum.
    SandboxRuntime — asyncio isolation protocol.
    SubprocessSandboxRuntime — dev subprocess path.
    DockerSandboxRuntime — production Docker stub.
    docker_daemon_reachable — Docker probe helper.
    resolve_sandbox_driver — policy helper.
    make_runtime_for_driver — sandbox factory by driver.
    check_self_preservation_argv — denylist checker.
    build_sandbox_child_env — sandbox env bootstrap.
    materialize_shadow_workspace — shadow symlink farm.
    write_workspace_snapshot_tarball — gzip snapshot helper.
    load_snapshot_manifest_version — manifest reader.
    snapshot_tarball_format_supported — supported ``format_version`` predicate.
    prune_workspace_snapshots — retention-based snapshot pruning.
    egress_firewall_noop — dev egress shim.
    apply_namespace_egress_firewall — namespace firewall (**NotImplemented**).
    SandboxRunRegistry — orphan sweeper gateway port.
    SandboxLabeledContainer — sweeper docker row stub.
    orphan_container_should_kill — orphan TTL predicate.
    sweep_orphan_labels — batch sweep helper.

Examples:
    >>> from sevn.security import SandboxDriver
    >>> SandboxDriver.docker.value
    'docker'
"""

from __future__ import annotations

from sevn.security.egress_firewall import apply_namespace_egress_firewall, egress_firewall_noop
from sevn.security.sandbox_errors import (
    SandboxConfigurationError,
    SandboxError,
    SandboxPolicyViolationError,
)
from sevn.security.sandbox_runtime import (
    DockerSandboxRuntime,
    SandboxDriver,
    SandboxRuntime,
    SubprocessSandboxRuntime,
    build_sandbox_child_env,
    check_self_preservation_argv,
    docker_daemon_reachable,
    load_snapshot_manifest_version,
    make_runtime_for_driver,
    materialize_shadow_workspace,
    prune_workspace_snapshots,
    resolve_sandbox_driver,
    snapshot_tarball_format_supported,
    write_workspace_snapshot_tarball,
)
from sevn.security.sandbox_sweeper import (
    SandboxLabeledContainer,
    SandboxRunRegistry,
    orphan_container_should_kill,
    sweep_orphan_labels,
)

__all__ = [
    "DockerSandboxRuntime",
    "SandboxConfigurationError",
    "SandboxDriver",
    "SandboxError",
    "SandboxLabeledContainer",
    "SandboxPolicyViolationError",
    "SandboxRunRegistry",
    "SandboxRuntime",
    "SubprocessSandboxRuntime",
    "apply_namespace_egress_firewall",
    "build_sandbox_child_env",
    "check_self_preservation_argv",
    "docker_daemon_reachable",
    "egress_firewall_noop",
    "load_snapshot_manifest_version",
    "make_runtime_for_driver",
    "materialize_shadow_workspace",
    "orphan_container_should_kill",
    "prune_workspace_snapshots",
    "resolve_sandbox_driver",
    "snapshot_tarball_format_supported",
    "sweep_orphan_labels",
    "write_workspace_snapshot_tarball",
]
