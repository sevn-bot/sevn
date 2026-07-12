"""Tests for host-dependency provisioning (`sevn.provisioning.host_deps`)."""

from __future__ import annotations

import pytest

from sevn.provisioning.host_deps import (
    HOST_DEPS,
    HostDep,
    ProvisionOutcome,
    ProvisionReport,
    host_dep_ids,
    provision_host_deps,
    summarize_report,
)


def _dep(dep_id: str, *, present: bool) -> HostDep:
    """Build a fake dependency with brew+apt install plans and a fixed probe."""
    return HostDep(
        id=dep_id,
        title=dep_id.upper(),
        probe=lambda: present,
        fallback_note="fallback active",
        manual_hint=f"install {dep_id} by hand",
        brew_formula=(dep_id,),
        apt_packages=(dep_id,),
    )


def test_registry_ids_stable() -> None:
    assert host_dep_ids() == ("deno", "docker", "pango", "ripgrep")
    assert set(HOST_DEPS) == set(host_dep_ids())


def test_already_present_is_skipped() -> None:
    called: list[list[str]] = []

    def runner(argv):  # type: ignore[no-untyped-def]
        called.append(list(argv))
        return 0, ""

    report = provision_host_deps(
        ["ripgrep"],
        deps={"ripgrep": _dep("ripgrep", present=True)},
        runner=runner,
        system="Darwin",
        pkg_manager="brew",
    )
    assert report.outcomes[0].status == "already_present"
    assert called == []  # never shelled out
    assert report.changed is False


def test_missing_then_installed() -> None:
    # Probe flips to present after the installer runs.
    state = {"present": False}
    dep = HostDep(
        id="ripgrep",
        title="ripgrep",
        probe=lambda: state["present"],
        fallback_note="",
        manual_hint="manual",
        brew_formula=("ripgrep",),
    )

    def runner(argv):  # type: ignore[no-untyped-def]
        assert list(argv) == ["brew", "install", "ripgrep"]
        state["present"] = True
        return 0, "installed"

    report = provision_host_deps(
        ["ripgrep"], deps={"ripgrep": dep}, runner=runner, system="Darwin", pkg_manager="brew"
    )
    assert report.outcomes[0].status == "installed"
    assert report.changed is True


def test_installer_failure_reports_failed_with_hint() -> None:
    def runner(argv):  # type: ignore[no-untyped-def]
        return 1, "brew: some error\nlast line error"

    report = provision_host_deps(
        ["pango"],
        deps={"pango": _dep("pango", present=False)},
        runner=runner,
        system="Darwin",
        pkg_manager="brew",
    )
    out = report.outcomes[0]
    assert out.status == "failed"
    assert "last line error" in out.detail
    assert "install pango by hand" in out.detail


def test_no_installer_for_platform_is_manual() -> None:
    report = provision_host_deps(
        ["deno"],
        deps={"deno": _dep("deno", present=False)},
        system="Windows",
        pkg_manager=None,
    )
    assert report.outcomes[0].status == "manual"
    assert "install deno by hand" in report.outcomes[0].detail


def test_unknown_id_is_unsupported() -> None:
    report = provision_host_deps(["bogus"], deps={}, system="Darwin", pkg_manager="brew")
    assert report.outcomes[0].status == "unsupported"


def test_dry_run_plans_without_running() -> None:
    called: list[list[str]] = []

    def runner(argv):  # type: ignore[no-untyped-def]
        called.append(list(argv))
        return 0, ""

    report = provision_host_deps(
        ["ripgrep"],
        deps={"ripgrep": _dep("ripgrep", present=False)},
        runner=runner,
        dry_run=True,
        system="Darwin",
        pkg_manager="brew",
    )
    assert called == []
    assert report.outcomes[0].status == "manual"
    assert "dry-run: would run `brew install ripgrep`" in report.outcomes[0].detail


