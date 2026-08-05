"""Prod-readiness Batch D W13 RED - container isolation and operator runtime (C8-C10).

Contracts (``.ignorelocal/waves/prod-readiness-0.0.1-wave-plan.md`` W13, D48-D50):
overlay-wide ``--no-sandbox`` ban (C8.1); stale overlay comments gone (C8.2); site-isolation
decision recorded (C8.4); versioned perms marker + CI init parity (C9.2/C9.4); documented
Compose version floor (C10.1); ``HostConfig`` enforcement check (C10.2); resolved ``docker
compose config`` limits for every service (C10.3 / D49 / W0.7); browser as its own service
(C8.3 / D50). Source-level and ``compose config`` assertions - HostConfig integration skips
without a Docker daemon.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess  # nosec B404
from pathlib import Path
from typing import Any

import pytest
import yaml

from sevn.security.sandbox_runtime import docker_daemon_reachable

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DOCKER_DIR = _REPO_ROOT / "docker"
_MAKEFILE = _REPO_ROOT / "Makefile"
_CHECK_COMPOSE = _REPO_ROOT / "scripts" / "check-compose-default.sh"
_CHROME_PY = _REPO_ROOT / "src" / "sevn" / "browser" / "chrome.py"
_SECURITY_README = _REPO_ROOT / "docs" / "readmes" / "security.md"
_DOCKER_README = _REPO_ROOT / "docker" / "README.md"
_ROOT_README = _REPO_ROOT / "README.md"
_CICD_SPEC = _REPO_ROOT / "about-sevn.bot" / "specs" / "25-cicd-full.md"

_BASE_COMPOSE = _DOCKER_DIR / "docker-compose.yml"
_BROWSER_OVERRIDE = _DOCKER_DIR / "docker-compose.browser.yml"
_GUI_OVERRIDE = _DOCKER_DIR / "docker-compose.gui.yml"
_CI_COMPOSE = _DOCKER_DIR / "docker-compose.ci.yml"

_COMPOSE_YAML_GLOBS = ("docker-compose*.yml",)
_NO_SANDBOX_TOKEN = "--no-sandbox"
_ISOLATE_ORIGINS_FLAG = "--disable-features=IsolateOrigins,site-per-process"
_PERMS_MARKER = "/operator/.sevn/perms-v1"
_COMMENT_LINE_RE = re.compile(r"^\s*#")
_COMPOSE_MIN_VERSION_RE = re.compile(
    r"(?:minimum|min(?:imum)?)\s+(?:docker\s+)?compose(?:\s+version)?\s*[:=]?\s*"
    r"v?(?P<ver>\d+(?:\.\d+)+)",
    re.IGNORECASE,
)
_COMPOSE_VERSION_ENFORCE_RE = re.compile(
    r"compose[_ -]?version|COMPOSE_VERSION|minimum.?compose|docker compose version",
    re.IGNORECASE,
)

_FILE_SETS: tuple[tuple[str, tuple[Path, ...]], ...] = (
    ("base", (_BASE_COMPOSE,)),
    ("browser", (_BASE_COMPOSE, _BROWSER_OVERRIDE)),
    ("gui", (_BASE_COMPOSE, _GUI_OVERRIDE)),
    ("ci", (_CI_COMPOSE,)),
)


def _compose_yaml_paths() -> list[Path]:
    return sorted(
        path
        for pattern in _COMPOSE_YAML_GLOBS
        for path in _DOCKER_DIR.glob(pattern)
        if path.is_file()
    )


def _strip_yaml_comments(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not _COMMENT_LINE_RE.match(line))


def _load_services(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    services = data.get("services")
    if not isinstance(services, dict):
        return {}
    return services


def _service_command_text(path: Path, service: str) -> str:
    cfg = _load_services(path).get(service, {})
    if not isinstance(cfg, dict):
        return ""
    command = cfg.get("command")
    if isinstance(command, list):
        return "\n".join(str(part) for part in command)
    return str(command or "")


def _docker_bin() -> str | None:
    return shutil.which("docker")


def _compose_config_json(compose_paths: tuple[Path, ...]) -> dict[str, Any]:
    docker = _docker_bin()
    if docker is None:
        pytest.skip("docker CLI not on PATH")
    args = [docker, "compose"]
    for path in compose_paths:
        args.extend(["-f", str(path)])
    args.extend(["config", "--format", "json"])
    proc = subprocess.run(
        args,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
        cwd=str(_REPO_ROOT),
    )  # nosec B603
    if proc.returncode != 0:
        pytest.skip(f"docker compose config failed: {proc.stderr.strip() or proc.stdout.strip()}")
    data = json.loads(proc.stdout)
    assert isinstance(data, dict)
    return data


def _service_has_limits(svc: dict[str, Any]) -> bool:
    deploy = svc.get("deploy") or {}
    limits = (deploy.get("resources") or {}).get("limits") or {}
    cpus = limits.get("cpus")
    memory = limits.get("memory")
    pids = limits.get("pids")
    pids_limit = svc.get("pids_limit")
    return bool(cpus) and bool(memory) and (pids is not None or pids_limit is not None)


def _docs_mention_compose_floor() -> bool:
    blobs = []
    for path in (_DOCKER_README, _ROOT_README, _CICD_SPEC, _MAKEFILE):
        if path.is_file():
            blobs.append(path.read_text(encoding="utf-8"))
    joined = "\n".join(blobs)
    return _COMPOSE_MIN_VERSION_RE.search(joined) is not None


def _preflight_enforces_compose_version() -> bool:
    texts: list[str] = []
    if _CHECK_COMPOSE.is_file():
        texts.append(_CHECK_COMPOSE.read_text(encoding="utf-8"))
    if _MAKEFILE.is_file():
        texts.append(_MAKEFILE.read_text(encoding="utf-8"))
    for path in (_REPO_ROOT / "scripts").glob("*compose*"):
        if path.is_file():
            texts.append(path.read_text(encoding="utf-8"))
    joined = "\n".join(texts)
    # Enforcement must compare a parsed client version, not only mention the word.
    return bool(
        re.search(r"version.*(?:lt|ge|compare|require)|require.*compose", joined, re.I)
        and _COMPOSE_VERSION_ENFORCE_RE.search(joined)
    )


def _site_isolation_justified() -> bool:
    """True when login-grade drops IsolateOrigins or docs justify keeping it."""
    chrome = _CHROME_PY.read_text(encoding="utf-8") if _CHROME_PY.is_file() else ""
    if _ISOLATE_ORIGINS_FLAG not in chrome:
        return True
    for path in (_SECURITY_README, _DOCKER_README, _CICD_SPEC):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        if ("IsolateOrigins" in text or "site-per-process" in text) and re.search(
            r"threat\s+model|justif|login-grade|untrusted",
            text,
            re.I,
        ):
            return True
    return False


def _browser_service_names(services: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for name, cfg in services.items():
        if not isinstance(cfg, dict):
            continue
        lowered = name.lower()
        if "browser" in lowered and "gateway" not in lowered:
            names.append(name)
            continue
        image = str(cfg.get("image") or "")
        build = cfg.get("build") or {}
        dockerfile = ""
        if isinstance(build, dict):
            dockerfile = str(build.get("dockerfile") or "")
        elif isinstance(build, str):
            dockerfile = build
        if name != "sevn-gateway" and (
            "browser" in image.lower() or "Dockerfile.gateway.browser" in dockerfile
        ):
            names.append(name)
    return sorted(set(names))


def _volume_sources(cfg: dict[str, Any]) -> list[str]:
    sources: list[str] = []
    for entry in cfg.get("volumes") or []:
        if isinstance(entry, str):
            sources.append(entry.split(":", 1)[0])
        elif isinstance(entry, dict):
            src = entry.get("source") or entry.get("src")
            if src:
                sources.append(str(src))
    return sources


def _env_mapping(cfg: dict[str, Any]) -> dict[str, str]:
    env = cfg.get("environment") or {}
    if isinstance(env, dict):
        return {str(k): str(v) for k, v in env.items()}
    if isinstance(env, list):
        out: dict[str, str] = {}
        for item in env:
            text = str(item)
            if "=" in text:
                key, val = text.split("=", 1)
                out[key] = val
        return out
    return {}


# ---------------------------------------------------------------------------
# W13.2 — C8.1: no compose overlay passes --no-sandbox
# ---------------------------------------------------------------------------


def test_no_compose_file_passes_no_sandbox() -> None:
    """W13.2 / C8.1: every compose YAML must not set ``--no-sandbox`` outside comments."""
    offenders: list[str] = []
    for path in _compose_yaml_paths():
        active = _strip_yaml_comments(path.read_text(encoding="utf-8"))
        if _NO_SANDBOX_TOKEN in active:
            offenders.append(path.name)
    assert offenders == [], f"--no-sandbox forbidden in compose overlays: {offenders}"


# ---------------------------------------------------------------------------
# W13.3 — C8.2: stale --no-sandbox comments gone
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        pytest.param(_BROWSER_OVERRIDE, id="browser-override"),
        pytest.param(_GUI_OVERRIDE, id="gui-override"),
    ],
)
def test_browser_gui_overrides_drop_stale_no_sandbox_comments(path: Path) -> None:
    """W13.3 / C8.2: browser/gui overrides must not claim Brave runs with ``--no-sandbox``."""
    assert path.is_file(), f"missing override {path}"
    text = path.read_text(encoding="utf-8")
    comment_hits = [
        line
        for line in text.splitlines()
        if _COMMENT_LINE_RE.match(line) and _NO_SANDBOX_TOKEN in line
    ]
    assert comment_hits == [], f"{path.name}: stale --no-sandbox comments remain: {comment_hits}"


# ---------------------------------------------------------------------------
# W13.4 — C8.4: site-isolation decision recorded
# ---------------------------------------------------------------------------


def test_site_isolation_flag_removed_or_documented() -> None:
    """W13.4 / C8.4: login-grade IsolateOrigins is gone or justified in docs."""
    assert _site_isolation_justified(), (
        f"{_ISOLATE_ORIGINS_FLAG} remains in login-grade args without a documented "
        "threat-model justification (docs/readmes/security.md or sibling)"
    )


# ---------------------------------------------------------------------------
# W13.5 — C9.2 / C9.4: marker gating + CI init parity
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    reason="green after W15: versioned perms marker gates migration (C9.2)", strict=False
)
def test_operator_perms_skips_broad_migration_when_marker_present() -> None:
    """W13.5 / C9.2: init checks the versioned marker before a broad ownership pass."""
    command = _service_command_text(_BASE_COMPOSE, "sevn-operator-perms")
    assert _PERMS_MARKER in command, f"marker {_PERMS_MARKER} missing from sevn-operator-perms"
    # Marker presence must short-circuit: test/ -f / [ -f before chown/find work.
    assert re.search(
        rf"(?:test\s+-f|\[\s+-f)\s+{_PERMS_MARKER.replace('.', r'\.')}",
        command,
    ) or re.search(rf"if\s+.*{_PERMS_MARKER.replace('.', r'\.')}", command), (
        "sevn-operator-perms must skip broad migration when the versioned marker exists"
    )


@pytest.mark.xfail(
    reason="green after W15: sevn-ci-init drops unconditional chown -R (C9.4)", strict=False
)
def test_ci_init_has_no_unconditional_chown() -> None:
    """W13.5 / C9.4: ``sevn-ci-init`` must not run unconditional ``chown -R`` on /operator."""
    command = _service_command_text(_CI_COMPOSE, "sevn-ci-init")
    unconditional = re.findall(r"chown\s+-R\s+10001:10001\s+/[^\s;]+", command)
    assert unconditional == [], (
        f"sevn-ci-init still runs unconditional chown -R: {unconditional}; "
        "apply scoped+marker treatment or document intentional CI divergence"
    )


# ---------------------------------------------------------------------------
# W13.6 — C10.1: minimum Docker Compose version
# ---------------------------------------------------------------------------


@pytest.mark.xfail(reason="green after W16: documented Compose version floor (C10.1)", strict=False)
def test_minimum_docker_compose_version_is_documented() -> None:
    """W13.6 / C10.1: a minimum Docker Compose version is pinned in operator docs/spec."""
    assert _docs_mention_compose_floor(), (
        "document a minimum Docker Compose version in docker/README.md, README.md, "
        "or about-sevn.bot/specs/25-cicd-full.md"
    )


@pytest.mark.xfail(
    reason="green after W16: Compose version floor enforced in preflight (C10.1)", strict=False
)
def test_compose_preflight_enforces_minimum_version() -> None:
    """W13.6 / C10.1: preflight (check-compose-default or sibling) refuses older clients."""
    assert _preflight_enforces_compose_version(), (
        "scripts/check-compose-default.sh (or sibling) must enforce the Compose version floor"
    )


# ---------------------------------------------------------------------------
# W13.7 — C10.2: HostConfig integration check
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    reason="green after W16: HostConfig NanoCpus/Memory/PidsLimit check (C10.2)", strict=False
)
def test_created_containers_hostconfig_matches_declared_limits() -> None:
    """W13.7 / C10.2: created containers expose non-zero HostConfig matching compose limits.

    Uses the CI file set (W0.7: no resolved limits today). Declared-limits assertion runs
    before ``compose create`` so the case stays red without local CI images; HostConfig
    matching runs when create succeeds.
    """
    if not docker_daemon_reachable():
        pytest.skip("Docker daemon not reachable")
    docker = _docker_bin()
    if docker is None:
        pytest.skip("docker CLI not on PATH")

    service_names = ("sevn-proxy", "sevn-gateway")
    config = _compose_config_json((_CI_COMPOSE,))
    services = config.get("services") or {}
    declared: dict[str, dict[str, Any]] = {}
    for name in service_names:
        svc = services[name]
        limits = ((svc.get("deploy") or {}).get("resources") or {}).get("limits") or {}
        assert limits.get("cpus"), (
            f"{name}: CI resolved config must declare deploy.resources.limits.cpus "
            "(C10.3 prerequisite for C10.2)"
        )
        assert limits.get("memory"), (
            f"{name}: CI resolved config must declare deploy.resources.limits.memory "
            "(C10.3 prerequisite for C10.2)"
        )
        declared[name] = {
            "limits": limits,
            "pids_limit": svc.get("pids_limit"),
        }

    project = "sevn-w13-hostconfig-ci"
    compose_args = [
        docker,
        "compose",
        "-p",
        project,
        "-f",
        str(_CI_COMPOSE),
    ]
    try:
        create = subprocess.run(
            [*compose_args, "create", *service_names],
            check=False,
            capture_output=True,
            text=True,
            timeout=180,
            cwd=str(_REPO_ROOT),
        )  # nosec B603
        if create.returncode != 0:
            pytest.skip(
                "compose create failed (images may be absent): "
                f"{create.stderr.strip() or create.stdout.strip()}"
            )
        for name in service_names:
            limits = declared[name]["limits"]
            ps = subprocess.run(
                [*compose_args, "ps", "-aq", name],
                check=False,
                capture_output=True,
                text=True,
                timeout=60,
                cwd=str(_REPO_ROOT),
            )  # nosec B603
            cid = (ps.stdout or "").strip().splitlines()
            assert cid, f"{name}: no container id after compose create"
            inspect = subprocess.run(
                [docker, "inspect", cid[0], "--format", "{{json .HostConfig}}"],
                check=False,
                capture_output=True,
                text=True,
                timeout=60,
            )  # nosec B603
            assert inspect.returncode == 0, inspect.stderr
            host = json.loads(inspect.stdout)
            nano = int(host.get("NanoCpus") or 0)
            memory = int(host.get("Memory") or 0)
            pids = int(host.get("PidsLimit") or 0)
            assert nano > 0, f"{name}: HostConfig.NanoCpus must be non-zero"
            assert memory > 0, f"{name}: HostConfig.Memory must be non-zero"
            assert pids > 0, f"{name}: HostConfig.PidsLimit must be non-zero"
            declared_cpus = limits.get("cpus")
            declared_memory = limits.get("memory")
            declared_pids = limits.get("pids") or declared[name]["pids_limit"]
            expected_nano = int(float(declared_cpus) * 1_000_000_000)
            assert nano == expected_nano, (
                f"{name}: NanoCpus {nano} != declared cpus {declared_cpus} ({expected_nano})"
            )
            assert memory == int(declared_memory), (
                f"{name}: Memory {memory} != declared {declared_memory}"
            )
            if declared_pids is not None:
                assert pids == int(declared_pids), (
                    f"{name}: PidsLimit {pids} != declared {declared_pids}"
                )
    finally:
        subprocess.run(
            [*compose_args, "down", "--remove-orphans"],
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(_REPO_ROOT),
        )  # nosec B603


# ---------------------------------------------------------------------------
# W13.8 — C10.3 / D49: resolved compose config limits (W0.7)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "compose_paths"),
    [pytest.param(label, paths, id=label) for label, paths in _FILE_SETS],
)
@pytest.mark.xfail(
    reason="green after W16: every resolved service declares limits (C10.3/D49)",
    strict=False,
)
def test_resolved_compose_config_declares_limits_for_every_service(
    label: str,
    compose_paths: tuple[Path, ...],
) -> None:
    """W13.8 / C10.3: ``docker compose config`` yields limits for every service (W0.7)."""
    missing = [path for path in compose_paths if not path.is_file()]
    assert not missing, f"{label}: missing compose files: {missing}"
    config = _compose_config_json(compose_paths)
    services = config.get("services") or {}
    assert services, f"{label}: resolved config has no services"
    lacking = sorted(name for name, svc in services.items() if not _service_has_limits(svc))
    assert lacking == [], (
        f"{label}: services missing deploy.resources.limits and/or pids_limit: {lacking}"
    )


# ---------------------------------------------------------------------------
# W13.9 — C8.3 / D50: browser as its own minimally-privileged service
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    reason="green after W17: browser service split without sevn-state / gateway token (C8.3)",
    strict=False,
)
def test_browser_runs_as_own_service_without_state_or_gateway_token() -> None:
    """W13.9 / C8.3: browser is a separate service — no ``sevn-state``, no ``SEVN_GATEWAY_TOKEN``."""
    assert _BROWSER_OVERRIDE.is_file()
    services = _load_services(_BROWSER_OVERRIDE)
    browser_names = _browser_service_names(services)
    assert browser_names, (
        "browser override must define a dedicated browser service "
        "(not only merge Brave into sevn-gateway)"
    )
    for name in browser_names:
        cfg = services[name]
        assert isinstance(cfg, dict)
        sources = _volume_sources(cfg)
        assert "sevn-state" not in sources, (
            f"{name}: must not mount sevn-state (got volumes {sources})"
        )
        env = _env_mapping(cfg)
        assert "SEVN_GATEWAY_TOKEN" not in env, f"{name}: must not receive SEVN_GATEWAY_TOKEN"
