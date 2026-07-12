"""Argv self-preservation coordination with **specs/08-sandbox.md** §8.3.

See **`tests/sandbox`** for subprocess runtime integration; denylist predicates are
validated here independently of Docker availability.
"""

from __future__ import annotations

from sevn.security.sandbox_runtime import check_self_preservation_argv


def test_self_preservation_allows_echo() -> None:
    assert check_self_preservation_argv(["/bin/echo", "hello"]) is None


def test_self_preservation_blocks_pkill() -> None:
    assert check_self_preservation_argv(["pkill", "python"]) is not None


def test_self_preservation_blocks_docker_kill_sevn_prefix() -> None:
    rule = check_self_preservation_argv(["docker", "kill", "sevn-gateway"])
    assert rule is not None


def test_pid_gate_stub_optional_set() -> None:
    from sevn.security.sandbox_runtime import pid_target_gate_stub

    assert pid_target_gate_stub(["kill", "999"], forbidden_pids=frozenset({999})) is not None
