"""Tests for partial CI path routing and test discovery."""

from __future__ import annotations

from scripts.ci_lib import (
    REPO_ROOT,
    _module_dotted_name,
    _paired_test,
    build_python_gate_steps,
    discover_related_tests,
    match_path_rules,
)


def test_module_dotted_name_gateway() -> None:
    path = REPO_ROOT / "src/sevn/gateway/turn/turn_bundle.py"
    assert _module_dotted_name(path) == "sevn.gateway.turn.turn_bundle"


def test_paired_test_maps_gateway_module() -> None:
    src = REPO_ROOT / "src/sevn/gateway/bootstrap/bootstrap_capture.py"
    paired = _paired_test(src)
    assert paired == REPO_ROOT / "tests/gateway/test_bootstrap_capture.py"


def test_match_path_rules_wave_orchestrator() -> None:
    targets = match_path_rules(["wave-orchestrator/src/waveorch/engine.py"])
    assert "wave-orchestrator-check" in targets


def test_match_path_rules_lockfile() -> None:
    targets = match_path_rules(["uv.lock"])
    assert targets == ["lockcheck"]


def test_match_path_rules_telegram_menu() -> None:
    targets = match_path_rules(["src/sevn/gateway/menu/menu_registry.py"])
    assert "telegram-menu-check" in targets
    assert "telegram-menu-docs-check" in targets


def test_match_path_rules_about_docs_check() -> None:
    targets = match_path_rules(["about-sevn.bot/specs/17-gateway.md"])
    assert "about-docs-check" in targets
    assert "about-site-check" in targets


def test_match_path_rules_spec_kit_wave() -> None:
    targets = match_path_rules(["spec-kit-wave/src/skw/spec_validate.py"])
    assert targets == ["about-docs-check"]


def test_discover_related_tests_includes_paired_file() -> None:
    src = REPO_ROOT / "src/sevn/gateway/bootstrap/bootstrap_capture.py"
    tests = discover_related_tests([src])
    assert REPO_ROOT / "tests/gateway/test_bootstrap_capture.py" in tests


def test_discover_related_tests_import_graph() -> None:
    src = REPO_ROOT / "src/sevn/gateway/turn/turn_bundle.py"
    tests = discover_related_tests([src])
    assert any("turn_bundle" in t.name or "gateway" in str(t.parent) for t in tests)


def test_build_python_gate_steps_includes_typecheck() -> None:
    src = REPO_ROOT / "src/sevn/gateway/turn/turn_bundle.py"
    if not src.is_file():
        return
    steps = build_python_gate_steps([src])
    labels = [label for label, _ in steps]
    assert "mypy" in labels
    assert "check_type_hints" in labels
    assert "pyright" in labels
    assert "lint-imports" in labels


def test_match_path_rules_dedupes_and_orders() -> None:
    targets = match_path_rules(
        [
            "infra/onboarding_catalog.schema.json",
            "infra/sevn.schema.json",
        ],
    )
    assert targets.index("config-schema") < targets.index("onboarding-profiles-schema")
