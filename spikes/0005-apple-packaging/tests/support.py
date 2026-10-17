"""Locate the built SevnSpike app and read its packaging contracts."""

from __future__ import annotations

import http.client
import json
import os
import plistlib
import shutil
import subprocess
import time
from pathlib import Path
from typing import cast

SPIKE_ROOT = Path(__file__).resolve().parents[1]
BUNDLE_ID = "bot.sevn.spike"
APP_DISPLAY_NAME = "SevnSpike"
LAUNCH_AGENT_LABEL = "com.sevn.spike.host"
LAUNCH_AGENT_PLIST = "com.sevn.spike.host.plist"
BUNDLE_PROGRAM = "Contents/MacOS/sevn-host"
PYTHON_RELATIVE = Path("Contents/Resources/python/bin/python3.13")
SITE_RELATIVE = Path("Contents/Resources/site")
HOST_RELATIVE = Path("Contents/MacOS/sevn-host")
MAIN_EXECUTABLE_RELATIVE = Path("Contents/MacOS/SevnSpike")
PLIST_RELATIVE = Path("Contents/Library/LaunchAgents") / LAUNCH_AGENT_PLIST
HEALTH_TIMEOUT_S = 10.0
REQUIRED_GATES = ("developer-id", "notary-profile", "clean-account", "tcc-prompts")
TCC_PATHS = ("app_child", "launch_agent")
_SKIP_BINARIES = frozenset({"SevnSpike", "sevn-host"})
_HELPER_DIRS = (Path("Contents/MacOS"), Path("Contents/Helpers"))
_MACHO_MAGICS = frozenset(
    {
        b"\xfe\xed\xfa\xce",
        b"\xce\xfa\xed\xfe",
        b"\xfe\xed\xfa\xcf",
        b"\xcf\xfa\xed\xfe",
        b"\xca\xfe\xba\xbe",
        b"\xbe\xba\xfe\xca",
    }
)
_DEFAULT_APP = SPIKE_ROOT / "app" / "build" / "Build" / "Products" / "Release" / "SevnSpike.app"


def sign_identity() -> str:
    return os.environ.get("SEVN_SIGN_IDENTITY", "").strip()


def notary_profile() -> str:
    return os.environ.get("SEVN_NOTARY_PROFILE", "").strip()


def require_app() -> Path:
    app = locate_app()
    if not app.is_dir():
        raise AssertionError(
            "built SevnSpike.app not found at "
            f"{app}. Build with -derivedDataPath spikes/0005-apple-packaging/app/build "
            "or set SEVN_SPIKE_APP."
        )
    return app


def locate_app() -> Path:
    override = os.environ.get("SEVN_SPIKE_APP", "").strip()
    if override:
        return Path(override)
    candidates: list[Path] = []
    for root in (SPIKE_ROOT / "app" / "build", SPIKE_ROOT / "build", SPIKE_ROOT / "dist"):
        if root.exists():
            candidates.extend(path for path in root.rglob("SevnSpike.app") if path.is_dir())
    derived = Path.home() / "Library" / "Developer" / "Xcode" / "DerivedData"
    if derived.is_dir():
        candidates.extend(
            path
            for path in derived.glob("SevnSpike-*/Build/Products/*/*.app")
            if path.name == "SevnSpike.app" and path.is_dir()
        )
    if not candidates:
        return _DEFAULT_APP
    return min(candidates, key=_app_rank)


def launch_agent_plist(app: Path) -> dict[str, object]:
    return load_plist(app / PLIST_RELATIVE)


def loopback_port(app: Path) -> int:
    data = launch_agent_plist(app)
    env = as_dict(
        data.get("EnvironmentVariables"),
        "launch agent EnvironmentVariables",
    )
    raw_port = env.get("SEVN_SPIKE_PORT")
    if isinstance(raw_port, str) and raw_port.isdigit():
        port = int(raw_port)
    elif isinstance(raw_port, int) and not isinstance(raw_port, bool):
        port = raw_port
    else:
        raise AssertionError("SEVN_SPIKE_PORT must be an integer loopback port")
    if not 1 <= port <= 65535:
        raise AssertionError(f"SEVN_SPIKE_PORT out of range: {port}")
    return port


def health_status(port: int) -> int | None:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
    try:
        connection.request("GET", "/health")
        response = connection.getresponse()
        response.read()
    except (OSError, http.client.HTTPException):
        return None
    else:
        return response.status
    finally:
        connection.close()


def wait_for_health(port: int, *, timeout_s: float) -> int | None:
    deadline = time.monotonic() + timeout_s
    status: int | None = None
    while time.monotonic() < deadline:
        status = health_status(port)
        if status == 200:
            return status
        time.sleep(0.25)
    return status


def wait_until_health_stops(port: int, *, timeout_s: float) -> int | None:
    deadline = time.monotonic() + timeout_s
    status: int | None = 200
    while time.monotonic() < deadline:
        status = health_status(port)
        if status != 200:
            return status
        time.sleep(0.25)
    return status


