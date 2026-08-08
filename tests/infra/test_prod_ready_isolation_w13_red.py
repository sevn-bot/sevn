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

import contextlib
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


def test_check_no_sandbox_in_compose_strips_comments_under_posix_grep(tmp_path: Path) -> None:
    r"""D-PR-4: comment-stripping regex in ``_check_no_sandbox_in_compose`` must be POSIX-portable.

    The preflight runs on supported macOS hosts whose ``/usr/bin/grep`` is BSD
    grep, and on minimal Linux containers where the ``grep`` in ``/usr/bin`` is
    a strict-POSIX build that does not implement the GNU ``\s`` shorthand.
    A regex like ``^\s*#`` is therefore interpreted literally as
    ``^s*#`` and only matches lines whose first non-anchor character is
    the literal letter ``s``; every comment line that does not start with
    ``s`` leaks into the active-config window, and a compose file whose
    ``--no-sandbox`` token lives only inside ``# --no-sandbox …`` comments
    is wrongly rejected.

    Two-part RED test:

    1. **Static guard** — scan ``scripts/check-compose-default.sh`` for any
       ``\s`` used as a regex whitespace class (the pattern that bit the
       previous version). POSIX BRE / ERE do not define ``\s``; the script
       must use ``[[:space:]]`` or an equivalent POSIX character class.
       This is the assertion that catches a regression on a stripped
       Linux image where ``/usr/bin/grep`` is genuinely strict-BSD.
    2. **Runtime exercise** — invoke the helper in a subprocess with
       ``PATH=/usr/bin:/bin`` (the documented supported-host baseline;
       on macOS this resolves BSD grep, on Linux it resolves whatever
       POSIX grep is on the bare PATH) and confirm a comment-only
       ``--no-sandbox`` is stripped while an active ``--no-sandbox`` token
       is still rejected (covered by the companion test below).
    """
    script_text = _CHECK_COMPOSE.read_text(encoding="utf-8")
    # Static guard — no ``\s`` inside a basic-regex pattern in the script.
    # Match ``grep ... `` followed by a quoted pattern that contains ``\s``.
    grep_basic_quote_pattern = re.compile(
        r"grep[^\n]*?['\"]([^'\"]*\\s[^'\"]*)['\"]",
    )
    hits = grep_basic_quote_pattern.findall(script_text)
    assert not hits, (
        "scripts/check-compose-default.sh still relies on the GNU grep "
        r"\s extension; replace with POSIX [[:space:]] to stay portable "
        f"across BSD / POSIX-only hosts. Hits: {hits}"
    )

    compose_with_commented_no_sandbox = (
        "services:\n"
        "  sevn-gateway:\n"
        "    image: example\n"
        # Leading-whitespace comment containing the token — the kind of
        # comment a previous regex with \s would mishandle.
        "    # --no-sandbox is forbidden; we run with the renderer sandbox on\n"
        "# --no-sandbox in plain comment form\n"
        "    environment:\n"
        "      - SEVN_GATEWAY_TOKEN=placeholder-token-32chars\n"
    )
    fixture = tmp_path / "docker-compose.comment-only.yml"
    fixture.write_text(compose_with_commented_no_sandbox, encoding="utf-8")

    # Extract just the function definition from the script body so we can
    # invoke it without the rest of the script (docker check, version
    # comparison, etc.) firing. We grab the heredoc-safe region between the
    # ``_check_no_sandbox_in_compose()`` opening and the closing brace of
    # the function.
    start = script_text.index("_check_no_sandbox_in_compose() {")
    end = script_text.index("}\n", start) + 1
    function_body = script_text[start:end]

    runner = tmp_path / "run.sh"
    runner.write_text(
        "set -e\n" + function_body + '\n_check_no_sandbox_in_compose "$1"\n',
        encoding="utf-8",
    )
    runner.chmod(0o755)

    # PATH=/usr/bin:/bin forces the host's bare ``/usr/bin`` + ``/bin``
    # greps, which on macOS is BSD grep and on minimal Linux containers is
    # whatever POSIX grep happens to be present. The static guard above is
    # what catches a regression on a strict-POSIX host; the runtime pass
    # below catches any logic bug in the comment-stripping helper itself.
    proc = subprocess.run(  # nosec B603
        ["/bin/bash", str(runner), str(fixture)],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)},
    )
    assert proc.returncode == 0, (
        "_check_no_sandbox_in_compose rejected a comment-only --no-sandbox "
        "line. The comment-stripping regex must use a POSIX-portable "
        "whitespace class (e.g. [[:space:]]) so strict-BSD / POSIX-only "
        "greps handle it. "
        f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )


