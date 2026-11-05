"""Image, fly skeleton, and CI workflow (D19, D20)."""

from __future__ import annotations

import json
import re
import subprocess
import tomllib

import pytest
from support.repo import repo_root


def test_dockerfile_user_and_healthcheck() -> None:
    text = (repo_root() / "deploy" / "Dockerfile").read_text(encoding="utf-8")
    users = re.findall(r"(?m)^USER\s+(\S+)", text)
    assert users
    assert users[-1] not in {"root", "0", "0:0"}
    health = re.search(r"(?ms)^HEALTHCHECK\b.*?(?=^(?:[A-Z]+)\b|\Z)", text)
    assert health is not None
    block = health.group(0).replace("\\\n", " ")
    assert "curl" in block
    assert "/health" in block
    assert re.search(r"(?m)^ENV\s+SEVN_HOME=/data\b", text)
    assert re.search(r"(?m)^VOLUME\s+/data\b", text)
    assert "--allow-remote-bind" in text


def test_fly_toml_has_volume_and_health() -> None:
    data = tomllib.loads((repo_root() / "deploy" / "fly.toml").read_text(encoding="utf-8"))
    mounts = data["mounts"]
    if isinstance(mounts, dict):
        assert mounts["destination"] == "/data"
    else:
        assert any(item["destination"] == "/data" for item in mounts)
    checks = data["http_service"]["checks"]
    assert any(item.get("path") == "/health" for item in checks)


