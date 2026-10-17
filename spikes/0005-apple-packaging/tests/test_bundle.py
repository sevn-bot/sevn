"""Built-app layout and launch-agent checks. Green after W2."""

from __future__ import annotations

from pathlib import Path

import pytest

from support import (
    APP_DISPLAY_NAME,
    BUNDLE_ID,
    BUNDLE_PROGRAM,
    HEALTH_TIMEOUT_S,
    HOST_RELATIVE,
    LAUNCH_AGENT_LABEL,
    MAIN_EXECUTABLE_RELATIVE,
    PLIST_RELATIVE,
    PYTHON_RELATIVE,
    SITE_RELATIVE,
    clip,
    embedded_python_env,
    helper_output,
    launch_agent_plist,
    load_plist,
    loopback_port,
    require_app,
    run,
    wait_for_health,
    wait_until_health_stops,
)


@pytest.mark.xfail(reason="green after W2: bundle layout", strict=False)
def test_bundle_layout() -> None:
    app = require_app()
    python = app / PYTHON_RELATIVE
    host = app / HOST_RELATIVE
    plist = app / PLIST_RELATIVE
    assert python.is_file()
    assert host.is_file()
    assert plist.is_file()
    assert (app / MAIN_EXECUTABLE_RELATIVE).is_file()
    assert (app / SITE_RELATIVE).is_dir()


@pytest.mark.xfail(reason="green after W2: launch agent plist", strict=False)
def test_launch_agent_plist_points_at_host() -> None:
    app = require_app()
    plist = launch_agent_plist(app)
    assert plist.get("Label") == LAUNCH_AGENT_LABEL
    assert plist.get("BundleProgram") == BUNDLE_PROGRAM


@pytest.mark.xfail(reason="green after W2: bundle identity", strict=False)
def test_bundle_identity() -> None:
    app = require_app()
    info = load_plist(app / "Contents" / "Info.plist")
    assert info.get("CFBundleIdentifier") == BUNDLE_ID
    assert info.get("CFBundleDisplayName") == APP_DISPLAY_NAME


@pytest.mark.xfail(reason="green after W2: embedded python prints 3.13", strict=False)
def test_embedded_python_runs() -> None:
    app = require_app()
    python = app / PYTHON_RELATIVE
    python_root = (app / "Contents" / "Resources" / "python").resolve()
    completed = run(
        [
            str(python),
            "-c",
            "import sys; print(sys.executable); "
            "print(f'{sys.version_info[0]}.{sys.version_info[1]}')",
        ],
        timeout=30,
        env=embedded_python_env(),
    )
    assert completed.returncode == 0, clip(completed.stderr)
    lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    assert len(lines) == 2, clip(completed.stdout)
    executable, version = lines
    assert version == "3.13"
    resolved = Path(executable).resolve()
    assert resolved.is_relative_to(python_root), executable


@pytest.mark.xfail(reason="green after W2: launch agent health", strict=False)
def test_launch_agent_health() -> None:
    app = require_app()
    binary = app / MAIN_EXECUTABLE_RELATIVE
    port = loopback_port(app)
    try:
        register = run([str(binary), "--register"], timeout=30)
        assert register.returncode == 0, clip(register.stderr + register.stdout)
        assert wait_for_health(port, timeout_s=HEALTH_TIMEOUT_S) == 200
    finally:
        unregister = run([str(binary), "--unregister"], timeout=30)
    assert unregister.returncode == 0, clip(unregister.stderr + unregister.stdout)
    assert wait_until_health_stops(port, timeout_s=HEALTH_TIMEOUT_S) != 200


@pytest.mark.xfail(reason="green after W2: helper --health", strict=False)
def test_helper_health() -> None:
    app = require_app()
    result = helper_output(app, "--health", timeout=10)
    assert result.returncode == 0