def test_check_no_sandbox_in_compose_rejects_active_token(tmp_path: Path) -> None:
    """D-PR-4 complement: an active (non-comment) ``--no-sandbox`` must still be rejected.

    The POSIX-portable regex must not weaken the active-token detection:
    a YAML whose ``--no-sandbox`` is *not* in a comment line must still
    fail the preflight under the same POSIX PATH.
    """
    compose_with_active_no_sandbox = (
        "services:\n"
        "  sevn-gateway:\n"
        "    image: example\n"
        "    environment:\n"
        '      - "SEVN_BROWSER_EXTRA_ARGS=--no-sandbox"\n'
    )
    fixture = tmp_path / "docker-compose.active.yml"
    fixture.write_text(compose_with_active_no_sandbox, encoding="utf-8")

    script_text = _CHECK_COMPOSE.read_text(encoding="utf-8")
    start = script_text.index("_check_no_sandbox_in_compose() {")
    end = script_text.index("}\n", start) + 1
    function_body = script_text[start:end]

    runner = tmp_path / "run.sh"
    runner.write_text(
        "set -e\n" + function_body + '\n_check_no_sandbox_in_compose "$1"\n',
        encoding="utf-8",
    )
    runner.chmod(0o755)

    proc = subprocess.run(  # nosec B603
        ["/bin/bash", str(runner), str(fixture)],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)},
    )
    assert proc.returncode != 0, (
        "_check_no_sandbox_in_compose accepted an active --no-sandbox token; "
        "the POSIX regex rewrite must preserve the rejection semantics. "
        f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )


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
_BRAVE_SMOKE_LAUNCH_TIMEOUT_S = 45.0
_BRAVE_SMOKE_CDP_POLL_INTERVAL_S = 0.5
_BRAVE_SMOKE_CONTAINER_NAME = "sevn-w13-brave-smoke"
# Chromium only writes ``DevToolsActivePort`` when the listener picks its own
# port (``--remote-debugging-port=0``). Passing a fixed port (e.g. ``9222``)
# makes CDP reachable but the file is never created, so polling for it would
# always time out. The smoke binds the resulting port back from
# ``DevToolsActivePort`` line 1.
_BRAVE_SMOKE_CDP_PORT_ARG = "--remote-debugging-port=0"


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


def test_brave_smoke_exercises_prod_security_context() -> None:
    """D-PR-1: Brave smoke ``docker run`` must use the prod overlay's security context.

    The prod overlay (``x-operator-service-hardening`` in
    ``docker/docker-compose.yml``) sets ``security_opt: no-new-privileges:true``
    and inherits Docker's default seccomp profile. The Brave smoke
    previously passed ``--security-opt=seccomp=unconfined`` and omitted
    ``no-new-privileges:true``, so it ran under **weaker** constraints than
    the prod overlay it was meant to prove — a regression in either
    prod-hardening dimension would not surface here.

    The contract: every ``docker run`` invocation in the smoke must carry
    ``--security-opt=no-new-privileges:true`` and must NOT pass
    ``seccomp=unconfined`` (or any other seccomp override). The fix keeps
    ``cap_drop: ALL`` and the non-root uid, which were already correct.
    """
    # Locate the ``docker run`` arg list for the Brave smoke. The test
    # builds it inline rather than shelling out, so we read it from the
    # test module itself.
    source = Path(__file__).read_text(encoding="utf-8")
    # Find the ``run_args = [`` block inside the brave-smoke test.
    match = re.search(
        r"def test_brave_runs_in_hardened_container_without_no_sandbox.*?run_args\s*=\s*\[(.*?)\]",
        source,
        re.DOTALL,
    )
    assert match, "could not locate the Brave smoke run_args block"
    run_args_text = match.group(1)

    # The smoke must add ``--security-opt=no-new-privileges:true`` so the
    # container cannot regain privileges via setuid binaries (this is the
    # prod hardening control). ``--security-opt no-new-privileges`` is also
    # accepted as the YAML form, but the smoke passes flags directly.
    assert re.search(
        r"--security[-_]opt[= ]['\"]?no-new-privileges(?::true)?['\"]?",
        run_args_text,
    ), (
        "D-PR-1: Brave smoke must pass --security-opt=no-new-privileges:true "
        "so the container runs under the same hardening control as the prod "
        "overlay (x-operator-service-hardening). The smoke previously omitted "
        "this flag, silently relaxing the security context relative to prod."
    )

    # The smoke must NOT pass ``seccomp=unconfined`` (or any other seccomp
    # override) so it runs under Docker's default seccomp profile — the same
    # profile the prod overlay inherits.
    seccomp_overrides = re.findall(
        r"--security[-_]opt[= ]['\"]?seccomp[=]([^\s'\"]+)['\"]?",
        run_args_text,
    )
    assert not seccomp_overrides, (
        f"D-PR-1: Brave smoke must NOT pass a seccomp override; the prod "
        f"overlay inherits Docker's default seccomp profile and the smoke "
        f"must run under the same profile. Found overrides: {seccomp_overrides}"
    )

    # ``cap_drop: ALL`` and the non-root uid are still required.
    assert "--cap-drop=ALL" in run_args_text, (
        "Brave smoke must still drop all capabilities (cap_drop: ALL)"
    )
    assert "--user=10001:10001" in run_args_text, (
        "Brave smoke must still run as the gateway service account (uid 10001)"
    )