def test_ci_workflow_runs_make_ci_without_secrets() -> None:
    text = (repo_root() / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "ubuntu-latest" in text
    assert "make ci" in text
    assert "pull_request" in text
    assert re.search(r"branches:[^\n]*main|-\s+[\"']?main[\"']?", text)
    assert "permissions:" in text
    assert re.search(r"contents:\s*read", text)
    assert "${{ secrets" not in text


# --- plan 0025: Linux images (D8, D9, W5) ------------------------------------

_RUNTIMES_DIR = "/opt/sevn/runtimes"
_CMD = '["sevn", "serve", "--host", "0.0.0.0", "--port", "8787", "--allow-remote-bind"]'
_HEALTH = "CMD curl -fsS http://127.0.0.1:8787/health || exit 1"
_IMAGES = [
    pytest.param("Dockerfile", id="debian"),
    pytest.param("Dockerfile.ubuntu", id="ubuntu"),
]


def _dockerfile(name: str) -> str:
    return (repo_root() / "deploy" / name).read_text(encoding="utf-8")


def _logical_lines(text: str) -> list[str]:
    """Instructions with continuations joined and comments dropped."""
    joined = re.sub(r"\\\n", " ", text)
    return [
        line.strip()
        for line in joined.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def _stages(text: str) -> list[tuple[str, list[str]]]:
    """``[(FROM line, instructions)]`` per build stage."""
    stages: list[tuple[str, list[str]]] = []
    for line in _logical_lines(text):
        if re.match(r"(?i)^FROM\s", line):
            stages.append((line, []))
        elif stages:
            stages[-1][1].append(line)
    return stages


def _final(text: str) -> tuple[str, list[str]]:
    stages = _stages(text)
    assert stages, "no FROM"
    return stages[-1]


def _installed_packages(lines: list[str]) -> set[str]:
    packages: set[str] = set()
    for line in lines:
        for match in re.finditer(r"apt-get\s+install\s+([^&;|]+)", line):
            packages.update(word for word in match.group(1).split() if not word.startswith("-"))
    return packages


@pytest.mark.parametrize("name", _IMAGES)
def test_images_install_bubblewrap_git_and_certificates(name: str) -> None:
    _from, lines = _final(_dockerfile(name))
    packages = _installed_packages(lines)
    assert {"bubblewrap", "git", "ca-certificates", "curl"} <= packages, packages


@pytest.mark.parametrize("name", _IMAGES)
def test_runtimes_stage_writes_opt_sevn_runtimes(name: str) -> None:
    stages = _stages(_dockerfile(name))
    named = [(head, lines) for head, lines in stages if re.search(r"(?i)\sAS\s+runtimes\s*$", head)]
    assert len(named) == 1, [head for head, _lines in stages]
    _head, lines = named[0]
    body = "\n".join(lines)
    assert "sevn runtimes install --all" in body
    assert re.search(rf"SEVN_RUNTIMES_DIR=[\"']?{re.escape(_RUNTIMES_DIR)}\b", body)

    _final_from, final = _final(_dockerfile(name))
    copies = [line for line in final if re.match(r"(?i)^COPY\s+(--\S+\s+)*--from=runtimes\b", line)]
    assert copies, final
    assert all(_RUNTIMES_DIR in line for line in copies), copies
    assert re.search(
        rf"(?m)^ENV\s+.*SEVN_RUNTIMES_DIR=[\"']?{re.escape(_RUNTIMES_DIR)}\b", "\n".join(final)
    )


@pytest.mark.parametrize("name", _IMAGES)
def test_runtimes_are_read_only_to_the_sevn_user(name: str) -> None:
    _from, final = _final(_dockerfile(name))
    assert any("--from=runtimes" in line for line in final), final
    for line in final:
        if "--from=runtimes" in line:
            assert "--chown" not in line, line
        if re.match(r"(?i)^RUN\s", line) and "chown" in line:
            assert "/opt/sevn" not in line, line


@pytest.mark.parametrize("name", _IMAGES)
def test_image_keeps_user_volume_healthcheck_and_cmd(name: str) -> None:
    text = _dockerfile(name)
    _from, final = _final(text)
    body = "\n".join(final)
    assert re.search(r"useradd\b[^\n]*--uid\s+10001\b", body), "uid 10001"
    assert re.search(r"--home-dir\s+/home/sevn\b", body)
    users = [line.split()[1] for line in final if re.match(r"(?i)^USER\s", line)]
    assert users and users[-1] == "sevn"
    assert re.search(r"(?m)^ENV\s+SEVN_HOME=/data\b", body)
    assert re.search(r"(?m)^VOLUME\s+/data\b", body)
    health = [line for line in final if re.match(r"(?i)^HEALTHCHECK\s", line)]
    assert len(health) == 1
    assert _HEALTH in re.sub(r"\s+", " ", health[0])
    cmds = [line for line in final if re.match(r"(?i)^CMD\s", line)]
    assert cmds[-1] == f"CMD {_CMD}"


def test_ubuntu_image_is_ubuntu_24_04_with_uv_python() -> None:
    text = _dockerfile("Dockerfile.ubuntu")
    head, final = _final(text)
    assert re.match(r"(?i)^FROM\s+ubuntu:24\.04\b", head), head
    assert re.search(r"uv\s+python\s+install\s+[^\n]*3\.13", "\n".join(final))


@pytest.mark.parametrize(
    ("target", "dockerfile", "tag"),
    [("image", "deploy/Dockerfile", None), ("image-ubuntu", "deploy/Dockerfile.ubuntu", "-ubuntu")],
)
def test_make_image_targets(target: str, dockerfile: str, tag: str | None) -> None:
    completed = subprocess.run(  # noqa: S603 — make -n on a fixed Makefile target, no shell
        ["make", "-n", target],  # noqa: S607 — the repo Makefile target CI runs
        cwd=repo_root(),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "docker build" in completed.stdout
    assert dockerfile in completed.stdout
    if tag is not None:
        assert tag in completed.stdout


@pytest.mark.live
@pytest.mark.parametrize("name", ["Dockerfile", "Dockerfile.ubuntu"])
def test_live_image_builds_and_serves_health(name: str) -> None:
    import shutil
    import time
    import urllib.request

    if shutil.which("docker") is None:
        pytest.skip("docker is not installed")
    tag = f"sevn-test:{name.lower().replace('.', '-')}"
    root = repo_root()
    subprocess.run(  # noqa: S603 — builds a repo Dockerfile under a test tag
        ["docker", "build", "-f", f"deploy/{name}", "-t", tag, "."],  # noqa: S607 — docker from PATH, as the Makefile and CI run it
        cwd=root,
        check=True,
        timeout=3600,
    )
    run = subprocess.run(  # noqa: S603 — runs the image this test built
        [  # noqa: S607 — docker from PATH, as the Makefile and CI run it
            "docker",
            "run",
            "-d",
            "--rm",
            "-p",
            "127.0.0.1::8787",
            "-e",
            "SEVN_ALLOWED_HOSTS=127.0.0.1:8787",
            tag,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    container = run.stdout.strip()
    try:
        port = (
            subprocess.run(  # noqa: S603 — asks about the container this test started
                ["docker", "port", container, "8787/tcp"],  # noqa: S607 — docker from PATH, as the Makefile and CI run it
                capture_output=True,
                text=True,
                check=True,
            )
            .stdout.strip()
            .rsplit(":", 1)[1]
        )
        deadline = time.monotonic() + 90
        healthy = False
        while time.monotonic() < deadline and not healthy:
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/health", timeout=2
                ) as response:
                    healthy = response.status == 200
            except OSError:
                time.sleep(1)
        assert healthy
        listed = subprocess.run(  # noqa: S603 — execs in the container this test started
            ["docker", "exec", container, "sevn", "runtimes", "list", "--json"],  # noqa: S607 — docker from PATH, as the Makefile and CI run it
            capture_output=True,
            text=True,
            check=True,
        )
        body = json.loads(listed.stdout)
        for runtime in ("claude", "opencode", "codex", "cursor-agent"):
            assert body[runtime]["used"] == "managed", runtime
    finally:
        subprocess.run(["docker", "rm", "-f", "-v", container], check=False)  # noqa: S603, S607 — removes the container this test started, docker from PATH