def test_selected_are_deduped_and_order_preserved() -> None:
    report = provision_host_deps(
        ["deno", "deno", "ripgrep"],
        deps={"deno": _dep("deno", present=True), "ripgrep": _dep("ripgrep", present=True)},
        system="Darwin",
        pkg_manager="brew",
    )
    assert [o.dep_id for o in report.outcomes] == ["deno", "ripgrep"]


def test_apt_argv_on_linux() -> None:
    def runner(argv):  # type: ignore[no-untyped-def]
        assert list(argv) == ["apt-get", "install", "-y", "ripgrep"]
        return 0, ""

    report = provision_host_deps(
        ["ripgrep"],
        deps={"ripgrep": _dep("ripgrep", present=False)},
        runner=runner,
        system="Linux",
        pkg_manager="apt",
        apt_privileged=True,
    )
    # probe is fixed False so re-probe fails -> manual "installed but not detected"
    assert report.outcomes[0].status == "manual"


def test_linux_apt_without_privilege_is_manual() -> None:
    called: list[list[str]] = []

    def runner(argv):  # type: ignore[no-untyped-def]
        called.append(list(argv))
        return 0, ""

    report = provision_host_deps(
        ["ripgrep"],
        deps={"ripgrep": _dep("ripgrep", present=False)},
        runner=runner,
        system="Linux",
        pkg_manager="apt",
        apt_privileged=False,
    )
    assert called == []
    out = report.outcomes[0]
    assert out.status == "manual"
    assert "passwordless sudo" in out.detail
    assert "ripgrep" in out.detail


def test_docker_cask_argv() -> None:
    argv = HOST_DEPS["docker"].install_argv(system="Darwin", pkg_manager="brew")
    assert argv == ["brew", "install", "--cask", "docker"]


def test_probe_that_raises_treated_as_absent() -> None:
    def boom() -> bool:
        raise RuntimeError("probe blew up")

    dep = HostDep(
        id="ripgrep",
        title="ripgrep",
        probe=boom,
        fallback_note="",
        manual_hint="manual",
    )
    report = provision_host_deps(
        ["ripgrep"], deps={"ripgrep": dep}, system="Windows", pkg_manager=None
    )
    # No installer for Windows -> manual (proves the raising probe did not crash the pass).
    assert report.outcomes[0].status == "manual"


def test_summarize_report_variants() -> None:
    assert summarize_report(ProvisionReport()) == ""
    assert (
        summarize_report(ProvisionReport([ProvisionOutcome("ripgrep", "installed", "x")]))
        == "host deps: installed ripgrep"
    )
    mixed = ProvisionReport(
        [
            ProvisionOutcome("ripgrep", "installed", "x"),
            ProvisionOutcome("pango", "failed", "y"),
            ProvisionOutcome("deno", "manual", "z"),
        ]
    )
    summary = summarize_report(mixed)
    assert "installed ripgrep" in summary
    assert "failed: pango" in summary
    assert "manual: deno" in summary


def test_config_section_validates_ids() -> None:
    from sevn.config.sections.provisioning import ProvisioningWorkspaceConfig

    assert ProvisioningWorkspaceConfig().auto_install == []
    assert ProvisioningWorkspaceConfig(auto_install=["deno", "deno"]).auto_install == ["deno"]
    with pytest.raises(ValueError, match=r"unknown provisioning\.auto_install"):
        ProvisioningWorkspaceConfig(auto_install=["bogus"])


def test_linux_apt_pkg_manager_keeps_apt_only_deps_on_apt() -> None:
    argv = HOST_DEPS["ripgrep"].install_argv(system="Linux", pkg_manager="apt")
    assert argv == ["apt-get", "install", "-y", "ripgrep"]


def test_linux_brew_only_dep_falls_back_to_brew_under_apt_manager() -> None:
    from unittest.mock import patch

    from sevn.voice.host_deps import VOICE_HOST_DEPS

    dep = VOICE_HOST_DEPS["whisper_cpp"]
    with patch("sevn.provisioning.host_deps.shutil.which", return_value="/linuxbrew/bin/brew"):
        argv = dep.install_argv(system="Linux", pkg_manager="apt")
    assert argv == ["brew", "install", "whisper-cpp"]