def test_brave_smoke_tempfile_cleanup_is_tolerated() -> None:
    """Docker-images fix: Brave smoke must not crash on tempdir cleanup under uid-10001 dirs.

    The W13.4b Brave smoke bind-mounts a tmp dir into the hardened
    container, which then creates ``segmentation_platform/`` and similar
    subdirectories owned by uid 10001 with mode 0700. Python 3.12's
    ``TemporaryDirectory`` cleanup walks the tree and calls ``os.chmod``
    from the onerror fallback (``_resetperms``); in some CI environments
    (notably the docker-images job on GHA ubuntu-latest, which runs as
    the unprivileged ``runner`` user) that ``chmod`` returns EPERM and
    the cleanup raises before the context exit returns control to the
    caller. The error propagates out of the test, which then fails the
    docker-images check even though the smoke itself was green.

    The fix is a defense-in-depth cleanup:

    1. Use ``tempfile.mkdtemp()`` directly instead of ``TemporaryDirectory``
       so the cleanup is fully under the test's control. The standard
       ``TemporaryDirectory`` finalizer (``weakref.finalize``) cannot be
       cleanly detached without changing the cleanup semantics we want.
    2. Wrap the test body in ``try: … finally:`` where the ``finally``
       runs ``docker rm -f`` (so uid-10001 is no longer holding file
       descriptors inside the bind-mount) **and** clears the bind-mount
       root with a one-shot ``alpine`` container running as ``--user=0``.
       Root inside the container has ``CAP_DAC_OVERRIDE`` and unlinks
       uid-10001 subdirs regardless of mode. The runner-owned mkdtemp
       root is then removed with ``shutil.rmtree(..., ignore_errors=True)``
       so any residual EPERM does not poison the test result.

    This test reads the source and asserts both invariants are present.
    """
    source = Path(__file__).read_text(encoding="utf-8")
    # Extract the function body for the smoke so we can assert on its
    # shape without re-running it (which requires a Docker daemon).
    # Match a line-anchored ``def test_brave_runs_in_hardened...`` so we
    # don't accidentally hit the search pattern inside the D-PR-1 test
    # (which references the smoke name as a literal string).
    match = re.search(
        r"^def test_brave_runs_in_hardened_container_without_no_sandbox.*?(?=^\ndef |\Z)",
        source,
        re.DOTALL | re.MULTILINE,
    )
    assert match, "could not locate the Brave smoke test body"
    body = match.group(0)

    # Invariant 1: the test creates the temp dir via ``tempfile.mkdtemp``
    # (NOT ``TemporaryDirectory``, whose 3.12 ``_resetperms`` chmod would
    # raise EPERM and fail the docker-images check even when the smoke
    # itself was green). Match the actual call, not comments — the latter
    # can mention ``mkdtemp`` without changing behavior.
    mkdtemp_call = re.search(r"tempfile\.mkdtemp\(([^)]*)\)", body)
    assert mkdtemp_call, (
        "Docker-images fix: Brave smoke must use tempfile.mkdtemp(...) so "
        "the test owns cleanup of the bind-mount (TemporaryDirectory's "
        "3.12 _resetperms chmod raises EPERM on uid-10001 subdirs and "
        "fails the docker-images check even on a green smoke)."
    )

    # Invariant 2: there must be at least one ``finally`` block that
    # runs ``docker rm -f`` (so uid-10001 is not still holding file
    # descriptors inside the bind-mount during the rmtree) AND clears
    # the bind-mount via a one-shot ``alpine`` container running as
    # ``--user=0`` so uid-10001 subdirs are unlinked regardless of
    # mode (the GHA runner cannot chmod or unlink those entries from
    # outside the container).
    finally_blocks = re.findall(r"\bfinally:\s*\n((?:[ \t].*\n?)+)", body, re.DOTALL)
    assert finally_blocks, "Brave smoke must have a finally block for cleanup"
    docker_rm_offset = -1
    rmtree_offset = -1
    alpine_offset = -1
    for finally_body in finally_blocks:
        if '"rm", "-f"' in finally_body:
            docker_rm_offset = finally_body.find('"rm", "-f"')
            rmtree_offset = finally_body.find("shutil.rmtree")
        if "alpine:" in finally_body:
            alpine_offset = finally_body.find("alpine:")
    assert docker_rm_offset != -1, (
        "Brave smoke finally block must docker rm -f the smoke container "
        "so uid-10001 is not holding file descriptors inside the bind "
        "mount during the rmtree"
    )
    assert rmtree_offset != -1, (
        "Brave smoke finally block must rmtree the bind-mount root before the test exits"
    )
    assert alpine_offset != -1, (
        "Docker-images fix: Brave smoke finally block must clear the "
        "bind-mount via a root container (alpine:) so uid-10001 subdirs "
        "are unlinked regardless of mode; the GHA runner cannot chmod "
        "or unlink those entries from outside the container."
    )
    assert docker_rm_offset < rmtree_offset, (
        "Brave smoke must stop the container (docker rm -f) BEFORE "
        "rmtree'ing the bind-mount root; otherwise uid-10001 may still "
        "hold descriptors that block the rmtree"
    )


