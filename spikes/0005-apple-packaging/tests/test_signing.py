"""Codesign, notarization, and verdict checks. Green after W3.

Team and notarization checks skip when the operator has not set the live
credentials. That skip is a missing gate, not a pass.
"""

from __future__ import annotations

import pytest

from support import (
    REQUIRED_GATES,
    SPIKE_ROOT,
    TCC_PATHS,
    as_dict,
    as_list,
    clip,
    iter_macho,
    load_json_object,
    notary_profile,
    require_app,
    run,
    sign_identity,
    team_identifier,
    tool,
)

_HAS_DEVELOPER_ID = bool(sign_identity())
_HAS_NOTARY = bool(notary_profile())


@pytest.mark.xfail(reason="green after W3: codesign deep verify", strict=False)
def test_codesign_deep_verify() -> None:
    app = require_app()
    verify = run(
        [tool("codesign"), "--verify", "--deep", "--strict", "--verbose=2", str(app)],
        timeout=180,
    )
    assert verify.returncode == 0, clip(verify.stderr + verify.stdout)
    info = run([tool("codesign"), "-dv", "--verbose=4", str(app)], timeout=60)
    text = info.stderr + info.stdout
    assert info.returncode == 0, clip(text)
    assert "(runtime)" in text


@pytest.mark.xfail(reason="green after W3: Mach-O files share one TeamIdentifier", strict=False)
@pytest.mark.skipif(not _HAS_DEVELOPER_ID, reason="skipped: no live gate")
def test_every_macho_signed_with_team() -> None:
    app = require_app()
    binaries = iter_macho(app)
    assert binaries, "bundle contains no Mach-O files"
    teams = {team_identifier(path) for path in binaries}
    assert teams != {"not set"}
    assert "not set" not in teams
    assert len(teams) == 1


@pytest.mark.xfail(reason="green after W3: notarized and stapled", strict=False)
@pytest.mark.skipif(
    not (_HAS_DEVELOPER_ID and _HAS_NOTARY),
    reason="skipped: no live gate",
)
def test_notarized_and_stapled() -> None:
    app = require_app()
    stapler = run([tool("xcrun"), "stapler", "validate", str(app)], timeout=120)
    assert stapler.returncode == 0, clip(stapler.stderr + stapler.stdout)
    assessed = run([tool("spctl"), "-a", "-vv", "-t", "exec", str(app)], timeout=60)
    text = assessed.stderr + assessed.stdout
    assert assessed.returncode == 0, clip(text)
    assert "accepted" in text
    assert "Notarized Developer ID" in text


@pytest.mark.xfail(reason="green after W3: library validation stays on", strict=False)
def test_disable_library_validation_is_justified() -> None:
    app = require_app()
    entitlements = run(
        [tool("codesign"), "-d", "--entitlements", ":-", str(app)],
        timeout=60,
    )
    text = entitlements.stdout + entitlements.stderr
    assert entitlements.returncode == 0, clip(text)
    if "disable-library-validation" not in text:
        return
    report = SPIKE_ROOT / "REPORT.md"
    assert report.is_file()
    assert "disable-library-validation" in report.read_text(encoding="utf-8")


@pytest.mark.xfail(reason="green after W3: verdict records packaging", strict=False)
def test_verdict_records_size_and_cold_start() -> None:
    payload = _load_verdict()
    assert payload["report"] == "REPORT.md"
    choice = payload["choice"]
    assert isinstance(choice, str) and choice.strip()
    sha = payload["sha"]
    assert isinstance(sha, str) and sha
    resolved = run(
        [tool("git"), "rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}"],
        timeout=30,
        cwd=SPIKE_ROOT.parents[1],
    )
    assert resolved.returncode == 0, sha
    size = payload["size_mb"]
    assert isinstance(size, int | float) and not isinstance(size, bool) and size > 0
    started = payload["start_to_health_s"]
    assert isinstance(started, int | float) and not isinstance(started, bool)
    assert 0 <= started <= 10
    entitlements = as_list(payload.get("entitlements"), "entitlements")
    assert all(isinstance(item, str) for item in entitlements)
    _assert_gates(payload)
    _assert_report()


def _load_verdict() -> dict[str, object]:
    return load_json_object(SPIKE_ROOT / "VERDICT.json")


def _assert_gates(payload: dict[str, object]) -> None:
    gates = as_dict(payload.get("gates"), "gates")
    outcomes: list[str] = []
    for name in REQUIRED_GATES:
        entry = as_dict(gates.get(name), name)
        outcome = entry.get("outcome")
        assert isinstance(outcome, str)
        assert outcome in {"passed", "failed", "skipped"}
        outcomes.append(outcome)
        reason = entry.get("reason")
        assert isinstance(reason, str) and reason.strip()
        assert isinstance(entry.get("evidence"), list)
    if not sign_identity():
        assert _gate_outcome(gates, "developer-id") == "skipped"
    if not notary_profile():
        assert _gate_outcome(gates, "notary-profile") == "skipped"
    if any(item != "passed" for item in outcomes):
        assert payload["verdict"] == "blocked"
    else:
        assert payload["verdict"] == "pass"
    tcc = as_dict(payload.get("tcc"), "tcc")
    for name in TCC_PATHS:
        recorded = as_dict(tcc.get(name), f"verdict tcc {name}")
        assert isinstance(recorded.get("pass"), bool)


def _gate_outcome(gates: dict[str, object], name: str) -> object:
    return as_dict(gates.get(name), name).get("outcome")


def _assert_report() -> None:
    path = SPIKE_ROOT / "REPORT.md"
    assert path.is_file()
    report = path.read_text(encoding="utf-8")
    for needle in ("Sparkle", "0070", "TCC", "SevnSpike"):
        assert needle in report, needle
