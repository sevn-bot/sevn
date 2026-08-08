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
import os
import re
import shutil
import subprocess  # nosec B404
import tempfile
import time
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
# W13.4b — C8.1 runtime: Brave smoke in the hardened prod container
# ---------------------------------------------------------------------------


# Order matters: the CI docker job builds `sevn-gateway-browser:ci`; the local
# `make docker-build-ci` Makefile target builds `:local`. The operator can also
# pin a different tag via SEVN_BROWSER_SMOKE_IMAGE.
_BRAVE_SMOKE_IMAGE_CANDIDATES = (
    os.environ.get("SEVN_BROWSER_SMOKE_IMAGE", "").strip(),
    "sevn-gateway-browser:ci",
    "sevn-gateway-browser:local",
)
_BRAVE_SMOKE_CDP_PORT = 9222
_BRAVE_SMOKE_LAUNCH_TIMEOUT_S = 25.0
_BRAVE_SMOKE_CDP_POLL_INTERVAL_S = 0.5
_BRAVE_SMOKE_CONTAINER_NAME = "sevn-w13-brave-smoke"


def _resolve_brave_smoke_image(docker: str) -> str | None:
    """Return the first acceptable browser image present, or None.

    Accepts (in priority order):
    1. ``SEVN_BROWSER_SMOKE_IMAGE`` if set and present.
    2. ``sevn-gateway-browser:ci`` — what the CI ``docker-images`` job builds.
    3. ``sevn-gateway-browser:local`` — what ``make docker-build-ci`` builds.

    Empty strings and untruthy env values are skipped.
    """
    for candidate in _BRAVE_SMOKE_IMAGE_CANDIDATES:
        if not candidate:
            continue
        if _ci_image_present(docker, candidate):
            return candidate
    return None


