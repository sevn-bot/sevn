"""Post-audit Batch A W1 RED - compose invocation contracts (#164-#166, #177).

Contracts (``about-sevn.bot/specs/25-cicd-full.md``, ``prd/06-setup-and-operations.md``):
exactly one gateway per documented ``-f`` invocation; no duplicate ``SEVN_GATEWAY_PORT``
publishers in a resolvable file set; Makefile compose targets resolve to a single-gateway
file set; operator service hardening (W3 / D24); conditional ``sevn-operator-perms`` chown
(W3 / D25). Parses compose YAML and the Makefile directly — no Docker daemon.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DOCKER_DIR = _REPO_ROOT / "docker"
_BASE_COMPOSE = _DOCKER_DIR / "docker-compose.yml"
_BROWSER_OVERRIDE = _DOCKER_DIR / "docker-compose.browser.yml"
_GUI_OVERRIDE = _DOCKER_DIR / "docker-compose.gui.yml"
_MAKEFILE = _REPO_ROOT / "Makefile"

_GATEWAY_SERVICE_NAMES = frozenset(
    {"sevn-gateway", "sevn-gateway-browser", "sevn-gateway-gui"},
)
_GATEWAY_PORT_MARKER = "${SEVN_GATEWAY_PORT"
_NEGATED_PROFILE_LINE_RE = re.compile(r'^\s*-\s*"![^"]+"\s*$', re.MULTILINE)
_NEGATED_PROFILE_INLINE_RE = re.compile(r'"!')
_COMPOSE_TARGET_NAMES = ("compose-up", "compose-gui-up", "compose-browser-up")
_MAKEFILE_TARGET_RE = re.compile(
    r"^(?P<name>compose(?:-up|-gui-up|-browser-up)):"
    r"(?:[^\n]*\n)(?P<body>(?:\t[^\n]*\n)+)",
    re.MULTILINE,
)
_COMPOSE_CMD_RE = re.compile(r"docker compose (.+)$")


def _load_services(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    services = data.get("services")
    if not isinstance(services, dict):
        return {}
    return services


def _merge_services(*paths: Path) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for path in paths:
        merged.update(_load_services(path))
    return merged


def _active_services(
    services: dict[str, Any],
    *,
    profiles: frozenset[str] | None = None,
) -> dict[str, Any]:
    active: dict[str, Any] = {}
    for name, cfg in services.items():
        if not isinstance(cfg, dict):
            continue
        svc_profiles = cfg.get("profiles")
        if svc_profiles is None:
            active[name] = cfg
            continue
        if profiles and set(svc_profiles) & profiles:
            active[name] = cfg
    return active


def _is_gateway_service(name: str, cfg: dict[str, Any]) -> bool:
    if name in _GATEWAY_SERVICE_NAMES or name.startswith("sevn-gateway"):
        return True
    for port in cfg.get("ports") or []:
        port_str = port if isinstance(port, str) else str(port)
        if _GATEWAY_PORT_MARKER in port_str or ":3001" in port_str:
            return True
    return False


def _publishes_gateway_port(cfg: dict[str, Any]) -> bool:
    for port in cfg.get("ports") or []:
        port_str = port if isinstance(port, str) else str(port)
        if _GATEWAY_PORT_MARKER in port_str:
            return True
    return False


def _gateway_names(services: dict[str, Any]) -> list[str]:
    return sorted(name for name, cfg in services.items() if _is_gateway_service(name, cfg))


def _gateway_port_publishers(services: dict[str, Any]) -> list[str]:
    return sorted(name for name, cfg in services.items() if _publishes_gateway_port(cfg))


def _operator_perms_command_text() -> str:
    cfg = _load_services(_BASE_COMPOSE).get("sevn-operator-perms", {})
    command = cfg.get("command")
    if isinstance(command, list):
        return "\n".join(str(part) for part in command)
    return str(command or "")


def _makefile_text() -> str:
    return _MAKEFILE.read_text(encoding="utf-8")


def _resolve_compose_file(token: str) -> Path:
    cleaned = token.strip().replace("$(COMPOSE_FILE)", "docker/docker-compose.yml")
    cleaned = cleaned.replace("${COMPOSE_FILE}", "docker/docker-compose.yml")
    if cleaned.startswith("docker/"):
        return _REPO_ROOT / cleaned
    return _REPO_ROOT / "docker" / cleaned


def _parse_makefile_compose_invocation(target: str) -> tuple[tuple[Path, ...], frozenset[str]]:
    makefile = _makefile_text()
    targets = {m.group("name"): m.group("body") for m in _MAKEFILE_TARGET_RE.finditer(makefile)}
    assert target in targets, f"Makefile target {target!r} is missing"
    body = targets[target]
    compose_line = ""
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("docker compose"):
            compose_line = stripped
            break
    assert compose_line, f"{target} has no docker compose recipe"
    cmd_match = _COMPOSE_CMD_RE.search(compose_line)
    assert cmd_match is not None, f"could not parse compose command in {target}"
    tail = cmd_match.group(1)
    compose_files: list[Path] = []
    profiles: set[str] = set()
    tokens = tail.split()
    idx = 0
    while idx < len(tokens):
        token = tokens[idx]
        if token == "-f" and idx + 1 < len(tokens):
            compose_files.append(_resolve_compose_file(tokens[idx + 1]))
            idx += 2
            continue
        if token == "--profile" and idx + 1 < len(tokens):
            profiles.add(tokens[idx + 1])
            idx += 2
            continue
        idx += 1
    if not compose_files:
        compose_files.append(_resolve_compose_file("docker/docker-compose.yml"))
    return tuple(compose_files), frozenset(profiles)


_DOCUMENTED_INVOCATIONS = (
    pytest.param(
        "base",
        (_BASE_COMPOSE,),
        frozenset(),
        id="base",
    ),
    pytest.param(
        "browser",
        (_BASE_COMPOSE, _BROWSER_OVERRIDE),
        frozenset(),
        id="browser-override",
    ),
    pytest.param(
        "gui",
        (_BASE_COMPOSE, _GUI_OVERRIDE),
        frozenset(),
        id="gui-override",
    ),
)


@pytest.mark.parametrize(
    ("label", "compose_paths", "profiles"),
    _DOCUMENTED_INVOCATIONS,
)
def test_documented_invocation_files_exist_and_yield_one_gateway(
    label: str,
    compose_paths: tuple[Path, ...],
    profiles: frozenset[str],
) -> None:
    """W1.1: each documented ``-f`` set resolves to exactly one gateway service."""
    missing = [path for path in compose_paths if not path.is_file()]
    assert not missing, f"{label}: missing compose files: {missing}"
    merged = _merge_services(*compose_paths)
    active = _active_services(merged, profiles=profiles)
    gateways = _gateway_names(active)
    assert gateways == ["sevn-gateway"], (
        f"{label}: expected exactly one gateway service (sevn-gateway), got {gateways}"
    )


def test_base_compose_defines_only_one_gateway_service() -> None:
    """W1.1: variant gateways must live in override files, not the base compose file."""
    gateways = _gateway_names(_load_services(_BASE_COMPOSE))
    assert gateways == ["sevn-gateway"], (
        "base docker-compose.yml must define only sevn-gateway; "
        f"browser/gui variants belong in override files, got {gateways}"
    )


@pytest.mark.parametrize(
    ("label", "compose_paths", "profiles"),
    _DOCUMENTED_INVOCATIONS,
)
def test_resolvable_file_set_has_unique_gateway_port_publisher(
    label: str,
    compose_paths: tuple[Path, ...],
    profiles: frozenset[str],
) -> None:
    """W1.2: no two active services publish ``${SEVN_GATEWAY_PORT}`` in one file set."""
    missing = [path for path in compose_paths if not path.is_file()]
    assert not missing, f"{label}: missing compose files: {missing}"
    merged = _merge_services(*compose_paths)
    active = _active_services(merged, profiles=profiles)
    publishers = _gateway_port_publishers(active)
    assert len(publishers) <= 1, f"{label}: multiple gateway port publishers {publishers}"


@pytest.mark.parametrize(
    "path",
    [
        pytest.param(_BASE_COMPOSE, id="base"),
        pytest.param(_BROWSER_OVERRIDE, id="browser-override"),
        pytest.param(_GUI_OVERRIDE, id="gui-override"),
    ],
)
def test_compose_files_forbid_negated_profiles(path: Path) -> None:
    """W1.2: negated compose profiles are forbidden (``check-compose-default.sh:31-33``)."""
    if not path.is_file():
        pytest.fail(f"missing compose file for negated-profile scan: {path}")
    text = path.read_text(encoding="utf-8")
    line_matches = _NEGATED_PROFILE_LINE_RE.findall(text)
    assert line_matches == [], f"{path.name}: negated profiles forbidden: {line_matches}"
    assert not _NEGATED_PROFILE_INLINE_RE.search(text), (
        f"{path.name}: negated profile marker '\"!' found"
    )


@pytest.mark.parametrize("target", _COMPOSE_TARGET_NAMES)
def test_makefile_compose_target_exists(target: str) -> None:
    """W1.3: documented Makefile compose targets must be present."""
    assert re.search(rf"^{re.escape(target)}:", _makefile_text(), re.MULTILINE), (
        f"Makefile is missing {target}"
    )


@pytest.mark.parametrize("target", _COMPOSE_TARGET_NAMES)
def test_makefile_compose_target_resolves_single_gateway(target: str) -> None:
    """W1.3: each Makefile compose-up variant selects exactly one gateway."""
    compose_paths, profiles = _parse_makefile_compose_invocation(target)
    missing = [path for path in compose_paths if not path.is_file()]
    assert not missing, f"{target}: missing compose files: {missing}"
    merged = _merge_services(*compose_paths)
    active = _active_services(merged, profiles=profiles)
    gateways = _gateway_names(active)
    publishers = _gateway_port_publishers(active)
    assert len(gateways) == 1, f"{target}: expected one gateway, got {gateways}"
    assert len(publishers) == 1, f"{target}: expected one port publisher, got {publishers}"


@pytest.mark.xfail(
    reason="green after W3: operator service hardening (#166, D24)",
    strict=False,
)
@pytest.mark.parametrize(
    "service",
    [
        pytest.param("sevn-proxy", id="sevn-proxy"),
        pytest.param("sevn-gateway", id="sevn-gateway"),
    ],
)
def test_operator_services_declare_hardening_keys(service: str) -> None:
    """W1.4: proxy and gateway declare cap_drop, security_opt, limits, restart."""
    cfg = _load_services(_BASE_COMPOSE)[service]
    assert cfg.get("cap_drop") == ["ALL"], f"{service}: cap_drop [ALL] required"
    security_opt = cfg.get("security_opt") or []
    assert "no-new-privileges:true" in security_opt, (
        f"{service}: security_opt no-new-privileges:true required"
    )
    assert cfg.get("pids_limit") is not None, f"{service}: pids_limit required"
    assert cfg.get("restart") == "unless-stopped", f"{service}: restart unless-stopped required"
    deploy = cfg.get("deploy") or {}
    limits = (deploy.get("resources") or {}).get("limits") or {}
    assert limits.get("cpus"), f"{service}: deploy.resources.limits.cpus required"
    assert limits.get("memory"), f"{service}: deploy.resources.limits.memory required"


@pytest.mark.xfail(
    reason="green after W3: sevn-proxy read_only rootfs (#166, D24)",
    strict=False,
)
def test_sevn_proxy_read_only_with_tmpfs() -> None:
    """W1.4: sevn-proxy runs read-only with tmpfs for writable paths."""
    cfg = _load_services(_BASE_COMPOSE)["sevn-proxy"]
    assert cfg.get("read_only") is True, "sevn-proxy must set read_only: true"
    tmpfs = cfg.get("tmpfs") or []
    assert tmpfs, "sevn-proxy must declare tmpfs mounts for writable paths"


@pytest.mark.xfail(
    reason="green after W3: conditional operator-perms chown (#166, D25)",
    strict=False,
)
def test_operator_perms_has_no_unconditional_chown() -> None:
    """W1.5: sevn-operator-perms must not run unconditional ``chown -R``."""
    command = _operator_perms_command_text()
    unconditional = re.findall(
        r"chown\s+-R\s+10001:10001\s+/[^\s;]+",
        command,
    )
    assert unconditional == [], "unconditional chown -R forbidden; use find ! -user 10001 predicate"


@pytest.mark.xfail(
    reason="green after W3: conditional operator-perms chown (#166, D25)",
    strict=False,
)
def test_operator_perms_uses_conditional_find_chown() -> None:
    """W1.5: sevn-operator-perms scopes chown with ``! -user 10001``."""
    command = _operator_perms_command_text()
    assert "! -user 10001" in command, (
        "sevn-operator-perms must use find ! -user 10001 -exec chown …"
    )
