"""Egress posture helpers inside sandbox namespaces (``specs/08-sandbox.md`` §4.2, §8.2).

Module: sevn.security.egress_firewall
Depends: sys

Exports:
    egress_firewall_noop — subprocess / dev shim (explicit no-op).
    write_macos_pf_ruleset — render pf anchor rules for subprocess mode (operator load).
    write_linux_iptables_ruleset — render iptables-restore rules for namespace mode.
    apply_namespace_egress_firewall — write rules; optional apply when ``SEVN_SANDBOX_IPTABLES_APPLY=1``.

Examples:
    >>> egress_firewall_noop(None) is None
    True
"""

from __future__ import annotations

import os
import shutil
import subprocess  # nosec B404
import sys
from pathlib import Path


def write_macos_pf_ruleset(
    dest: Path,
    *,
    proxy_host: str = "127.0.0.1",
    proxy_port: int = 8787,
) -> Path:
    """Write a minimal pf ruleset allowing loopback + proxy egress (subprocess mode).

    Operators load with ``sudo pfctl -f <dest>`` when ``SEVN_SANDBOX_PF=1``.

    Args:
        dest (Path): Output path for the rules file.
        proxy_host (str, optional): Allowed proxy host. Defaults to loopback.
        proxy_port (int, optional): Allowed proxy port. Defaults to 8787.

    Returns:
        Path: ``dest`` after write.

    Examples:
        >>> write_macos_pf_ruleset.__name__
        'write_macos_pf_ruleset'
    """
    if sys.platform != "darwin":
        msg = "write_macos_pf_ruleset is only meaningful on macOS"
        raise OSError(msg)
    body = (
        "# sevn.bot subprocess sandbox pf shim (specs/08-sandbox.md)\n"
        "set skip on lo0\n"
        f"pass out proto tcp from any to {proxy_host} port {proxy_port}\n"
        "block out log all\n"
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(body, encoding="utf-8")
    return dest


def egress_firewall_noop(_reason: str | None = None) -> None:
    """No-op for subprocess sandbox mode (§4.3; best-effort only).

    Args:
        _reason (str | None): Optional diagnostics label for callers.

    Returns:
        None: Always.

    Examples:
        >>> egress_firewall_noop() is None
        True
    """
    return


def write_linux_iptables_ruleset(
    dest: Path,
    *,
    proxy_host_ports: tuple[str, ...],
) -> Path:
    """Write iptables-restore rules allowing loopback + listed proxy TCP ports.

    Operators apply with ``iptables-restore <dest>`` when ``SEVN_SANDBOX_IPTABLES_APPLY=1``.

    Args:
        dest (Path): Output path for the rules file.
        proxy_host_ports (tuple[str, ...]): Allowed ``host:port`` endpoints.

    Returns:
        Path: ``dest`` after write.

    Examples:
        >>> write_linux_iptables_ruleset.__name__
        'write_linux_iptables_ruleset'
    """
    if not sys.platform.startswith("linux"):
        msg = "write_linux_iptables_ruleset is only meaningful on Linux"
        raise OSError(msg)
    lines = [
        "# sevn.bot Docker namespace egress shim (specs/08-sandbox.md)",
        "*filter",
        ":INPUT ACCEPT [0:0]",
        ":FORWARD ACCEPT [0:0]",
        ":OUTPUT DROP [0:0]",
        "-A OUTPUT -o lo -j ACCEPT",
    ]
    for hp in proxy_host_ports:
        host, _, port_s = hp.partition(":")
        if not host or not port_s.isdigit():
            continue
        lines.append(f"-A OUTPUT -p tcp -d {host} --dport {port_s} -j ACCEPT")
    lines.append("-A OUTPUT -j REJECT")
    lines.append("COMMIT")
    body = "\n".join(lines) + "\n"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(body, encoding="utf-8")
    return dest


def apply_namespace_egress_firewall(
    *,
    proxy_host_ports: tuple[str, ...],
    egress_domains: tuple[str, ...] | None = None,
) -> None:
    """Write (and optionally apply) DROP-by-default egress rules for a sandbox namespace.

    Args:
        proxy_host_ports (tuple[str, ...]): Explicit proxy endpoints (host:port).
        egress_domains (tuple[str, ...] | None): Reserved for future domain rules.

    Returns:
        None: After rules are written or applied.

    Examples:
        >>> apply_namespace_egress_firewall(proxy_host_ports=("127.0.0.1:8787",)) is None
        True
    """
    _ = egress_domains
    if not proxy_host_ports:
        msg = "proxy_host_ports must be non-empty"
        raise ValueError(msg)
    rules_path = Path(
        os.environ.get("SEVN_SANDBOX_IPTABLES_RULES", "/tmp/sevn-iptables.rules"),  # nosec B108
    )
    if sys.platform.startswith("linux"):
        write_linux_iptables_ruleset(rules_path, proxy_host_ports=proxy_host_ports)
    elif sys.platform == "darwin":
        host, _, port_s = proxy_host_ports[0].partition(":")
        write_macos_pf_ruleset(
            rules_path.with_suffix(".pf.rules"),
            proxy_host=host or "127.0.0.1",
            proxy_port=int(port_s) if port_s.isdigit() else 8787,
        )
    else:
        msg = f"namespace egress firewall unsupported on {sys.platform!r}"
        raise OSError(msg)
    if os.environ.get("SEVN_SANDBOX_IPTABLES_APPLY") == "1" and sys.platform.startswith("linux"):
        _apply_iptables_rules(rules_path)


def _apply_iptables_rules(rules_path: Path) -> None:
    """Load ``rules_path`` via ``iptables-restore`` when operator opts in.

    Args:
        rules_path (Path): Rules file from ``write_linux_iptables_ruleset``.

    Returns:
        None: Always.

    Examples:
        >>> _apply_iptables_rules.__name__
        '_apply_iptables_rules'
    """
    restore = shutil.which("iptables-restore") or "iptables-restore"
    subprocess.run(  # nosec B603
        [restore, str(rules_path)],
        capture_output=True,
        text=True,
        check=False,
    )