def embedded_python_env() -> dict[str, str]:
    env = dict(os.environ)
    for key in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "VIRTUAL_ENV"):
        env.pop(key, None)
    env["PYTHONNOUSERSITE"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def helper_output(app: Path, flag: str, *, timeout: float) -> subprocess.CompletedProcess[str]:
    attempts: list[str] = []
    for path in helper_candidates(app):
        try:
            result = run([str(path), flag], timeout=timeout)
        except subprocess.TimeoutExpired:
            attempts.append(f"{path.name} {flag} timed out")
            continue
        if result.returncode == 0:
            return result
        attempts.append(f"{path.name} rc={result.returncode}")
    if attempts:
        detail = "; ".join(attempts)
    else:
        detail = "no executable under Contents/MacOS or Contents/Helpers"
    raise AssertionError(f"no helper answered {flag} with exit 0 ({detail})")


def parse_preflight(stdout: str) -> tuple[bool, bool]:
    values: dict[str, bool] = {}
    for line in stdout.splitlines():
        if "=" not in line:
            continue
        key, raw = line.split("=", 1)
        normalized = raw.strip().lower()
        if key.strip() in {"screen_capture", "accessibility"} and normalized in {"true", "false"}:
            values[key.strip()] = normalized == "true"
    if "screen_capture" not in values or "accessibility" not in values:
        raise AssertionError(
            "helper --probe-tcc must print screen_capture=<true|false> and "
            f"accessibility=<true|false>; got {clip(stdout)!r}"
        )
    return values["screen_capture"], values["accessibility"]


def load_json_object(path: Path) -> dict[str, object]:
    if not path.is_file():
        raise AssertionError(f"missing {path.relative_to(SPIKE_ROOT)}")
    parsed: object = json.loads(path.read_text(encoding="utf-8"))
    return as_dict(parsed, path.name)


def assert_tcc_paths(payload: dict[str, object], *, require_pass: bool) -> None:
    paths = as_dict(payload.get("paths"), "tcc paths")
    for name in TCC_PATHS:
        row = as_dict(paths.get(name), f"tcc path {name}")
        if require_pass and row.get("pass") is not True:
            raise AssertionError(f"tcc path {name} must pass")
        if row.get("prompt_name") != APP_DISPLAY_NAME:
            raise AssertionError(f"tcc path {name} prompt must name {APP_DISPLAY_NAME}")
        if row.get("bundle_id") != BUNDLE_ID:
            raise AssertionError(f"tcc path {name} bundle_id must be {BUNDLE_ID}")
        excerpt = row.get("log_excerpt")
        if not isinstance(excerpt, str) or BUNDLE_ID not in excerpt:
            raise AssertionError(f"tcc path {name} log_excerpt must contain {BUNDLE_ID}")


def as_dict(value: object, label: str) -> dict[str, object]:
    if not _is_dict(value):
        raise AssertionError(f"{label} must be an object")
    raw = cast("dict[object, object]", value)
    result: dict[str, object] = {}
    for key, item in raw.items():
        if not isinstance(key, str):
            raise AssertionError(f"{label} keys must be strings")
        result[key] = item
    return result


def as_list(value: object, label: str) -> list[object]:
    if not _is_list(value):
        raise AssertionError(f"{label} must be a list")
    return list(cast("list[object]", value))


def _is_dict(value: object) -> bool:
    return isinstance(value, dict)


def _is_list(value: object) -> bool:
    return isinstance(value, list)


def iter_macho(app: Path) -> list[Path]:
    root = app.resolve()
    seen: set[Path] = set()
    found: list[Path] = []
    for path in app.rglob("*"):
        if not path.is_file():
            continue
        resolved = path.resolve()
        if resolved in seen or not resolved.is_relative_to(root):
            continue
        try:
            with resolved.open("rb") as handle:
                magic = handle.read(4)
        except OSError:
            continue
        if magic not in _MACHO_MAGICS:
            continue
        seen.add(resolved)
        found.append(resolved)
    return found


def team_identifier(path: Path) -> str:
    info = run([tool("codesign"), "-dv", "--verbose=4", str(path)], timeout=60)
    text = info.stderr + info.stdout
    if info.returncode != 0:
        raise AssertionError(f"codesign -dv failed for {path}: {clip(text)}")
    for line in text.splitlines():
        if line.startswith("TeamIdentifier="):
            return line.split("=", 1)[1].strip()
    raise AssertionError(f"no TeamIdentifier for {path}: {clip(text)}")


def tool(name: str) -> str:
    found = shutil.which(name)
    if found is None:
        raise AssertionError(f"{name} is not on PATH")
    return found


def run(
    argv: list[str],
    *,
    timeout: float,
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        argv,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
        cwd=cwd,
    )


def clip(text: str, limit: int = 2000) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "..."


def load_plist(path: Path) -> dict[str, object]:
    if not path.is_file():
        raise AssertionError(f"missing {path}")
    with path.open("rb") as handle:
        parsed: object = plistlib.load(handle)
    return as_dict(parsed, path.name)


def helper_candidates(app: Path) -> list[Path]:
    found: list[Path] = []
    for relative in _HELPER_DIRS:
        directory = app / relative
        if not directory.is_dir():
            continue
        for path in sorted(directory.iterdir()):
            if path.name in _SKIP_BINARIES or path.suffix in {".dylib", ".so", ".py"}:
                continue
            if path.is_file() and os.access(path, os.X_OK):
                found.append(path)
    return found


def _app_rank(path: Path) -> tuple[int, int, str]:
    location = 0 if SPIKE_ROOT in path.parents else 1
    parts = path.parts
    if "Release" in parts:
        config = 0
    elif "Debug" in parts:
        config = 1
    else:
        config = 2
    return (location, config, str(path))