def test_brave_runs_in_hardened_container_without_no_sandbox() -> None:
    """W13.4b / C8.1: dockerized Brave boots headless in a hardened container without ``--no-sandbox``.

    The static checks above prove the YAML config has no ``--no-sandbox``; this
    proves the dockerized browser actually starts in a hardened container
    (``cap_drop: ALL`` + ``no-new-privileges`` + non-root uid ``10001``) when
    driven by the prod overlay's environment. CDP readiness is the contract:
    we launch real headless Brave (``--headless=new``) with
    ``--remote-debugging-port`` and a bind-mounted ``--user-data-dir``, then
    poll the user-data-dir for ``DevToolsActivePort`` (the file Chromium writes
    once the CDP endpoint is reachable). The launch must succeed and the
    renderer must remain running long enough to write that file.

    The image is env-overridable via ``SEVN_BROWSER_SMOKE_IMAGE`` (default
    ``sevn-gateway-browser:ci``; falls back to ``sevn-gateway-browser:local``).
    The CI ``docker-images`` job runs this test so a missing or broken image
    surfaces as a red check on the PR.

    Skip policy: skip ONLY when the Docker daemon is genuinely unreachable or
    when no acceptable image is present locally. A failed launch against a
    present image **fails** the test (no ``exit 0`` swallow).
    """
    if not docker_daemon_reachable():
        pytest.skip("Docker daemon not reachable")
    docker = _docker_bin()
    if docker is None:
        pytest.skip("docker CLI not on PATH")
    image = _resolve_brave_smoke_image(docker)
    if image is None:
        pytest.skip(
            "no acceptable browser image present (checked "
            "SEVN_BROWSER_SMOKE_IMAGE, sevn-gateway-browser:ci, "
            "sevn-gateway-browser:local); build with `make docker-build-ci` "
            "to run this test"
        )

    with tempfile.TemporaryDirectory(prefix="sevn-w13-brave-") as tmp_str:
        profile_host = Path(tmp_str) / "profile"
        profile_host.mkdir(parents=True, exist_ok=True)
        # Bind the host tmp dir into the container at /tmp/w13-profile so we can
        # read DevToolsActivePort from the host without docker exec gymnastics.
        # The container runs as uid 10001; the dir must be writable by that uid.
        os.chmod(profile_host, 0o777)

        # Detached so the renderer keeps running while we poll. --rm cleans up
        # on stop; we also force-rm in the finally below for safety.
        run_args = [
            docker,
            "run",
            "-d",
            "--rm",
            "--name",
            _BRAVE_SMOKE_CONTAINER_NAME,
            "--security-opt=no-new-privileges:true",
            "--cap-drop=ALL",
            "--user=10001:10001",
            # Mirror the prod overlay environment exactly.
            "-e",
            "SEVN_BROWSER_EXTRA_ARGS=--disable-dev-shm-usage",
            "-e",
            "SEVN_CHROME_EXECUTABLE=/usr/bin/brave-browser",
            "-e",
            "SEVN_BROWSER_ENGINE=brave",
            # Bind the host profile dir into the container so we can read
            # DevToolsActivePort from the host side (Chromium writes it under
            # the user-data-dir on CDP readiness).
            "-v",
            f"{profile_host}:/tmp/w13-profile",
            image,
            # Skip the gateway entrypoint (we are not running the gateway here);
            # just exec Brave directly. The entrypoint only runs the gateway
            # when /operator/workspace/sevn.json is present, but going around it
            # keeps the contract narrower: "Brave itself boots under the
            # hardened flags".
            "sh",
            "-c",
            # Refuse --no-sandbox if anything in the env sneaks it in. The
            # assertion below verifies the marker is absent, but failing fast
            # surfaces the regression immediately.
            'case " :${SEVN_BROWSER_EXTRA_ARGS}:" in '
            "*--no-sandbox*) echo BAD_ENV; exit 1;; "
            "esac; "
            "exec /usr/bin/brave-browser "
            "--headless=new "
            f"--remote-debugging-port={_BRAVE_SMOKE_CDP_PORT} "
            "--remote-debugging-address=127.0.0.1 "
            "--user-data-dir=/tmp/w13-profile "
            "--no-first-run --no-default-browser-check "
            "--disable-dev-shm-usage "
            "--disable-background-networking "
            "--disable-background-timer-throttling "
            "--disable-features=TranslateUI "
            "about:blank",
        ]
        try:
            launch = subprocess.run(
                run_args,
                check=False,
                capture_output=True,
                text=True,
                timeout=15,
                cwd=str(_REPO_ROOT),
            )  # nosec B603
            assert launch.returncode == 0, (
                f"docker run failed for {image} (image is present, so this is "
                f"a product failure, not an environment skip): "
                f"{(launch.stderr or launch.stdout).strip()}"
            )
            container_id = (launch.stdout or "").strip()
            assert container_id, (
                f"docker run -d produced no container id: {(launch.stderr or '').strip()}"
            )

            # Poll the user-data-dir for DevToolsActivePort. Chromium writes
            # "<port>\n<host>\n" once the remote-debugging listener is up.
            devtools_port: int | None = None
            deadline = time.monotonic() + _BRAVE_SMOKE_LAUNCH_TIMEOUT_S
            while time.monotonic() < deadline:
                port_file = profile_host / "DevToolsActivePort"
                if port_file.is_file():
                    try:
                        first_line = port_file.read_text(encoding="utf-8").splitlines()[0]
                        parsed = int(first_line.strip())
                        if parsed > 0:
                            devtools_port = parsed
                            break
                    except (OSError, ValueError):
                        pass
                # Confirm the container is still running; if it exited the
                # renderer never came up.
                ps = subprocess.run(
                    [
                        docker,
                        "inspect",
                        "--format",
                        "{{.State.Running}} {{.State.ExitCode}}",
                        _BRAVE_SMOKE_CONTAINER_NAME,
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )  # nosec B603
                state = (ps.stdout or "").strip()
                assert state.startswith("true "), (
                    f"Brave exited before DevToolsActivePort appeared "
                    f"(state={state!r}); stderr: "
                    f"{(launch.stderr or '').strip()}"
                )
                time.sleep(_BRAVE_SMOKE_CDP_POLL_INTERVAL_S)

            assert devtools_port is not None, (
                f"DevToolsActivePort never appeared in {profile_host} within "
                f"{_BRAVE_SMOKE_LAUNCH_TIMEOUT_S:.0f}s; Brave launched but did "
                "not become CDP-ready. Renderer likely needs --no-sandbox or "
                "kernel user namespaces to start."
            )

            # Confirm the env we handed Brave did NOT include --no-sandbox.
            # We inspect the live container so this is a runtime assertion, not
            # just a substring scan on the launch string.
            env_inspect = subprocess.run(
                [
                    docker,
                    "exec",
                    _BRAVE_SMOKE_CONTAINER_NAME,
                    "sh",
                    "-c",
                    'case " :${SEVN_BROWSER_EXTRA_ARGS}:" in '
                    "*--no-sandbox*) echo BAD_ENV; exit 1;; "
                    "esac; "
                    "printf OK",
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )  # nosec B603
            assert env_inspect.returncode == 0, (
                f"prod-overlay SEVN_BROWSER_EXTRA_ARGS contains --no-sandbox "
                f"(container env): {(env_inspect.stderr or '').strip()}"
            )
            assert env_inspect.stdout.strip() == "OK", (
                f"unexpected SEVN_BROWSER_EXTRA_ARGS marker: {env_inspect.stdout!r}"
            )
        finally:
            subprocess.run(
                [docker, "rm", "-f", _BRAVE_SMOKE_CONTAINER_NAME],
                check=False,
                capture_output=True,
                text=True,
                timeout=15,
            )  # nosec B603


# ---------------------------------------------------------------------------
# W13.5 — C9.2 / C9.4: marker gating + CI init parity
# ---------------------------------------------------------------------------


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


def test_minimum_docker_compose_version_is_documented() -> None:
    """W13.6 / C10.1: a minimum Docker Compose version is pinned in operator docs/spec."""
    assert _docs_mention_compose_floor(), (
        "document a minimum Docker Compose version in docker/README.md, README.md, "
        "or about-sevn.bot/specs/25-cicd-full.md"
    )


def test_compose_preflight_enforces_minimum_version() -> None:
    """W13.6 / C10.1: preflight (check-compose-default or sibling) refuses older clients."""
    assert _preflight_enforces_compose_version(), (
        "scripts/check-compose-default.sh (or sibling) must enforce the Compose version floor"
    )


# ---------------------------------------------------------------------------
# W13.7 — C10.2: HostConfig integration check
# ---------------------------------------------------------------------------


def _ci_image_present(docker: str, image: str) -> bool:
    proc = subprocess.run(
        [docker, "image", "inspect", image],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )  # nosec B603
    return proc.returncode == 0


def test_created_containers_hostconfig_matches_declared_limits() -> None:
    """W13.7 / C10.2: created containers expose non-zero HostConfig matching compose limits.

    Declared-limits assertion always runs (C10.3 prerequisite). HostConfig matching runs
    when the two service images we actually inspect are present locally and ``compose
    create --pull never`` succeeds for both; otherwise skip (no build/pull). The pre-check
    derives the resolved image names from ``docker compose config`` for the two services
    we inspect — pre-checking dependency images (``sevn-ci-init``, ``mock-openai``,
    ``busybox``, …) would silently skip whenever a dependency service is named without an
    explicit ``image:`` (Compose then tags the build with a project-derived name,
    e.g. ``<project>-mock-openai``, which the static name never matches).

    To keep the create bounded to the two services we inspect (and avoid the
    ``unknown flag: --no-deps`` failure that ``docker compose create`` raises
    when the ``--no-deps`` flag is passed — it does not exist on
    ``create``, only on ``up`` / ``run``), we render a minimal Compose project
    that strips out every service except the two under test and keeps only
    the project-wide ``networks: default``. The rendered file is written to a
    tempdir under the repo and torn down in the finally block. A nonzero
    ``compose create`` after all required images are verified present is a
    product/config failure — fail closed, do not skip.
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
    resolved_images: dict[str, str] = {}
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
        # Resolve the exact image name Compose will hand to dockerd for create.
        # When `image:` is set (the CI case for sevn-proxy / sevn-gateway),
        # services[name].image is the source of truth. When it is not set,
        # Compose derives a project-prefixed name and we surface that as the
        # expected image so the pre-check is honest about what we are about to
        # create.
        image = str(svc.get("image") or "").strip()
        if image:
            resolved_images[name] = image
        else:
            project_prefix = (config.get("name") or "sevn").strip() or "sevn"
            resolved_images[name] = f"{project_prefix}-{name}"

    missing_images = [
        f"{name} -> {img}"
        for name, img in resolved_images.items()
        if not _ci_image_present(docker, img)
    ]
    if missing_images:
        pytest.skip(
            "CI service images not present locally (skip HostConfig create; "
            "no build/pull): " + ", ".join(missing_images)
        )

    # Render a minimal compose project that only references the two services
    # we want to inspect. ``docker compose create`` does NOT support
    # ``--no-deps`` (it is a create-time-only flag and the docker CLI rejects
    # it), so the only honest way to keep the create bounded to those two
    # services is to give Compose a project that has no other services in it.
    # We pull each service block verbatim from the resolved config (so
    # ``deploy.resources.limits``, ``pids_limit``, ``image:``, ``pull_policy:``
    # all survive) and only keep the project-wide ``networks:`` defaults.
    project = "sevn-w13-hostconfig-ci"
    with tempfile.TemporaryDirectory(prefix="sevn-w13-hostconfig-") as tmp_str:
        minimal_compose = Path(tmp_str) / "compose.yml"
        minimal_services: dict[str, Any] = {}
        for name in service_names:
            svc = dict(services[name])
            # Strip depends_on so the minimal project validates (sevn-proxy
            # and sevn-gateway reference mock-openai / sevn-ci-init, which
            # are deliberately omitted from this project). Without this the
            # Compose file fails schema validation with "depends on undefined
            # service" before any container is created.
            svc.pop("depends_on", None)
            # Strip volumes / networks references that point at sibling
            # services in the full stack — only the named networks and
            # project volumes are kept in the minimal project (see below).
            minimal_services[name] = svc
        minimal_payload: dict[str, Any] = {
            "name": project,
            "services": minimal_services,
        }
        # Preserve project-wide networks / volumes when present, but scope them
        # to only what the two target services reference; an unreferenced
        # ``volumes:`` entry (e.g. the seed ``sevn-ci-workspace``) is harmless
        # because no service mounts it.
        if config.get("networks"):
            minimal_payload["networks"] = config["networks"]
        if config.get("volumes"):
            minimal_payload["volumes"] = config["volumes"]
        minimal_compose.write_text(
            yaml.safe_dump(minimal_payload, sort_keys=False), encoding="utf-8"
        )

        compose_args = [
            docker,
            "compose",
            "-p",
            project,
            "-f",
            str(minimal_compose),
        ]
        try:
            create = subprocess.run(
                [
                    *compose_args,
                    "create",
                    "--pull",
                    "never",
                    *service_names,
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=120,
                cwd=str(_REPO_ROOT),
            )  # nosec B603
            # Daemon is reachable and both required images were already verified
            # present, so a nonzero create is a product/config failure — fail closed
            # instead of skipping, otherwise the HostConfig proof is meaningless.
            create_detail = (create.stderr or create.stdout).strip()
            assert create.returncode == 0, (
                f"compose create failed (daemon reachable, images present, "
                f"so this is a config failure not an environment skip): "
                f"{create_detail}"
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
    reason=(
        "deferred D50/#240: browser service split without sevn-state / gateway token (C8.3); "
        "not green until follow-up PR"
    ),
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
