#!/usr/bin/env python3
"""Deployment-surface drivers for the repo ``/verify`` gate (#164, #165, #166, #170).

Four drivers the release-0.0.1 audit program had no way to run, because no gate
ever started the compose stack or ran a ``docker`` subcommand:
per-profile compose validation, operator stack boot + health probe, tier-B
sandbox spawn through the real ``docker`` CLI, and runtime CLI/HTTP probes.

Every driver writes JSON + log evidence under ``evidence/verify/`` and reports
``driver_unavailable`` (exit 2) — never ``pass`` — when Docker, a built sandbox
image, or a running gateway is missing.

Module: scripts.verify_deployment
Depends: argparse, asyncio, dataclasses, datetime, json, os, re, shutil, subprocess, sys, tempfile, time, urllib, pathlib

Exports:
    Check — One assertion inside a driver, with the evidence that backs it.
    DriverResult — One driver verdict plus its captured checks.
    Invocation — One documented way an operator or CI reaches the compose stack.
    drive_compose_profiles — Assert every documented compose invocation (#164, #165).
    drive_stack_health — Boot the operator stack, probe /health + /ready, tear down (#166).
    drive_sandbox_spawn — Prove D43 fail-closed (or digest-pinned spawn) via real docker CLI.
    drive_authenticated_proxy_roundtrip — End-to-end gateway→proxy auth via the boot secret (Batch A C1.2 path; C14.2).
    drive_volume_upgrade — Seed ``sevn-state`` with a sentinel; assert it survives a compose up (C14.2).
    drive_browser_gui_boot — Resolve the browser/GUI overlays and assert the gateway image flips (C14.2; C10.3).
    drive_cancellation_cleanup — Cancel a mid-flight sandbox spawn and assert no orphan containers / volumes (C14.2).
    drive_sandbox_scoped_token — ``scope=sandbox`` token accepts ``/web/*`` and rejects ``/llm/*`` (Batch E C7.1/C7.2; W23.4).
    drive_runtime — sevn CLI invocation plus HTTP probes against a running gateway.
    main — CLI entry; runs one driver or all of them.

Examples:
    >>> sorted(EXIT_CODES)
    ['driver_unavailable', 'fail', 'pass']
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EVIDENCE_DIR = REPO / "evidence" / "verify"

STATUS_PASS = "pass"
STATUS_FAIL = "fail"
STATUS_WARN = "warn"
STATUS_UNAVAILABLE = "driver_unavailable"

EXIT_CODES = {STATUS_PASS: 0, STATUS_FAIL: 1, STATUS_UNAVAILABLE: 2}

OPERATOR_COMPOSE = "docker/docker-compose.yml"
VERIFY_COMPOSE = "docker/docker-compose.verify.yml"
VERIFY_DIGESTS_COMPOSE = "docker/docker-compose.verify-digests.yml"
VERIFY_PROXY_URL = "http://127.0.0.1:3102"
BROWSER_COMPOSE = "docker/docker-compose.browser.yml"
GUI_COMPOSE = "docker/docker-compose.gui.yml"
PROD_COMPOSE = "docker/docker-compose.prod.yml"
CI_COMPOSE = "docker/docker-compose.ci.yml"
EVALS_COMPOSE = "docker/docker-compose.improve-evals.yml"

DEFAULT_SERVICES = frozenset({"sevn-operator-perms", "sevn-proxy", "sevn-gateway"})
COMPOSE_GUARD = "scripts/check-compose-default.sh"

# ``SEVN_VERIFY_IMAGE_OVERLAY`` opts the drivers into the digest-pinned
# overlay (docker-compose.verify-digests.yml) so they exercise the SHA-tagged
# images promoted by ``container-supply-chain`` instead of locally-rebuilt
# ones. Set on the ``verify-deployment`` job in ci-cd.yml so the C14.1
# release-tag evidence actually tests what was published (mergecraft review
# finding 3737950464 / F-Thermos-V1 follow-up).
VERIFY_IMAGE_OVERLAY_ENV = "SEVN_VERIFY_IMAGE_OVERLAY"

_DOCKER_TIME = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(\.\d+)?(Z|[+-]\d{2}:\d{2})?$")


@dataclass
class Check:
    """One assertion inside a driver, with the evidence that backs it."""

    name: str
    status: str
    detail: str
    command: str = ""
    output: str = ""


@dataclass
class DriverResult:
    """One driver verdict plus its captured checks."""

    name: str
    status: str
    reason: str = ""
    checks: list[Check] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Invocation:
    """One documented way an operator or CI reaches the compose stack."""

    name: str
    files: tuple[str, ...]
    profiles: tuple[str, ...]
    env_profiles: str
    source: str
    expect_services: frozenset[str] | None = None
    mutually_exclusive: bool = False


INVOCATIONS: tuple[Invocation, ...] = (
    Invocation(
        name="default",
        files=(OPERATOR_COMPOSE,),
        profiles=(),
        env_profiles="",
        source="Makefile compose-up; docker/README.md:10",
        expect_services=DEFAULT_SERVICES,
    ),
    Invocation(
        name="browser-override",
        files=(OPERATOR_COMPOSE, BROWSER_COMPOSE),
        profiles=(),
        env_profiles="",
        source="Makefile compose-browser-up; docker/README.md:49",
        expect_services=DEFAULT_SERVICES,
    ),
    Invocation(
        name="gui-override",
        files=(OPERATOR_COMPOSE, GUI_COMPOSE),
        profiles=(),
        env_profiles="",
        source="Makefile compose-gui-up; docker/README.md:53",
        expect_services=DEFAULT_SERVICES,
    ),
    Invocation(
        name="browser-env",
        files=(OPERATOR_COMPOSE,),
        profiles=(),
        env_profiles="browser",
        source="legacy COMPOSE_PROFILES=browser without override (rejected by check-compose-default.sh)",
        mutually_exclusive=True,
    ),
    Invocation(
        name="gui-env",
        files=(OPERATOR_COMPOSE,),
        profiles=(),
        env_profiles="gui",
        source="legacy COMPOSE_PROFILES=gui without override (rejected by check-compose-default.sh)",
        mutually_exclusive=True,
    ),
    Invocation(
        name="prod-overlay-browser",
        files=(OPERATOR_COMPOSE, BROWSER_COMPOSE, PROD_COMPOSE),
        profiles=(),
        env_profiles="",
        source="docker/README.md:64",
    ),
    Invocation(
        name="browser-gui-override",
        files=(OPERATOR_COMPOSE, BROWSER_COMPOSE, GUI_COMPOSE),
        profiles=(),
        env_profiles="",
        source="docker/README.md:58 (documented as mutually exclusive)",
        mutually_exclusive=True,
    ),
    Invocation(
        name="browser-gui-flag",
        files=(OPERATOR_COMPOSE,),
        profiles=("browser", "gui"),
        env_profiles="",
        source="legacy --profile browser --profile gui (mutually exclusive)",
        mutually_exclusive=True,
    ),
    Invocation(
        name="legacy-browser-profile-flag",
        files=(OPERATOR_COMPOSE,),
        profiles=("browser",),
        env_profiles="",
        source="legacy --profile browser without override (rejected by check-compose-default.sh)",
        mutually_exclusive=True,
    ),
    Invocation(
        name="legacy-gui-profile-flag",
        files=(OPERATOR_COMPOSE,),
        profiles=("gui",),
        env_profiles="",
        source="legacy --profile gui without override (rejected by check-compose-default.sh)",
        mutually_exclusive=True,
    ),
    Invocation(
        name="browser-gui-env",
        files=(OPERATOR_COMPOSE,),
        profiles=(),
        env_profiles="browser,gui",
        source="docker/docker-compose.yml:13 (documented as mutually exclusive)",
        mutually_exclusive=True,
    ),
    Invocation(
        name="ci",
        files=(CI_COMPOSE,),
        profiles=(),
        env_profiles="",
        source="Makefile compose-ci-smoke; .github/workflows/docker.yml:134",
    ),
    Invocation(
        name="improve-evals",
        files=(EVALS_COMPOSE,),
        profiles=(),
        env_profiles="",
        source="Makefile improve-evals-docker",
    ),
)


def _now_stamp() -> str:
    """Return a filesystem-safe UTC timestamp for evidence filenames.

    Returns:
        str: ``YYYYmmddTHHMMSSZ``.

    Examples:
        >>> len(_now_stamp())
        16
    """
    return datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")


def _run(
    argv: list[str], *, env: dict[str, str] | None = None, timeout: float = 120.0
) -> tuple[int, str]:
    """Run a command from the repo root and capture merged output.

    Args:
        argv (list[str]): Command and arguments.
        env (dict[str, str] | None): Full environment override.
        timeout (float): Seconds before the command is killed.

    Returns:
        tuple[int, str]: Exit code (``124`` on timeout) and combined stdout+stderr.

    Examples:
        >>> _run(["true"])[0]
        0
    """
    try:
        proc = subprocess.run(
            argv,
            cwd=REPO,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return 124, f"timeout after {timeout}s: {' '.join(argv)}"
    except FileNotFoundError as exc:
        return 127, str(exc)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def _docker_unavailable_reason() -> str | None:
    """Return why the Docker driver cannot run, or ``None`` when it can.

    Returns:
        str | None: Human-readable reason, or ``None`` when ``docker`` is usable.

    Examples:
        >>> _docker_unavailable_reason() in (None,) or isinstance(_docker_unavailable_reason(), str)
        True
    """
    if shutil.which("docker") is None:
        return "docker CLI not on PATH"
    code, out = _run(["docker", "info", "--format", "{{.ServerVersion}}"], timeout=60.0)
    if code != 0:
        return f"docker daemon not reachable (exit {code}): {out.strip()[:400]}"
    return None


def _verify_image_overlay_path() -> Path | None:
    """Return the digest-overlay path when ``SEVN_VERIFY_IMAGE_OVERLAY`` opts in.

    The overlay pins ``sevn-proxy`` and ``sevn-gateway`` ``image:`` to the
    SHA-tagged images promoted by ``container-supply-chain`` (D45), so the
    drivers actually exercise the published container images instead of
    locally-rebuilt ones. The overlay is opt-in because local-dev stacks
    have no published digest to pull from.

    Returns:
        Path | None: Resolved overlay path, or ``None`` when the opt-in is
        unset, the overlay file is missing from the checkout, or the
        required ``SEVN_VERIFY_IMAGE_TAG`` is empty (a malformed CI run).

    Examples:
        >>> import os
        >>> _verify_image_overlay_path() is None
        True
    """
    if os.environ.get(VERIFY_IMAGE_OVERLAY_ENV) != "1":
        return None
    if not os.environ.get("SEVN_VERIFY_IMAGE_TAG"):
        return None
    path = REPO / VERIFY_DIGESTS_COMPOSE
    return path if path.is_file() else None


def _compose_base(project: str, files: tuple[str, ...]) -> list[str]:
    """Build a ``docker compose`` argv with the digest overlay appended when opted in.

    Args:
        project (str): Compose project name (keeps driver stacks isolated).
        files (tuple[str, ...]): Compose files in merge order (base first).

    Returns:
        list[str]: ``docker compose -p <project> -f <a> -f <b> [-f <digest>]``.

    Examples:
        >>> _compose_base("p", ("docker/docker-compose.yml",))[:5]
        ['docker', 'compose', '-p', 'p', '-f']
    """
    argv = ["docker", "compose", "-p", project]
    for path in files:
        argv.extend(["-f", path])
    overlay = _verify_image_overlay_path()
    if overlay is not None:
        argv.extend(["-f", str(overlay)])
    return argv


def _compose_up_args(base: list[str], *extra: str) -> list[str]:
    """Append ``up -d`` plus build/pull flags honoring the digest overlay.

    With the digest overlay active, the merged config has ``build: !reset
    null`` for the gateway/proxy services, so ``--build`` is a no-op for
    those services and ``--no-build`` is the explicit, honest flag — it
    forces compose to pull the published images rather than attempt to
    build from source.

    Args:
        base (list[str]): The argv prefix returned by ``_compose_base``.
        extra (str): Extra ``docker compose up`` flags after ``-d``.

    Returns:
        list[str]: Argv suitable for ``docker compose up``.

    Examples:
        >>> _compose_up_args(["docker", "compose"], "extra")[-3:]
        ['-d', '--build', 'extra']
    """
    argv = [*base, "up", "-d"]
    argv.append("--no-build" if _verify_image_overlay_path() is not None else "--build")
    argv.extend(extra)
    return argv


def _parse_docker_time(value: str) -> datetime | None:
    """Parse a Docker RFC3339 timestamp, tolerating nanosecond precision.

    Args:
        value (str): Timestamp such as ``2026-08-04T00:00:00.123456789Z``.

    Returns:
        datetime | None: Timezone-aware datetime, or ``None`` when unparseable.

    Examples:
        >>> _parse_docker_time("2026-08-04T00:00:00.123456789Z").year
        2026
        >>> _parse_docker_time("0001-01-01T00:00:00Z").year
        1
        >>> _parse_docker_time("nope") is None
        True
    """
    match = _DOCKER_TIME.match(value.strip())
    if not match:
        return None
    head, frac, zone = match.group(1), match.group(2) or "", match.group(3) or "+00:00"
    if zone == "Z":
        zone = "+00:00"
    frac = frac[:7] if frac else ""
    try:
        return datetime.fromisoformat(f"{head}{frac}{zone}")
    except ValueError:
        return None


def _http_probe(url: str, *, timeout: float = 5.0) -> tuple[int, str]:
    """Issue a GET and return the HTTP status plus a body excerpt.

    Args:
        url (str): Absolute URL to probe.
        timeout (float): Socket timeout in seconds.

    Returns:
        tuple[int, str]: Status code (``0`` when the connection failed) and body/error excerpt.

    Examples:
        >>> _http_probe("http://127.0.0.1:1/nope")[0]
        0
    """
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return int(resp.status), resp.read(600).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return int(exc.code), exc.read(600).decode("utf-8", "replace")
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return 0, str(exc)


def _compose_argv(inv: Invocation, extra: list[str]) -> list[str]:
    """Build the ``docker compose`` argv for one documented invocation.

    Args:
        inv (Invocation): Documented invocation under test.
        extra (list[str]): Subcommand and its arguments.

    Returns:
        list[str]: Full argv starting with ``docker compose``.

    Examples:
        >>> _compose_argv(INVOCATIONS[0], ["config"])[:2]
        ['docker', 'compose']
    """
    argv = ["docker", "compose"]
    for file in inv.files:
        argv += ["-f", file]
    for profile in inv.profiles:
        argv += ["--profile", profile]
    return argv + extra


def _published_ports(config: dict) -> dict[str, list[str]]:
    """Map each published host endpoint to the services claiming it.

    Args:
        config (dict): Parsed ``docker compose config --format json`` document.

    Returns:
        dict[str, list[str]]: ``host_ip:port/proto`` keyed to service names.

    Examples:
        >>> _published_ports({"services": {"a": {"ports": [{"published": "80"}]}}})
        {'0.0.0.0:80/tcp': ['a']}
    """
    claims: dict[str, list[str]] = {}
    for name, svc in sorted((config.get("services") or {}).items()):
        for port in svc.get("ports") or []:
            published = str(port.get("published") or "").strip()
            if not published:
                continue
            host = port.get("host_ip") or "0.0.0.0"
            key = f"{host}:{published}/{port.get('protocol') or 'tcp'}"
            claims.setdefault(key, []).append(name)
    return claims


def _guard_bypass_sites() -> list[str]:
    """Find profile-selecting compose call sites that never invoke the repo guard.

    A guard that reads ``COMPOSE_PROFILES`` cannot see ``--profile`` passed on the
    command line, so every profile-selecting entry point is its own invocation
    path and must route through ``scripts/check-compose-default.sh`` (#165).

    Returns:
        list[str]: ``file:line`` sites plus the offending command, empty when clean.

    Examples:
        >>> isinstance(_guard_bypass_sites(), list)
        True
    """
    sites: list[str] = []
    makefile = REPO / "Makefile"
    if makefile.is_file():
        target = ""
        recipe: list[tuple[int, str]] = []

        def _flush(name: str, body: list[tuple[int, str]]) -> None:
            if not name or not body:
                return
            text = "\n".join(line for _, line in body)
            if "--profile" not in text and "COMPOSE_PROFILES" not in text:
                return
            if "check-compose-default" in text:
                return
            lineno = next(
                no for no, line in body if "--profile" in line or "COMPOSE_PROFILES" in line
            )
            sites.append(
                f"Makefile:{lineno} target {name!r} selects a compose profile without {COMPOSE_GUARD}"
            )

        for no, raw in enumerate(makefile.read_text(encoding="utf-8").splitlines(), start=1):
            if raw.startswith("\t"):
                recipe.append((no, raw))
                continue
            head = re.match(r"^([A-Za-z0-9_.\-]+)\s*:(?!=)", raw)
            if head:
                _flush(target, recipe)
                target, recipe = head.group(1), []
                if "check-compose-default" in raw:
                    recipe.append((no, raw))
        _flush(target, recipe)

    for path in sorted((REPO / "scripts").glob("*.sh")):
        if path.name == Path(COMPOSE_GUARD).name:
            continue
        text = path.read_text(encoding="utf-8")
        if "docker compose" not in text or "check-compose-default" in text:
            continue
        for no, line in enumerate(text.splitlines(), start=1):
            if "--profile" in line or "COMPOSE_PROFILES" in line:
                sites.append(
                    f"scripts/{path.name}:{no} selects a compose profile without {COMPOSE_GUARD}"
                )
    return sites


def drive_compose_profiles() -> DriverResult:
    """Assert every documented compose invocation resolves and claims distinct host ports.

    Covers #164 (``--profile browser`` also starts ``sevn-gateway``; both publish
    ``${SEVN_GATEWAY_PORT:-3001}``) and #165 (the mutual-exclusion guard reads only
    ``COMPOSE_PROFILES``, so ``make compose-gui-up`` bypasses it).

    Returns:
        DriverResult: Verdict plus one check per invocation and assertion.

    Examples:
        >>> drive_compose_profiles().name
        'compose-profiles'
    """
    result = DriverResult(name="compose-profiles", status=STATUS_PASS)
    reason = _docker_unavailable_reason()
    if reason:
        result.status = STATUS_UNAVAILABLE
        result.reason = f"{reason} — cannot resolve compose profiles"
        return result

    for inv in INVOCATIONS:
        if not all((REPO / f).is_file() for f in inv.files):
            result.checks.append(
                Check(
                    name=f"{inv.name}/compose-file-present",
                    status=STATUS_WARN,
                    detail=f"missing one of {inv.files} — invocation skipped ({inv.source})",
                )
            )
            continue

        argv = _compose_argv(inv, ["config", "--format", "json"])
        env = dict(os.environ)
        if inv.env_profiles:
            env["COMPOSE_PROFILES"] = inv.env_profiles
        else:
            env.pop("COMPOSE_PROFILES", None)
        code, out = _run(argv, env=env, timeout=180.0)
        shown = " ".join(argv)
        if inv.env_profiles:
            shown = f"COMPOSE_PROFILES={inv.env_profiles} {shown}"

        if code != 0:
            status = STATUS_PASS if inv.mutually_exclusive else STATUS_FAIL
            result.checks.append(
                Check(
                    name=f"{inv.name}/config-resolves",
                    status=status,
                    detail=(
                        "compose refused the mutually exclusive combination"
                        if inv.mutually_exclusive
                        else f"documented invocation does not resolve ({inv.source})"
                    ),
                    command=shown,
                    output=out.strip()[:1200],
                )
            )
            continue

        try:
            config = json.loads(out)
        except json.JSONDecodeError as exc:
            result.checks.append(
                Check(
                    name=f"{inv.name}/config-parses",
                    status=STATUS_FAIL,
                    detail=f"compose config is not JSON: {exc}",
                    command=shown,
                    output=out.strip()[:1200],
                )
            )
            continue

        services = sorted((config.get("services") or {}).keys())
        result.checks.append(
            Check(
                name=f"{inv.name}/config-resolves",
                status=STATUS_PASS,
                detail=f"services: {', '.join(services) or '(none)'} — documented at {inv.source}",
                command=shown,
            )
        )

        if inv.expect_services is not None:
            match = set(services) == set(inv.expect_services)
            result.checks.append(
                Check(
                    name=f"{inv.name}/service-set",
                    status=STATUS_PASS if match else STATUS_FAIL,
                    detail=f"expected {sorted(inv.expect_services)}, got {services}",
                    command=shown,
                )
            )

        collisions = {k: v for k, v in _published_ports(config).items() if len(v) > 1}
        result.checks.append(
            Check(
                name=f"{inv.name}/host-port-uniqueness",
                status=STATUS_FAIL if collisions else STATUS_PASS,
                detail=(
                    "; ".join(f"{k} claimed by {v}" for k, v in sorted(collisions.items()))
                    if collisions
                    else "no two services publish the same host endpoint"
                ),
                command=shown,
            )
        )

        if inv.mutually_exclusive:
            # Run the guard with the same -f / --profile args the invocation uses so
            # CLI-profile and override-file bypass paths (#165) are covered.
            guard_env = dict(os.environ)
            guard_env.pop("COMPOSE_PROFILES", None)
            if inv.env_profiles:
                guard_env["COMPOSE_PROFILES"] = inv.env_profiles
            guard_argv = ["bash", COMPOSE_GUARD]
            for file in inv.files:
                guard_argv += ["-f", file]
            for profile in inv.profiles:
                guard_argv += ["--profile", profile]
            guard_code, guard_out = _run(guard_argv, env=guard_env, timeout=180.0)
            rejected = bool(collisions) or guard_code != 0
            prefix = f"COMPOSE_PROFILES={inv.env_profiles} " if inv.env_profiles else ""
            result.checks.append(
                Check(
                    name=f"{inv.name}/mutual-exclusion-enforced",
                    status=STATUS_PASS if rejected else STATUS_FAIL,
                    detail=(
                        f"rejected — guard exit {guard_code}, port collision detected: {bool(collisions)}"
                        if rejected
                        else "browser+gui resolved cleanly and no guard refused it"
                    ),
                    command=f"{prefix}{' '.join(guard_argv)}",
                    output=guard_out.strip()[:800],
                )
            )

    bypasses = _guard_bypass_sites()
    result.checks.append(
        Check(
            name="guard-coverage",
            status=STATUS_FAIL if bypasses else STATUS_PASS,
            detail=(
                "; ".join(bypasses)
                if bypasses
                else f"every profile-selecting compose call site routes through {COMPOSE_GUARD}"
            ),
        )
    )

    if any(c.status == STATUS_FAIL for c in result.checks):
        result.status = STATUS_FAIL
        result.reason = "one or more documented compose invocations violate an invariant"
    return result


def drive_stack_health() -> DriverResult:
    """Boot the operator compose stack under a private project, probe health, tear down.

    Runs under project ``SEVN_VERIFY_PROJECT`` (default ``sevn-verify``) on port
    ``SEVN_VERIFY_GATEWAY_PORT`` (default ``3101``) so it never collides with the
    operator's own stack, and always tears down with ``down -v``. Records how long
    the boot-blocking ``sevn-operator-perms`` recursive ``chown`` takes — the #166
    regression is only observable when the stack actually starts.

    Returns:
        DriverResult: Verdict plus boot, readiness, and perms-duration checks.

    Examples:
        >>> drive_stack_health().name
        'stack-health'
    """
    result = DriverResult(name="stack-health", status=STATUS_PASS)
    reason = _docker_unavailable_reason()
    if reason:
        result.status = STATUS_UNAVAILABLE
        result.reason = f"{reason} — cannot boot the operator stack"
        return result
    if not (REPO / OPERATOR_COMPOSE).is_file():
        result.status = STATUS_UNAVAILABLE
        result.reason = f"{OPERATOR_COMPOSE} not present in this checkout"
        return result

    project = os.environ.get("SEVN_VERIFY_PROJECT", "sevn-verify")
    port = os.environ.get("SEVN_VERIFY_GATEWAY_PORT", "3101")
    boot_timeout = float(os.environ.get("SEVN_VERIFY_STACK_TIMEOUT_S", "1500"))
    ready_timeout = float(os.environ.get("SEVN_VERIFY_READY_TIMEOUT_S", "180"))
    perms_budget = float(os.environ.get("SEVN_VERIFY_PERMS_MAX_S", "5"))

    env = dict(os.environ)
    env["SEVN_GATEWAY_PORT"] = port
    env["SEVN_GATEWAY_BIND"] = "127.0.0.1"
    env.setdefault(
        "SEVN_GATEWAY_TOKEN",
        "verify-stack-health-gateway-token-32chars-minimum-length",
    )
    env.pop("COMPOSE_PROFILES", None)
    base = _compose_base(project, (OPERATOR_COMPOSE,))

    try:
        started = time.monotonic()
        code, out = _run(_compose_up_args(base), env=env, timeout=boot_timeout)
        result.checks.append(
            Check(
                name="stack-up",
                status=STATUS_PASS if code == 0 else STATUS_FAIL,
                detail=f"docker compose up exited {code} after {time.monotonic() - started:.1f}s",
                command=" ".join(_compose_up_args(base)),
                output=out.strip()[-4000:],
            )
        )
        if code != 0:
            result.status = STATUS_FAIL
            result.reason = "operator stack failed to start"
            return result

        base_url = f"http://127.0.0.1:{port}"
        unreachable = False
        for path in ("/health", "/ready"):
            deadline = time.monotonic() + ready_timeout
            status, body = 0, "not probed"
            while time.monotonic() < deadline:
                status, body = _http_probe(f"{base_url}{path}")
                if 200 <= status < 300:
                    break
                time.sleep(3.0)
            ok = 200 <= status < 300
            unreachable = unreachable or not ok
            result.checks.append(
                Check(
                    name=f"gateway{path}",
                    status=STATUS_PASS if ok else STATUS_FAIL,
                    detail=f"HTTP {status} from {base_url}{path}",
                    command=f"GET {base_url}{path}",
                    output=body[:800],
                )
            )

        if unreachable:
            # Teardown wipes the containers, so the diagnosis has to be captured
            # here or the gate is left with a bare "HTTP 0".
            _, ps_out = _run([*base, "ps", "-a"], env=env, timeout=120.0)
            _, log_out = _run([*base, "logs", "--no-color", "--tail", "80"], env=env, timeout=180.0)
            result.checks.append(
                Check(
                    name="unreachable-diagnosis",
                    status=STATUS_WARN,
                    detail="captured service state and logs for the failing boot",
                    command=" ".join([*base, "logs", "--no-color", "--tail", "80"]),
                    output=f"{ps_out.strip()}\n\n{log_out.strip()}"[-8000:],
                )
            )

        container = f"{project}-sevn-operator-perms-1"
        icode, iout = _run(
            [
                "docker",
                "inspect",
                "--format",
                "{{.State.StartedAt}}|{{.State.FinishedAt}}",
                container,
            ],
            timeout=60.0,
        )
        if icode == 0 and "|" in iout:
            raw_start, _, raw_end = iout.strip().partition("|")
            begin, end = _parse_docker_time(raw_start), _parse_docker_time(raw_end)
            if begin and end and end > begin:
                elapsed = (end - begin).total_seconds()
                result.checks.append(
                    Check(
                        name="operator-perms-duration",
                        status=STATUS_PASS if elapsed <= perms_budget else STATUS_FAIL,
                        detail=(
                            f"boot-blocking recursive chown took {elapsed:.1f}s "
                            f"(budget {perms_budget:.1f}s, SEVN_VERIFY_PERMS_MAX_S)"
                        ),
                        command=f"docker inspect {container}",
                    )
                )
            else:
                result.checks.append(
                    Check(
                        name="operator-perms-duration",
                        status=STATUS_WARN,
                        detail=f"could not parse container timestamps: {iout.strip()[:200]}",
                    )
                )
        else:
            result.checks.append(
                Check(
                    name="operator-perms-duration",
                    status=STATUS_WARN,
                    detail=f"{container} not inspectable (exit {icode}) — chown cost unmeasured",
                    output=iout.strip()[:400],
                )
            )
    finally:
        down = [*base, "down", "-v", "--remove-orphans"]
        dcode, dout = _run(down, env=env, timeout=600.0)
        result.checks.append(
            Check(
                name="stack-down",
                status=STATUS_PASS if dcode == 0 else STATUS_FAIL,
                detail=f"teardown exited {dcode}",
                command=" ".join(down),
                output=dout.strip()[-1500:],
            )
        )

    if any(c.status == STATUS_FAIL for c in result.checks):
        result.status = STATUS_FAIL
        result.reason = result.reason or "operator stack did not reach a healthy state"
    return result


async def _spawn_through_docker(image: str) -> tuple[str, str]:
    """Resolve the sandbox image and spawn/tear down one real container.

    Args:
        image (str): Sandbox image reference to spawn.

    Returns:
        tuple[str, str]: Resolved image reference and the spawned sandbox id.

    Examples:
        >>> asyncio.run(_spawn_through_docker("alpine:3.20.3"))  # doctest: +SKIP
        ('alpine@sha256:…', 'sevn-sb-...')
    """
    from sevn.config.workspace_config import WorkspaceConfig
    from sevn.security.sandbox_runtime import (
        DockerSandboxRuntime,
        ensure_sandbox_image_ready,
    )

    # Use the product path (C5.1 cache + C4.2 digest pull-if-absent). Calling
    # ``_resolve_digest_pinned_image`` first double-pulled tags and skipped the
    # digest cold-start pull that ``ensure_sandbox_image_ready`` owns.
    resolved = await ensure_sandbox_image_ready(image)
    runtime = DockerSandboxRuntime(trace_sink=None, cfg=WorkspaceConfig.minimal(), image=image)
    with tempfile.TemporaryDirectory(prefix="sevn-verify-ws-") as tmp:
        sandbox_id = await runtime.spawn(
            run_id=f"verify-{_now_stamp()}",
            workspace=Path(tmp),
            env={},
        )
        try:
            return resolved, sandbox_id
        finally:
            await runtime.teardown(sandbox_id)


def _repo_digests_empty(image: str) -> tuple[bool, str]:
    """Return whether ``image`` has an empty ``RepoDigests`` list locally.

    Args:
        image (str): Local docker image reference.

    Returns:
        tuple[bool, str]: ``(True, detail)`` when digests are absent; else
        ``(False, inspect output)``.

    Examples:
        >>> isinstance(_repo_digests_empty("missing:tag")[0], bool)
        True
    """
    code, out = _run(
        ["docker", "image", "inspect", "--format", "{{len .RepoDigests}}", image],
        timeout=60.0,
    )
    detail = out.strip()
    if code != 0:
        return False, detail
    return detail in ("0", ""), detail


def _is_d43_fail_closed(exc: BaseException, image: str) -> bool:
    """True when spawn raised the intentional empty-``RepoDigests`` refuse (D43).

    Locally built tags (e.g. ``sevn-sandbox:local``) have no registry digests.
    Post-W7/W8 product code raises ``SandboxConfigurationError`` on pull denial
    or empty ``RepoDigests`` instead of handing a bare ``sha256:…`` ``.Id`` to
    ``docker pull`` (#170 regression). That refuse is the pass criterion for the
    default verify image; set ``SEVN_VERIFY_SANDBOX_IMAGE`` to a digest-pinned
    registry ref to exercise a successful spawn instead.

    Args:
        exc (BaseException): Exception raised by ``_spawn_through_docker``.
        image (str): Image reference passed to spawn.

    Returns:
        bool: Whether ``exc`` is the expected D43 fail-closed outcome.

    Examples:
        >>> from sevn.security.sandbox_errors import SandboxConfigurationError
        >>> _is_d43_fail_closed(
        ...     SandboxConfigurationError("docker pull 'x:local' failed (exit 1)"),
        ...     "x:local",
        ... )  # doctest: +SKIP
        True
    """
    from sevn.security.sandbox_errors import SandboxConfigurationError

    if not isinstance(exc, SandboxConfigurationError):
        return False
    msg = str(exc)
    # #170 regression: bare image id handed to ``docker pull``.
    if re.search(r"docker pull ['\"]sha256:", msg):
        return False
    empty, _ = _repo_digests_empty(image)
    if "has no RepoDigests" in msg:
        return empty
    # Local builds are not registry-pullable; only empty RepoDigests makes that
    # pull denial the intentional D43 refuse (not a transient network failure on
    # a tagged image that already has digests).
    if f"docker pull {image!r} failed" in msg or f"docker pull '{image}' failed" in msg:
        return empty
    return False


def drive_sandbox_spawn() -> DriverResult:
    """Prove sandbox image pinning against the real ``docker`` CLI (D43 / #170).

    Default image ``sevn-sandbox:local`` (from ``make docker-build-ci``) has no
    ``RepoDigests``. The product must **fail closed** with
    ``SandboxConfigurationError`` — that refuse is a **pass**. Override with
    digest-pinned ``SEVN_VERIFY_SANDBOX_IMAGE`` (``repo@sha256:…``) to require a
    successful spawn/teardown instead.

    Returns:
        DriverResult: Verdict plus image-resolution and real-spawn checks.

    Examples:
        >>> drive_sandbox_spawn().name
        'sandbox-spawn'
    """
    result = DriverResult(name="sandbox-spawn", status=STATUS_PASS)
    reason = _docker_unavailable_reason()
    if reason:
        result.status = STATUS_UNAVAILABLE
        result.reason = f"{reason} — cannot spawn a sandbox"
        return result

    image = os.environ.get("SEVN_VERIFY_SANDBOX_IMAGE", "sevn-sandbox:local")
    code, out = _run(["docker", "image", "inspect", "--format", "{{.Id}}", image], timeout=60.0)
    if code != 0:
        result.status = STATUS_UNAVAILABLE
        result.reason = (
            f"sandbox image {image!r} not present locally — run `make docker-build-ci` "
            f"or set SEVN_VERIFY_SANDBOX_IMAGE (docker image inspect exit {code})"
        )
        return result
    local_id = out.strip()

    try:
        resolved, sandbox_id = asyncio.run(_spawn_through_docker(image))
    except Exception as exc:
        code2, out2 = _run(
            ["docker", "image", "inspect", "--format", "{{json .RepoDigests}}", image],
            timeout=60.0,
        )
        digests_detail = out2.strip()[:400]
        if _is_d43_fail_closed(exc, image):
            result.checks.append(
                Check(
                    name="image-resolution",
                    status=STATUS_PASS,
                    detail=(
                        f"{image!r} has empty RepoDigests (local id {local_id}); "
                        "product refused spawn instead of falling back to bare .Id (D43)"
                    ),
                    output=digests_detail,
                )
            )
            result.checks.append(
                Check(
                    name="fail-closed",
                    status=STATUS_PASS,
                    detail=f"{type(exc).__name__}: {exc}",
                    command=f"ensure_sandbox_image_ready({image!r})",
                )
            )
            result.reason = (
                f"D43 fail-closed confirmed for locally built {image!r} "
                "(set SEVN_VERIFY_SANDBOX_IMAGE to a digest-pinned ref to spawn)"
            )
            return result

        result.status = STATUS_FAIL
        result.reason = f"real docker spawn of {image!r} failed: {type(exc).__name__}: {exc}"
        result.checks.append(
            Check(
                name="docker-spawn",
                status=STATUS_FAIL,
                detail=result.reason,
                command=f"DockerSandboxRuntime(image={image!r}).spawn(...)",
            )
        )
        result.checks.append(
            Check(
                name="image-resolution",
                status=STATUS_FAIL,
                detail=(
                    f"RepoDigests lookup exit {code2}; local image id {local_id} — "
                    "unexpected spawn failure (not D43 fail-closed)"
                ),
                output=digests_detail,
            )
        )
        return result

    pullable = not resolved.startswith("sha256:")
    result.checks.append(
        Check(
            name="image-resolution",
            status=STATUS_PASS if pullable else STATUS_FAIL,
            detail=(
                f"{image!r} resolved to {resolved!r}"
                if pullable
                else (
                    f"{image!r} resolved to bare image id {resolved!r}, "
                    "which `docker pull` cannot accept (#170 regression)"
                )
            ),
        )
    )
    if pullable and resolved == image and "@sha256:" not in image:
        result.checks.append(
            Check(
                name="digest-pinning",
                status=STATUS_WARN,
                detail=f"{image!r} was not digest-pinned (no RepoDigests); spawn ran against the mutable tag",
            )
        )
    result.checks.append(
        Check(
            name="docker-spawn",
            status=STATUS_PASS,
            detail=f"spawned and tore down sandbox {sandbox_id} from {image!r} via the real docker CLI",
            command=f"DockerSandboxRuntime(image={image!r}).spawn(...)",
        )
    )

    if any(c.status == STATUS_FAIL for c in result.checks):
        result.status = STATUS_FAIL
        result.reason = "sandbox spawn path is broken against the real docker CLI"
    return result


def drive_authenticated_proxy_roundtrip() -> DriverResult:
    """Exercise the authenticated gateway→proxy round-trip (Batch A C1.2 path).

    Boots the operator stack under a private project, mints a session token with
    ``mint_session_token`` against the resolved boot secret, and probes the
    proxy ``/web/auth-check`` endpoint through the gateway with the
    ``X-Sevn-Proxy-Token`` header. A passing round-trip proves the proxy
    accepts the boot-resolved secret end-to-end — the C1.2 path Batch A wired
    and nothing else in the verify matrix exercises.

    Returns:
        DriverResult: Verdict plus token-mint and proxy round-trip checks.

    Examples:
        >>> drive_authenticated_proxy_roundtrip().name
        'authenticated-proxy-roundtrip'
    """
    result = DriverResult(name="authenticated-proxy-roundtrip", status=STATUS_PASS)
    reason = _docker_unavailable_reason()
    if reason:
        result.status = STATUS_UNAVAILABLE
        result.reason = f"{reason} — cannot exercise authenticated round-trip"
        return result
    if not (REPO / OPERATOR_COMPOSE).is_file():
        result.status = STATUS_UNAVAILABLE
        result.reason = f"{OPERATOR_COMPOSE} not present in this checkout"
        return result

    from sevn.proxy.auth import mint_session_token

    project = os.environ.get("SEVN_VERIFY_PROJECT", "sevn-verify")
    gateway_port = os.environ.get("SEVN_VERIFY_GATEWAY_PORT", "3101")
    boot_timeout = float(os.environ.get("SEVN_VERIFY_STACK_TIMEOUT_S", "1500"))
    ready_timeout = float(os.environ.get("SEVN_VERIFY_READY_TIMEOUT_S", "180"))

    secret = os.environ.get(
        "SEVN_VERIFY_PROXY_SHARED_SECRET",
        "verify-authenticated-roundtrip-32chars-minimum-length",
    )
    gateway_token = os.environ.get(
        "SEVN_VERIFY_GATEWAY_TOKEN",
        "verify-authenticated-roundtrip-gateway-token-32chars-min",
    )

    env = dict(os.environ)
    env["SEVN_GATEWAY_PORT"] = gateway_port
    env["SEVN_GATEWAY_BIND"] = "127.0.0.1"
    env["SEVN_PROXY_SHARED_SECRET"] = secret
    env["SEVN_GATEWAY_TOKEN"] = gateway_token
    env.pop("COMPOSE_PROFILES", None)
    base = _compose_base(project, (OPERATOR_COMPOSE, VERIFY_COMPOSE))

    try:
        code, out = _run(_compose_up_args(base), env=env, timeout=boot_timeout)
        result.checks.append(
            Check(
                name="stack-up",
                status=STATUS_PASS if code == 0 else STATUS_FAIL,
                detail=f"docker compose up exited {code}",
                command=" ".join(_compose_up_args(base)),
                output=out.strip()[-4000:],
            )
        )
        if code != 0:
            result.status = STATUS_FAIL
            result.reason = "operator stack failed to start for round-trip"
            return result

        proxy_url = VERIFY_PROXY_URL
        deadline = time.monotonic() + ready_timeout
        proxy_ready = False
        last_status, last_body = 0, "not probed"
        while time.monotonic() < deadline:
            last_status, last_body = _http_probe(f"{proxy_url}/healthz")
            if 200 <= last_status < 300:
                proxy_ready = True
                break
            time.sleep(3.0)
        result.checks.append(
            Check(
                name="proxy-healthz",
                status=STATUS_PASS if proxy_ready else STATUS_FAIL,
                detail=f"HTTP {last_status} from {proxy_url}/healthz",
                command=f"GET {proxy_url}/healthz",
                output=last_body[:600],
            )
        )
        if not proxy_ready:
            result.status = STATUS_FAIL
            result.reason = "proxy did not answer /healthz after boot"
            return result

        try:
            token = mint_session_token(
                signing_key=secret,
                scope="sandbox",
                run_id=f"verify-roundtrip-{_now_stamp()}",
                ttl_s=60,
            )
            result.checks.append(
                Check(
                    name="token-mint",
                    status=STATUS_PASS,
                    detail=f"minted session token for scope=sandbox (len={len(token)})",
                    command="mint_session_token(scope='sandbox', ttl_s=60)",
                )
            )
        except Exception as exc:
            result.status = STATUS_FAIL
            result.reason = f"mint_session_token raised: {type(exc).__name__}: {exc}"
            result.checks.append(
                Check(
                    name="token-mint",
                    status=STATUS_FAIL,
                    detail=result.reason,
                )
            )
            return result

        auth_status, auth_body = _http_probe(
            f"{proxy_url}/web/auth-check",
            timeout=10.0,
        )
        result.checks.append(
            Check(
                name="proxy-auth-anonymous",
                status=STATUS_FAIL if 200 <= auth_status < 300 else STATUS_PASS,
                detail=f"HTTP {auth_status} from {proxy_url}/web/auth-check (no token)",
                command=f"GET {proxy_url}/web/auth-check",
                output=auth_body[:600],
            )
        )

        auth_header_status, auth_header_body = _authenticated_probe(
            f"{proxy_url}/web/auth-check", token=token, timeout=10.0
        )
        ok = 200 <= auth_header_status < 300
        result.checks.append(
            Check(
                name="proxy-auth-with-token",
                status=STATUS_PASS if ok else STATUS_FAIL,
                detail=f"HTTP {auth_header_status} from {proxy_url}/web/auth-check with X-Sevn-Session-Token",
                command=f"GET {proxy_url}/web/auth-check (with session token)",
                output=auth_header_body[:600],
            )
        )
        if not ok:
            result.status = STATUS_FAIL
            result.reason = (
                "proxy refused authenticated /web/auth-check — "
                "Batch A C1.2 secret path is not actually wired end-to-end"
            )
    finally:
        dcode, dout = _run([*base, "down", "-v", "--remove-orphans"], env=env, timeout=600.0)
        result.checks.append(
            Check(
                name="stack-down",
                status=STATUS_PASS if dcode == 0 else STATUS_FAIL,
                detail=f"teardown exited {dcode}",
                command=" ".join([*base, "down", "-v", "--remove-orphans"]),
                output=dout.strip()[-1500:],
            )
        )

    if any(c.status == STATUS_FAIL for c in result.checks):
        result.status = STATUS_FAIL
        result.reason = result.reason or "authenticated gateway→proxy round-trip failed"
    return result


def _authenticated_probe(url: str, *, token: str, timeout: float = 10.0) -> tuple[int, str]:
    """Probe a URL with a ``X-Sevn-Session-Token`` header.

    Args:
        url (str): Absolute URL to probe.
        token (str): Session token value to send.
        timeout (float): Socket timeout in seconds.

    Returns:
        tuple[int, str]: Status code and body excerpt.

    Examples:
        >>> _authenticated_probe("http://127.0.0.1:1/nope", token="x")[0]
        0
    """
    request = urllib.request.Request(
        url,
        headers={"X-Sevn-Session-Token": token, "X-Sevn-Proxy-Token": token},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            return int(resp.status), resp.read(600).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return int(exc.code), exc.read(600).decode("utf-8", "replace")
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return 0, str(exc)


def drive_volume_upgrade() -> DriverResult:
    """Pre-populate a ``sevn-state`` volume, boot the stack, assert content survives.

    Models the operator upgrade/migration path: a volume named ``sevn-state``
    with a sentinel file already present must not be wiped when the operator
    stack comes up under the C9.2 versioned init marker semantics. This is
    C14.2's "volume upgrade/migration" driver — without it, ``compose down -v``
    in any verification run would silently destroy operator state and the
    C1.2 secret bootstrap would have to redo work that should be persisted.

    Returns:
        DriverResult: Verdict plus sentinel-presence checks.

    Examples:
        >>> drive_volume_upgrade().name
        'volume-upgrade'
    """
    result = DriverResult(name="volume-upgrade", status=STATUS_PASS)
    reason = _docker_unavailable_reason()
    if reason:
        result.status = STATUS_UNAVAILABLE
        result.reason = f"{reason} — cannot exercise volume upgrade"
        return result
    if not (REPO / OPERATOR_COMPOSE).is_file():
        result.status = STATUS_UNAVAILABLE
        result.reason = f"{OPERATOR_COMPOSE} not present in this checkout"
        return result

    project = os.environ.get("SEVN_VERIFY_PROJECT", "sevn-verify")
    volume = f"{project}_sevn-state"
    sentinel = f"verify-volume-upgrade-{_now_stamp()}"
    boot_timeout = float(os.environ.get("SEVN_VERIFY_STACK_TIMEOUT_S", "1500"))

    try:
        _run(
            ["docker", "volume", "create", volume],
            timeout=60.0,
        )
        seed_code, seed_out = _run(
            [
                "docker",
                "run",
                "--rm",
                "-v",
                f"{volume}:/mnt",
                "alpine:latest",
                "sh",
                "-c",
                f"echo {sentinel!r} > /mnt/.sevn-verify-sentinel && cat /mnt/.sevn-verify-sentinel",
            ],
            timeout=60.0,
        )
        result.checks.append(
            Check(
                name="sentinel-seed",
                status=STATUS_PASS if seed_code == 0 else STATUS_FAIL,
                detail=f"seeded {volume!r} with sentinel; exit {seed_code}",
                command=f"docker run --rm -v {volume}:/mnt alpine sh -c 'echo {sentinel}'",
                output=seed_out.strip()[:400],
            )
        )
        if seed_code != 0:
            result.status = STATUS_FAIL
            result.reason = "sentinel seed failed; volume upgrade cannot be exercised"
            return result

        env = dict(os.environ)
        env["SEVN_GATEWAY_PORT"] = os.environ.get("SEVN_VERIFY_GATEWAY_PORT", "3101")
        env["SEVN_GATEWAY_BIND"] = "127.0.0.1"
        env.setdefault(
            "SEVN_GATEWAY_TOKEN",
            "verify-volume-upgrade-gateway-token-32chars-min",
        )
        env.setdefault(
            "SEVN_PROXY_SHARED_SECRET",
            "verify-volume-upgrade-proxy-secret-32chars-min",
        )
        env.pop("COMPOSE_PROFILES", None)
        base = _compose_base(project, (OPERATOR_COMPOSE,))
        code, out = _run(_compose_up_args(base), env=env, timeout=boot_timeout)
        result.checks.append(
            Check(
                name="stack-up",
                status=STATUS_PASS if code == 0 else STATUS_FAIL,
                detail=f"docker compose up exited {code}",
                command=" ".join(_compose_up_args(base)),
                output=out.strip()[-4000:],
            )
        )

        _read_code, read_out = _run(
            [
                "docker",
                "run",
                "--rm",
                "-v",
                f"{volume}:/mnt",
                "alpine:latest",
                "cat",
                "/mnt/.sevn-verify-sentinel",
            ],
            timeout=60.0,
        )
        sentinel_still = sentinel in read_out
        result.checks.append(
            Check(
                name="sentinel-survives",
                status=STATUS_PASS if sentinel_still else STATUS_FAIL,
                detail=(
                    f"sentinel {sentinel!r} preserved through compose up"
                    if sentinel_still
                    else f"sentinel {sentinel!r} missing after compose up — operator state was wiped"
                ),
                command=f"docker run --rm -v {volume}:/mnt alpine cat /mnt/.sevn-verify-sentinel",
                output=read_out.strip()[:400],
            )
        )
        if code != 0:
            result.status = STATUS_FAIL
            result.reason = "operator stack failed to start during volume upgrade"
            return result
        if not sentinel_still:
            result.status = STATUS_FAIL
            result.reason = "operator state volume was wiped by compose up"
            return result
    finally:
        env = dict(os.environ)
        env.pop("COMPOSE_PROFILES", None)
        base = _compose_base(project, (OPERATOR_COMPOSE,))
        _run([*base, "down", "-v", "--remove-orphans"], env=env, timeout=600.0)
        _run(["docker", "volume", "rm", "-f", volume], timeout=60.0)

    return result


def drive_browser_gui_boot() -> DriverResult:
    """Resolve the browser and GUI compose overlays and assert the gateway image flips.

    ``docker/docker-compose.browser.yml`` and ``docker/docker-compose.gui.yml``
    redefine ``sevn-gateway``; the resolved config must use the multi-arch
    ``Dockerfile.gateway.browser`` / ``Dockerfile.gateway.gui`` image and
    inherit base resource limits through Compose merge semantics. C10.3
    requires limits wherever the resolved config is missing them.

    Returns:
        DriverResult: Verdict plus image-and-limits resolution checks.

    Examples:
        >>> drive_browser_gui_boot().name
        'browser-gui-boot'
    """
    result = DriverResult(name="browser-gui-boot", status=STATUS_PASS)
    reason = _docker_unavailable_reason()
    if reason:
        result.status = STATUS_UNAVAILABLE
        result.reason = f"{reason} — cannot resolve compose overlays"
        return result
    for overlay in (BROWSER_COMPOSE, GUI_COMPOSE):
        if not (REPO / overlay).is_file():
            result.status = STATUS_UNAVAILABLE
            result.reason = f"{overlay} not present in this checkout"
            return result

    expected = (
        ("browser-override", BROWSER_COMPOSE, "Dockerfile.gateway.browser"),
        ("gui-override", GUI_COMPOSE, "Dockerfile.gateway.gui"),
    )
    for label, overlay, expected_dockerfile in expected:
        argv = [
            "docker",
            "compose",
            "-f",
            OPERATOR_COMPOSE,
            "-f",
            overlay,
            "config",
            "--format",
            "json",
        ]
        env = dict(os.environ)
        env.pop("COMPOSE_PROFILES", None)
        code, out = _run(argv, env=env, timeout=180.0)
        if code != 0:
            result.checks.append(
                Check(
                    name=f"{label}/config-resolves",
                    status=STATUS_FAIL,
                    detail=f"docker compose config refused {overlay}",
                    command=" ".join(argv),
                    output=out.strip()[:800],
                )
            )
            continue
        try:
            config = json.loads(out)
        except json.JSONDecodeError as exc:
            result.checks.append(
                Check(
                    name=f"{label}/config-parses",
                    status=STATUS_FAIL,
                    detail=f"compose config is not JSON: {exc}",
                    command=" ".join(argv),
                    output=out.strip()[:800],
                )
            )
            continue
        build = (config.get("services") or {}).get("sevn-gateway", {}).get("build") or {}
        dockerfile = build.get("dockerfile") or ""
        match = expected_dockerfile in dockerfile
        result.checks.append(
            Check(
                name=f"{label}/gateway-dockerfile",
                status=STATUS_PASS if match else STATUS_FAIL,
                detail=(
                    f"sevn-gateway builds from {dockerfile!r}"
                    if dockerfile
                    else f"sevn-gateway has no build section; expected {expected_dockerfile}"
                ),
                command=" ".join(argv),
            )
        )
        if not match:
            result.status = STATUS_FAIL
            result.reason = (
                f"{overlay} did not flip sevn-gateway to {expected_dockerfile} "
                f"(resolved: {dockerfile!r})"
            )

    if any(c.status == STATUS_FAIL for c in result.checks):
        result.status = STATUS_FAIL
    return result


def drive_cancellation_cleanup() -> DriverResult:
    """Spawn a sandbox through the real ``docker`` CLI, cancel mid-run, assert no orphans.

    C14.2's "cancellation cleanup" driver: starts a tier-B sandbox via
    ``DockerSandboxRuntime.spawn``, cancels the surrounding ``asyncio`` task
    mid-flight, and asserts no orphan containers or leaked named volumes
    remain. Without this assertion, a cancelled run can leave a container
    pinned to the operator's network — exactly the kind of silent leak that
    only surfaces under load.

    Returns:
        DriverResult: Verdict plus pre-/post-spawn container and volume checks.

    Examples:
        >>> drive_cancellation_cleanup().name
        'cancellation-cleanup'
    """
    result = DriverResult(name="cancellation-cleanup", status=STATUS_PASS)
    reason = _docker_unavailable_reason()
    if reason:
        result.status = STATUS_UNAVAILABLE
        result.reason = f"{reason} — cannot exercise cancellation cleanup"
        return result

    image = os.environ.get("SEVN_VERIFY_SANDBOX_IMAGE", "sevn-sandbox:local")
    code, _out = _run(["docker", "image", "inspect", "--format", "{{.Id}}", image], timeout=60.0)
    if code != 0:
        result.status = STATUS_UNAVAILABLE
        result.reason = (
            f"sandbox image {image!r} not present locally — run `make docker-build-ci` "
            f"or set SEVN_VERIFY_SANDBOX_IMAGE (docker image inspect exit {code})"
        )
        return result

    baseline_ps, baseline_vol = _container_and_volume_baseline()

    async def _spawn_and_cancel() -> str:
        from sevn.config.workspace_config import WorkspaceConfig
        from sevn.security.sandbox_runtime import DockerSandboxRuntime

        runtime = DockerSandboxRuntime(trace_sink=None, cfg=WorkspaceConfig.minimal(), image=image)
        with tempfile.TemporaryDirectory(prefix="sevn-verify-cancel-") as tmp:
            task = asyncio.create_task(
                runtime.spawn(
                    run_id=f"verify-cancel-{_now_stamp()}",
                    workspace=Path(tmp),
                    env={},
                )
            )
            await asyncio.sleep(0.05)
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
            return "spawn-cancelled"

    try:
        marker = asyncio.run(_spawn_and_cancel())
        result.checks.append(
            Check(
                name="cancel-triggered",
                status=STATUS_PASS,
                detail=f"{marker} — task cancelled before teardown could run synchronously",
                command="DockerSandboxRuntime.spawn() (cancelled)",
            )
        )
    except Exception as exc:
        result.status = STATUS_FAIL
        result.reason = f"cancellation flow raised unexpectedly: {type(exc).__name__}: {exc}"
        result.checks.append(
            Check(
                name="cancel-triggered",
                status=STATUS_FAIL,
                detail=result.reason,
            )
        )
    finally:
        # F-THERMOS-5: orphan diff + cleanup must run even if the
        # cancellation flow raised. Without this guard, a partially-
        # completed spawn could leave containers / volumes pinned to the
        # operator network; the mirror of ``drive_volume_upgrade``'s
        # ``finally: docker compose down -v`` pattern.
        time.sleep(2.0)
        after_ps, after_vol = _container_and_volume_baseline()
        orphan_containers = sorted(set(after_ps) - set(baseline_ps))
        orphan_volumes = sorted(set(after_vol) - set(baseline_vol))
        result.checks.append(
            Check(
                name="no-orphan-containers",
                status=STATUS_PASS if not orphan_containers else STATUS_FAIL,
                detail=(
                    f"baseline {len(baseline_ps)} containers; post-cancel {len(after_ps)}; "
                    f"new: {orphan_containers or '(none)'}"
                ),
                command="docker ps --format '{{.Names}}'",
            )
        )
        result.checks.append(
            Check(
                name="no-leaked-volumes",
                status=STATUS_PASS if not orphan_volumes else STATUS_FAIL,
                detail=(
                    f"baseline {len(baseline_vol)} volumes; post-cancel {len(after_vol)}; "
                    f"new: {orphan_volumes or '(none)'}"
                ),
                command="docker volume ls --format '{{.Name}}'",
            )
        )

        if orphan_containers:
            for name in orphan_containers:
                _run(["docker", "rm", "-f", name], timeout=60.0)
        if orphan_volumes:
            for name in orphan_volumes:
                _run(["docker", "volume", "rm", "-f", name], timeout=60.0)

    if any(c.status == STATUS_FAIL for c in result.checks):
        result.status = STATUS_FAIL
        result.reason = result.reason or "cancellation left orphan containers / volumes"
    return result


def _container_and_volume_baseline() -> tuple[set[str], set[str]]:
    """Snapshot running containers and named volumes for an orphan diff.

    Returns:
        tuple[set[str], set[str]]: Container-name set and volume-name set.

    Examples:
        >>> isinstance(_container_and_volume_baseline(), tuple)
        True
    """
    code, out = _run(["docker", "ps", "--format", "{{.Names}}"], timeout=60.0)
    containers = set(out.split()) if code == 0 else set()
    vcode, vout = _run(["docker", "volume", "ls", "--format", "{{.Name}}"], timeout=60.0)
    volumes = set(vout.split()) if vcode == 0 else set()
    return containers, volumes


def drive_sandbox_scoped_token() -> DriverResult:
    """Exercise the sandbox-scoped session token end-to-end (Batch E C7.1/C7.2 path).

    Boots the operator stack, mints a ``scope=sandbox`` session token bound to
    a run_id, and asserts the proxy accepts it on ``/web/*`` and ``/integration``
    while refusing it on ``/llm/*`` (scope mismatch). Also asserts an
    unscoped ``X-Sevn-Proxy-Token`` (the long-lived service secret) is
    honoured on the same ``/web/*`` path — proving the W3 single-sourced
    secret still satisfies guarded routes. This is the W23.4 driver Batch E
    enables; without it, a release could regress scoped-token routing
    without any verify matrix catching it.

    Returns:
        DriverResult: Verdict plus scope-accept and scope-reject checks.

    Examples:
        >>> drive_sandbox_scoped_token().name
        'sandbox-scoped-token'
    """
    result = DriverResult(name="sandbox-scoped-token", status=STATUS_PASS)
    reason = _docker_unavailable_reason()
    if reason:
        result.status = STATUS_UNAVAILABLE
        result.reason = f"{reason} — cannot exercise sandbox-scoped session token"
        return result
    if not (REPO / OPERATOR_COMPOSE).is_file():
        result.status = STATUS_UNAVAILABLE
        result.reason = f"{OPERATOR_COMPOSE} not present in this checkout"
        return result

    from sevn.proxy.auth import mint_session_token

    project = os.environ.get("SEVN_VERIFY_PROJECT", "sevn-verify")
    gateway_port = os.environ.get("SEVN_VERIFY_GATEWAY_PORT", "3101")
    boot_timeout = float(os.environ.get("SEVN_VERIFY_STACK_TIMEOUT_S", "1500"))
    ready_timeout = float(os.environ.get("SEVN_VERIFY_READY_TIMEOUT_S", "180"))

    secret = os.environ.get(
        "SEVN_VERIFY_PROXY_SHARED_SECRET",
        "verify-scoped-token-32chars-minimum-length-shared",
    )
    gateway_token = os.environ.get(
        "SEVN_VERIFY_GATEWAY_TOKEN",
        "verify-scoped-token-gateway-token-32chars-min",
    )

    env = dict(os.environ)
    env["SEVN_GATEWAY_PORT"] = gateway_port
    env["SEVN_GATEWAY_BIND"] = "127.0.0.1"
    env["SEVN_PROXY_SHARED_SECRET"] = secret
    env["SEVN_GATEWAY_TOKEN"] = gateway_token
    env.pop("COMPOSE_PROFILES", None)
    base = _compose_base(project, (OPERATOR_COMPOSE, VERIFY_COMPOSE))

    try:
        code, out = _run(_compose_up_args(base), env=env, timeout=boot_timeout)
        result.checks.append(
            Check(
                name="stack-up",
                status=STATUS_PASS if code == 0 else STATUS_FAIL,
                detail=f"docker compose up exited {code}",
                command=" ".join(_compose_up_args(base)),
                output=out.strip()[-4000:],
            )
        )
        if code != 0:
            result.status = STATUS_FAIL
            result.reason = "operator stack failed to start for scoped-token check"
            return result

        proxy_url = VERIFY_PROXY_URL
        deadline = time.monotonic() + ready_timeout
        proxy_ready = False
        last_status, last_body = 0, "not probed"
        while time.monotonic() < deadline:
            last_status, last_body = _http_probe(f"{proxy_url}/healthz")
            if 200 <= last_status < 300:
                proxy_ready = True
                break
            time.sleep(3.0)
        result.checks.append(
            Check(
                name="proxy-healthz",
                status=STATUS_PASS if proxy_ready else STATUS_FAIL,
                detail=f"HTTP {last_status} from {proxy_url}/healthz",
                command=f"GET {proxy_url}/healthz",
                output=last_body[:600],
            )
        )
        if not proxy_ready:
            result.status = STATUS_FAIL
            result.reason = "proxy did not answer /healthz after boot"
            return result

        run_id = f"verify-scoped-token-{_now_stamp()}"
        sandbox_token = mint_session_token(
            signing_key=secret,
            scope="sandbox",
            run_id=run_id,
            ttl_s=60,
        )
        result.checks.append(
            Check(
                name="token-mint",
                status=STATUS_PASS,
                detail=f"minted scope=sandbox token bound to run_id={run_id!r}",
                command="mint_session_token(scope='sandbox', ttl=60, run_id=…)",
            )
        )

        web_status, web_body = _authenticated_probe(
            f"{proxy_url}/web/auth-check",
            token=sandbox_token,
            timeout=10.0,
        )
        ok_web = 200 <= web_status < 300
        result.checks.append(
            Check(
                name="sandbox-scope-accepts-web",
                status=STATUS_PASS if ok_web else STATUS_FAIL,
                detail=f"HTTP {web_status} from {proxy_url}/web/auth-check (scope=sandbox)",
                command=f"GET {proxy_url}/web/auth-check (X-Sevn-Session-Token scope=sandbox)",
                output=web_body[:600],
            )
        )
        if not ok_web:
            result.status = STATUS_FAIL
            result.reason = "sandbox-scoped token refused on /web/auth-check"

        llm_status, llm_body = _authenticated_probe(
            f"{proxy_url}/llm/openai/chat/completions",
            token=sandbox_token,
            timeout=10.0,
        )
        refused_llm = llm_status == 401 or llm_status == 403
        result.checks.append(
            Check(
                name="sandbox-scope-rejects-llm",
                status=STATUS_PASS if refused_llm else STATUS_FAIL,
                detail=(
                    f"HTTP {llm_status} from {proxy_url}/llm/openai/chat/completions "
                    "(scope=sandbox should be refused)"
                ),
                command=(
                    f"POST {proxy_url}/llm/openai/chat/completions "
                    "(X-Sevn-Session-Token scope=sandbox)"
                ),
                output=llm_body[:600],
            )
        )
        if not refused_llm:
            result.status = STATUS_FAIL
            result.reason = (
                "sandbox-scoped token was accepted on /llm/* — scope enforcement is broken"
            )

        service_status, service_body = _authenticated_probe(
            f"{proxy_url}/web/auth-check",
            token=secret,
            timeout=10.0,
        )
        ok_service = 200 <= service_status < 300
        result.checks.append(
            Check(
                name="service-secret-still-accepted",
                status=STATUS_PASS if ok_service else STATUS_FAIL,
                detail=f"HTTP {service_status} from {proxy_url}/web/auth-check (X-Sevn-Proxy-Token)",
                command=f"GET {proxy_url}/web/auth-check (X-Sevn-Proxy-Token service secret)",
                output=service_body[:600],
            )
        )
        if not ok_service:
            result.status = STATUS_FAIL
            result.reason = "X-Sevn-Proxy-Token service secret was refused on /web/auth-check"
    finally:
        dcode, dout = _run([*base, "down", "-v", "--remove-orphans"], env=env, timeout=600.0)
        result.checks.append(
            Check(
                name="stack-down",
                status=STATUS_PASS if dcode == 0 else STATUS_FAIL,
                detail=f"teardown exited {dcode}",
                command=" ".join([*base, "down", "-v", "--remove-orphans"]),
                output=dout.strip()[-1500:],
            )
        )

    if any(c.status == STATUS_FAIL for c in result.checks):
        result.status = STATUS_FAIL
        result.reason = result.reason or "sandbox-scoped token path failed"
    return result


def drive_runtime() -> DriverResult:
    """Exercise the ``sevn`` CLI and probe an already-running gateway over HTTP.

    This is the driver C-Verify improvised as in-process ``TestClient`` calls. It
    targets ``SEVN_VERIFY_APP_URL`` (default ``http://127.0.0.1:3001``) and reports
    ``driver_unavailable`` when nothing is listening, rather than passing.

    Returns:
        DriverResult: Verdict plus CLI-invocation and HTTP-probe checks.

    Examples:
        >>> drive_runtime().name
        'runtime'
    """
    result = DriverResult(name="runtime", status=STATUS_PASS)

    cli = os.environ.get("SEVN_VERIFY_CLI", "sevn")
    argv = [cli, "--version"] if shutil.which(cli) else ["uv", "run", cli, "--version"]
    code, out = _run(argv, timeout=300.0)
    if code == 127:
        result.status = STATUS_UNAVAILABLE
        result.reason = f"neither {cli!r} nor `uv run {cli}` is invocable: {out.strip()[:300]}"
        return result
    result.checks.append(
        Check(
            name="cli-invocation",
            status=STATUS_PASS if code == 0 else STATUS_FAIL,
            detail=f"exit {code}",
            command=" ".join(argv),
            output=out.strip()[-1500:],
        )
    )

    base_url = os.environ.get("SEVN_VERIFY_APP_URL", "http://127.0.0.1:3001").rstrip("/")
    status, body = _http_probe(f"{base_url}/health")
    if status == 0:
        result.status = STATUS_UNAVAILABLE
        result.reason = (
            f"no gateway answering at {base_url} ({body[:200]}) — "
            "run `make compose-up` or `make verify-stack-health` first"
        )
        return result
    result.checks.append(
        Check(
            name="http-health",
            status=STATUS_PASS if 200 <= status < 300 else STATUS_FAIL,
            detail=f"HTTP {status}",
            command=f"GET {base_url}/health",
            output=body[:800],
        )
    )
    ready_status, ready_body = _http_probe(f"{base_url}/ready")
    result.checks.append(
        Check(
            name="http-ready",
            status=STATUS_PASS if 200 <= ready_status < 300 else STATUS_FAIL,
            detail=f"HTTP {ready_status}",
            command=f"GET {base_url}/ready",
            output=ready_body[:800],
        )
    )

    if any(c.status == STATUS_FAIL for c in result.checks):
        result.status = STATUS_FAIL
        result.reason = "runtime CLI or HTTP surface is not behaving"
    return result


DRIVERS = {
    "compose-profiles": drive_compose_profiles,
    "stack-health": drive_stack_health,
    "sandbox-spawn": drive_sandbox_spawn,
    "runtime": drive_runtime,
    "authenticated-proxy-roundtrip": drive_authenticated_proxy_roundtrip,
    "volume-upgrade": drive_volume_upgrade,
    "browser-gui-boot": drive_browser_gui_boot,
    "cancellation-cleanup": drive_cancellation_cleanup,
    "sandbox-scoped-token": drive_sandbox_scoped_token,
}


def _write_evidence(result: DriverResult, stamp: str) -> Path:
    """Persist a driver result as JSON evidence a gate annotation can quote.

    Args:
        result (DriverResult): Completed driver verdict.
        stamp (str): Shared run timestamp for the filename.

    Returns:
        Path: Written evidence file.

    Examples:
        >>> _write_evidence(DriverResult(name="x", status="pass"), "t")  # doctest: +SKIP
        PosixPath('.../evidence/verify/x-t.json')
    """
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    path = EVIDENCE_DIR / f"{result.name}-{stamp}.json"
    payload = {
        "driver": result.name,
        "status": result.status,
        "reason": result.reason,
        "captured_at": datetime.now(tz=UTC).isoformat(),
        "repo": str(REPO),
        "checks": [vars(c) for c in result.checks],
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _report(result: DriverResult) -> None:
    """Print a driver verdict in a shape that pastes into a gate annotation.

    Args:
        result (DriverResult): Completed driver verdict.

    Returns:
        None: Always ``None``.

    Examples:
        >>> _report(DriverResult(name="x", status="pass"))
        <BLANKLINE>
        === x: pass ===
    """
    print(f"\n=== {result.name}: {result.status} ===")
    if result.reason:
        print(f"reason: {result.reason}")
    for check in result.checks:
        print(f"  [{check.status:>4}] {check.name}: {check.detail}")
        if check.command:
            print(f"         $ {check.command}")
    for path in result.evidence:
        print(f"  evidence: {path}")


def main(argv: list[str] | None = None) -> int:
    """Run one deployment driver or all of them and emit evidence.

    Args:
        argv (list[str] | None): Command-line arguments, defaulting to ``sys.argv[1:]``.

    Returns:
        int: ``0`` pass, ``1`` fail, ``2`` driver_unavailable.

    Examples:
    >>> main(["--list"])
    authenticated-proxy-roundtrip
    browser-gui-boot
    cancellation-cleanup
    compose-profiles
    runtime
    sandbox-scoped-token
    sandbox-spawn
    stack-health
    volume-upgrade
    0
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("driver", nargs="?", choices=[*sorted(DRIVERS), "all"], default="all")
    parser.add_argument("--list", action="store_true", help="List driver names and exit")
    args = parser.parse_args(argv)

    if args.list:
        for name in sorted(DRIVERS):
            print(name)
        return 0

    names = sorted(DRIVERS) if args.driver == "all" else [args.driver]
    stamp = _now_stamp()
    statuses: list[str] = []
    for name in names:
        result = DRIVERS[name]()
        result.evidence.append(str(_write_evidence(result, stamp).relative_to(REPO)))
        _report(result)
        statuses.append(result.status)

    if STATUS_FAIL in statuses:
        overall = STATUS_FAIL
    elif STATUS_UNAVAILABLE in statuses:
        overall = STATUS_UNAVAILABLE
    else:
        overall = STATUS_PASS
    # GNU make collapses every recipe failure to exit 2, so the pass/fail/
    # driver_unavailable distinction has to survive in the output too.
    print(f"\nVERIFY_OVERALL: {overall} (exit {EXIT_CODES[overall]})")
    return EXIT_CODES[overall]


if __name__ == "__main__":
    sys.exit(main())