def test_brave_runs_in_hardened_container_without_no_sandbox() -> None:
    """W13.4b / C8.1: dockerized Brave boots headless in a hardened container without ``--no-sandbox``.

    The static checks above prove the YAML config has no ``--no-sandbox``; this
    proves the dockerized browser actually starts in a hardened container
    matching the **production** security context (D-PR-1) when driven by the
    prod overlay's environment. CDP readiness is the contract: we launch real
    headless Brave (``--headless=new``) with ``--remote-debugging-port=0`` and a
    bind-mounted ``--user-data-dir``, then poll the user-data-dir for
    ``DevToolsActivePort`` (the file Chromium writes once the CDP endpoint is
    reachable; Chromium only writes this file for an auto-picked port, not for
    an explicit fixed port). The launch must succeed and the renderer must
    remain running long enough to write that file.

    The container hardening here matches the prod overlay (``x-operator-service-hardening``)
    exactly:

    - ``cap_drop: ALL`` — every capability dropped.
    - ``user=10001:10001`` — non-root (matches the gateway service account).
    - ``--security-opt no-new-privileges:true`` — matches the prod overlay
      (D-PR-1: was previously omitted, which meant the smoke silently ran
      with weaker constraints than prod).
    - Docker's **default** seccomp profile (D-PR-1: the previous version
      passed ``--security-opt seccomp=unconfined``, which lets Chromium's
      renderer do ``clone(CLONE_NEWPID|CLONE_NEWUSER)`` without a seccomp
      block but also disables a control the prod overlay inherits).

    Renderer-sandbox-vs-host-namespaces is a separate question: the GHA
    runner host disables ``apparmor_restrict_unprivileged_userns`` via a
    step in ``.github/workflows/docker.yml`` so Chromium can create the
    user namespace under the default seccomp policy. The smoke proves
    the C8.1 contract (env must not contain ``--no-sandbox``); the
    renderer-sandbox hardening is the prod overlay's job, not this test's.

    The image is env-overridable via ``SEVN_BROWSER_SMOKE_IMAGE`` (default
    ``sevn-gateway-browser:ci``; falls back to ``sevn-gateway-browser:local``).
    The CI ``docker-images`` job runs this test so a missing or broken image
    surfaces as a red check on the PR.

    Skip policy: skip ONLY when the Docker daemon is genuinely unreachable or
    when no acceptable image is present locally. A failed launch against a
    present image **fails** the test (no ``exit 0`` swallow) — the assertion
    message includes ``docker logs`` output so the actual renderer failure
    is visible.
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

    # The W13 hard-context container runs as uid 10001, so any subdir
    # Chromium creates under profile_host (e.g. ``segmentation_platform``)
    # is mode 0700 owned by uid 10001. The runner on GHA ubuntu-latest
    # (``runner`` user, not root) cannot chmod or unlink those entries, so
    # Python 3.12's ``TemporaryDirectory`` cleanup (which always attempts
    # ``_resetperms`` → ``chmod 0o700`` in ``onexc`` regardless of the
    # ``ignore_cleanup_errors`` flag — see cpython 3.12 ``Lib/tempfile.py``
    # ``_rmtree``) raises ``PermissionError`` and the test reports red on
    # the docker-images check even when the renderer behaved correctly.
    #
    # Cleanup strategy:
    #
    # 1. **Bypass the TemporaryDirectory cleanup for the bind-mount root.**
    #    Use ``tempfile.mkdtemp`` directly so we own the rmtree; the
    #    ``TemporaryDirectory`` finalizer (registered via ``weakref.finalize``
    #    on ``__init__``) cannot be detached cleanly without changing the
    #    cleanup semantics we want. Instead we rmtree the root ourselves
    #    with root-equivalent privileges (``sudo rm -rf``), then the parent
    #    mkdtemp root is empty and a final ``shutil.rmtree`` succeeds.
    # 2. **Use a side container to delete the bind-mount.** When sudo is
    #    unavailable, mount the bind-mount into a throwaway ``--user=0``
    #    ``alpine`` container and run ``rm -rf /data`` inside — root inside
    #    the container has ``CAP_DAC_OVERRIDE`` and clears uid-10001 dirs
    #    the runner cannot touch. This avoids relying on the GHA host's
    #    sudo (which can be disabled by org policy) and keeps the fix
    #    portable to local Colima where the host user already has root.
    # 3. **Defense-in-depth: ``ignore_cleanup_errors=True``** on the
    #    ``TemporaryDirectory`` so any remaining ``os.chmod`` EPERM during
    #    ``__exit__`` is swallowed (the directory is already empty).
    tmp_str = tempfile.mkdtemp(prefix="sevn-w13-brave-")
    profile_host = Path(tmp_str) / "profile"
    profile_host.mkdir(parents=True, exist_ok=True)
    # Bind the host tmp dir into the container at /tmp/w13-profile so we can
    # read DevToolsActivePort from the host without docker exec gymnastics.
    # The container runs as uid 10001; the dir must be writable by that uid.
    os.chmod(profile_host, 0o777)
    try:
        # Detached so the renderer keeps running while we poll. --rm cleans up
        # on stop; we also force-rm in the finally below for safety.
        run_args = [
            docker,
            "run",
            "-d",
            "--rm",
            "--name",
            _BRAVE_SMOKE_CONTAINER_NAME,
            # Container hardening: exercise the **production** security context
            # (D-PR-1). The prod overlay inherits ``no-new-privileges:true`` from
            # ``x-operator-service-hardening`` and uses Docker's default seccomp
            # profile — the smoke must run under the same constraints so a
            # regression in either dimension surfaces here as a red check, not
            # a silent "works under relaxed flags" false negative on the
            # operator's machine. Chromium's renderer sandbox then runs under
            # the default seccomp policy the prod overlay will hand it.
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges:true",
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
            # Override the gateway entrypoint so the smoke does not try to
            # bootstrap /operator/workspace/sevn.json (we are running Brave
            # directly, not the gateway). Skipping the bootstrap keeps the
            # contract narrow: "Brave itself boots under the hardened flags".
            "--entrypoint",
            "sh",
            image,
            "-c",
            # Refuse --no-sandbox if anything in the env sneaks it in. The
            # assertion below verifies the marker is absent, but failing fast
            # surfaces the regression immediately.
            'case " :${SEVN_BROWSER_EXTRA_ARGS}:" in '
            "*--no-sandbox*) echo BAD_ENV; exit 1;; "
            "esac; "
            "exec /usr/bin/brave-browser "
            "--headless=new "
            f"{_BRAVE_SMOKE_CDP_PORT_ARG} "
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
                timeout=30,
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
            # "<port>\n<host>\n" once the remote-debugging listener is up
            # (only when --remote-debugging-port=0 lets Chromium pick the
            # port — a fixed-port listener does not write this file).
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
                # renderer never came up. Capture ``docker logs`` so a future
                # failure surfaces the actual Brave stderr (the renderer abort
                # is not visible in ``docker run -d``'s own stderr).
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
                if not state.startswith("true "):
                    # ``docker logs`` has no ``--no-color`` flag (the
                    # standalone ``docker logs`` CLI only accepts
                    # ``--details``, ``--follow``, ``--since``,
                    # ``--tail``, ``--timestamps``, ``--until``; the
                    # ``--no-color`` flag exists only on the
                    # ``docker compose logs`` subcommand). On a freshly
                    # rebuilt GHA ubuntu-latest image (Docker CLI 27+)
                    # the bogus flag raises "unknown flag: --no-color"
                    # and the diagnostic masks the actual renderer abort
                    # we wanted to see — a green smoke was turning red
                    # on the docker-images check for that reason alone
                    # (PR #243-A verify run 31270304442). Drop the flag
                    # so the renderer stderr reaches pytest.fail.
                    logs = subprocess.run(
                        [
                            docker,
                            "logs",
                            "--tail=80",
                            _BRAVE_SMOKE_CONTAINER_NAME,
                        ],
                        check=False,
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )  # nosec B603
                    pytest.fail(
                        "Brave exited before DevToolsActivePort appeared "
                        f"(state={state!r}); renderer logs:\n"
                        f"{(logs.stdout or '').strip()}\n"
                        f"{(logs.stderr or '').strip()}"
                    )
                time.sleep(_BRAVE_SMOKE_CDP_POLL_INTERVAL_S)

            assert devtools_port is not None, (
                f"DevToolsActivePort never appeared in {profile_host} within "
                f"{_BRAVE_SMOKE_LAUNCH_TIMEOUT_S:.0f}s; Brave launched but did "
                "not become CDP-ready. Renderer likely needs --no-sandbox or "
                "kernel user namespaces to start."
            )

            # Confirm the CDP endpoint actually answers. The renderer writes
            # ``DevToolsActivePort`` as soon as the listener binds the socket;
            # the listener only answers HTTP **after** the browser process has
            # finished initialising its handlers. Probing
            # ``/json/version`` proves both — a half-initialised listener that
            # bound the port but never reached the HTTP handler will fail this.
            # We curl from inside the container (127.0.0.1 inside its network
            # namespace) so we do not need to publish the port.
            cdp_probe = subprocess.run(
                [
                    docker,
                    "exec",
                    _BRAVE_SMOKE_CONTAINER_NAME,
                    "sh",
                    "-c",
                    f"curl -fsS --max-time 5 http://127.0.0.1:{devtools_port}/json/version",
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=15,
            )  # nosec B603
            assert cdp_probe.returncode == 0, (
                f"CDP listener on 127.0.0.1:{devtools_port} never answered "
                f"/json/version (renderer wrote the port file but did not reach "
                f"HTTP readiness). stderr: "
                f"{(cdp_probe.stderr or '').strip()}"
            )
            cdp_doc = json.loads(cdp_probe.stdout)
            assert isinstance(cdp_doc, dict), f"CDP /json/version returned non-object: {cdp_doc!r}"
            assert cdp_doc.get("Browser"), f"CDP /json/version missing Browser key: {cdp_doc!r}"

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
            # Belt-and-suspenders cleanup of the bind-mount root. With the
            # container stopped, uid-10001 is no longer holding any file
            # descriptors open inside profile_host. The subdirs are still
            # mode 0700 owned by uid 10001; the GHA ``runner`` user (and any
            # unprivileged CI user) cannot chmod / unlink them, which is
            # what was tripping Python 3.12's ``TemporaryDirectory``
            # ``_resetperms`` chmod into EPERM.
            #
            # We work around that by deleting the bind-mount's contents via
            # a one-shot root container (the throwaway ``alpine`` image is
            # already pulled by every GHA runner). The bind-mount root is
            # removed by root inside the container, so uid-10001 subdirs are
            # unlinked regardless of their perms. After the bind-mount is
            # empty, a regular ``shutil.rmtree`` of ``profile_host`` succeeds
            # because the runner owns the (now-empty) dir. Finally the
            # mkdtemp root (``tmp_str``) is removed too; if any leftover
            # EPERM survives it does not affect the test result.
            bind_profile = str(profile_host)
            subprocess.run(  # nosec B603
                [
                    docker,
                    "run",
                    "--rm",
                    "--user=0:0",
                    "-v",
                    f"{bind_profile}:/data:rw",
                    "alpine:3.20",
                    "sh",
                    "-c",
                    "rm -rf /data/* /data/.[!.]* 2>/dev/null; chmod -R u+rwX /data 2>/dev/null; true",
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
            with contextlib.suppress(OSError):
                shutil.rmtree(profile_host, ignore_errors=True)
            # Mkdtemp cleanup — the parent ``tmp_str`` should now be empty
            # after the bind-mount rmtree above; ``ignore_errors`` absorbs
            # any remaining EPERM so the test result is not poisoned.
            with contextlib.suppress(OSError):
                shutil.rmtree(tmp_str, ignore_errors=True)
    finally:
        # Belt-and-suspenders outer cleanup: if the inner ``try`` raised
        # before its own ``finally`` could run (or between the docker rm
        # and the rmtree), we still need to free the bind-mount and the
        # mkdtemp root. The same root-container trick is used so uid-10001
        # subdirs do not poison a subsequent rerun or the GHA runner's /tmp.
        if profile_host.exists():
            subprocess.run(  # nosec B603
                [
                    docker,
                    "run",
                    "--rm",
                    "--user=0:0",
                    "-v",
                    f"{profile_host}:/data:rw",
                    "alpine:3.20",
                    "sh",
                    "-c",
                    "rm -rf /data/* /data/.[!.]* 2>/dev/null; chmod -R u+rwX /data 2>/dev/null; true",
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
            with contextlib.suppress(OSError):
                shutil.rmtree(profile_host, ignore_errors=True)
        with contextlib.suppress(OSError):
            shutil.rmtree(tmp_str, ignore_errors=True)


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


def test_operator_perms_browser_state_has_independent_marker() -> None:
    """D-PR-2: ``/browser-profiles`` lives on its own volume and needs its own marker.

    ``sevn-browser-state`` is a separate volume from ``sevn-state``: the
    operator may legitimately recreate one without the other (e.g.
    ``docker volume rm sevn-browser-state`` to wipe a stuck Chromium
    profile). If the perms marker lived only on ``sevn-state`` and gated
    the ``/browser-profiles`` chown pass, then recreating only the
    browser volume would leave its mount owned by the docker default
    uid (root), and the marker branch would silently skip the chown.

    The contract: the chown over ``/browser-profiles`` is gated by a
    marker that lives on ``sevn-state`` (``/operator/.sevn/...``) so it
    survives a ``sevn-browser-state`` recreation, but the marker is
    specific to the browser volume (not the global workspace marker).
    """
    command = _service_command_text(_BASE_COMPOSE, "sevn-operator-perms")
    # The browser chown path needs a dedicated marker that survives
    # recreation of ``sevn-browser-state``. We don't pin the exact
    # filename (the implementation may evolve) but it must be a
    # distinct token that is NOT the global ``perms-v1`` marker.
    assert _PERMS_MARKER in command, f"global marker {_PERMS_MARKER} missing"

    # Locate the /browser-profiles chown block, then walk backward to
    # the nearest ``[ ! -f <marker> ]`` guard. The guard that the browser
    # chown actually falls under must use a marker distinct from the
    # global workspace marker.
    browser_chown_block = re.search(
        r"find\s+/browser-profiles\b",
        command,
    )
    assert browser_chown_block, (
        "sevn-operator-perms must still chown /browser-profiles (C9.2); "
        "the previous block was removed and not replaced with a dedicated "
        "browser-volume normalization pass"
    )
    preceding = command[: browser_chown_block.start()]
    guard_match = re.findall(
        r"\[ ! -f (/operator/\.sevn/[^\s\]]+)\s*\]",
        preceding,
    )
    assert guard_match, (
        "sevn-operator-perms must guard the /browser-profiles chown with "
        "its own marker check ([ ! -f /operator/.sevn/<browser-marker> ])"
    )
    browser_marker = guard_match[-1]
    assert browser_marker != _PERMS_MARKER, (
        f"D-PR-2: the browser chown is gated by the global {_PERMS_MARKER} "
        "marker, which lives on sevn-state. If only the sevn-browser-state "
        "volume is recreated, the global marker survives and the browser "
        "chown is skipped. Use a dedicated marker so the browser volume's "
        "ownership is normalized independently."
    )

    # The browser marker must be created inside the gated branch so a
    # cold boot writes it before any subsequent run can skip.
    create_pattern = re.search(
        rf"printf[^\n]*>\s*{re.escape(browser_marker)}",
        command,
    )
    assert create_pattern, (
        f"sevn-operator-perms must create the browser marker "
        f"({browser_marker}) inside its own gated branch, not skip it on "
        "a cold boot"
    )


def test_ci_init_has_no_unconditional_chown() -> None:
    """W13.5 / C9.4: ``sevn-ci-init`` must not run unconditional ``chown -R`` on /operator."""
    command = _service_command_text(_CI_COMPOSE, "sevn-ci-init")
    unconditional = re.findall(r"chown\s+-R\s+10001:10001\s+/[^\s;]+", command)
    assert unconditional == [], (
        f"sevn-ci-init still runs unconditional chown -R: {unconditional}; "
        "apply scoped+marker treatment or document intentional CI divergence"
    )


def test_ci_init_marker_check_runs_before_seed_copy() -> None:
    """D-PR-3: ``sevn-ci-init`` must gate the seed copy behind the marker check.

    On a warm boot the persistent ``sevn-ci-workspace`` volume is already
    populated and already owned by uid 10001. The previous init ran
    ``cp -a /seed/sevn.json /operator/workspace/sevn.json`` (and the same
    for ``/seed/.sevn``) **before** checking for the
    ``/operator/.sevn/perms-v1`` marker. ``cp -a`` reseeds the workspace
    from the host fixture, the host fixture is owned by the build-time
    root user, and the marker check then sees the marker and skips
    normalization — leaving the gateway container unable to read its
    own ``sevn.json``.

    The fix is to invert the order: check the marker first, and only
    seed (with ``cp -an`` so an existing volume is never clobbered) on
    cold boots. Warm boots still chown any drift that has accumulated
    since the previous run.
    """
    command = _service_command_text(_CI_COMPOSE, "sevn-ci-init")
    assert _PERMS_MARKER in command, f"marker {_PERMS_MARKER} missing from sevn-ci-init"

    # Locate every ``cp -a[n]`` that copies a seed file/dir from /seed.
    seed_copy_re = re.compile(r"\bcp\s+-a[n]?\s+/seed/\S+\s+/\S+")
    seed_copies = seed_copy_re.findall(command)
    assert seed_copies, (
        "sevn-ci-init no longer seeds the workspace from /seed; if the seed "
        "is genuinely optional, document the contract in a comment instead"
    )

    # Find the byte-offset of the marker check and the byte-offset of each
    # seed copy. The marker check must precede every seed copy so a warm
    # boot never reseeds the volume before normalization is decided.
    marker_match = re.search(rf"\[ ! -f {_PERMS_MARKER.replace('.', r'\.')}\s*\]", command)
    assert marker_match, (
        "sevn-ci-init must guard the cold-boot path with [ ! -f /operator/.sevn/perms-v1 ]"
    )
    marker_offset = marker_match.start()
    for copy in seed_copies:
        copy_offset = command.find(copy)
        assert copy_offset > marker_offset, (
            f"D-PR-3: seed copy {copy!r} appears before the marker check "
            f"({copy_offset} < {marker_offset}); cp -a would reseed the "
            "workspace with host/root ownership and the marker branch "
            "would then skip normalization. Move the seed copy inside "
            "the marker-gated cold-boot branch (or use cp -an so warm "
            "boots do not clobber the persistent volume)."
        )

    # Warm-boot safety net: even when the marker is present, the init must
    # still chown any drift (the persistent volume could have been mounted
    # under a different uid via a host bind-mount, etc.). The shape we
    # require is a ``find ... ! -user 10001 -exec chown 10001:10001 {} +``
    # scoped to a single app-owned subdir (no ``chown -R``).
    scoped_drift_chown = re.search(
        r"find\s+/operator/workspace(?:\S*)\s+!\s+-user\s+10001\s+-exec\s+chown\s+10001:10001",
        command,
    )
    assert scoped_drift_chown, (
        "sevn-ci-init must keep a scoped drift-recovery chown (find ... "
        "! -user 10001 -exec chown 10001:10001 {}) on warm boots, so a "
        "host bind-mount that landed a non-10001 owner is still "
        "normalized without reseeding the workspace"
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
