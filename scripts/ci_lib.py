"""Shared helpers for partial CI gates (``ci-changed``, ``ci-affected``).

Module: scripts.ci_lib
Depends: fnmatch, os, subprocess, pathlib

Exports:
    PathRule — path glob → make target mapping row.
    collect_changed_paths — git diff union vs ``SEVN_CI_BASE``.
    collect_changed_py — changed ``.py`` under scan roots.
    match_path_rules — map changed paths to ``make`` target names.
    discover_related_tests — import-graph test selection.
    build_python_gate_steps — ruff/mypy/pytest step list for changed Python.
    run_step — subprocess helper with banner logging.
    run_make_targets — run deduped ``make`` targets in order.
    run_python_gates — execute Python partial gates.

Examples:
    >>> REPO_ROOT.name
    'sevn.bot'
"""

from __future__ import annotations

import fnmatch
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
_SCAN_ROOTS = ("src/", "tests/", "scripts/")
_PY_SCAN_ROOTS = _SCAN_ROOTS


@dataclass(frozen=True)
class PathRule:
    """Map path globs (repo-relative) to one ``make`` target."""

    patterns: tuple[str, ...]
    target: str


# Order matters for logging only; targets are deduped before execution.
PATH_RULES: tuple[PathRule, ...] = (
    PathRule(
        (".ignorelocal/kits/wave-orchestrator/**", "wave-orchestrator/**"),
        "wave-orchestrator-check",
    ),
    PathRule(("pyproject.toml", "uv.lock"), "lockcheck"),
    PathRule(("pyproject.toml",), "security"),
    PathRule(
        (
            "src/sevn/gateway/menu/**",
            "about-sevn.bot/Telegram Menu.html",
            "about-sevn.bot/Telegram*",
            "scripts/check_telegram_menu*.py",
            "scripts/telegram_menu_*.py",
        ),
        "telegram-menu-check",
    ),
    PathRule(
        (
            "src/sevn/gateway/menu/**",
            "about-sevn.bot/Telegram Menu.html",
            "about-sevn.bot/Telegram*",
            "scripts/check_telegram_menu_docs.py",
            "scripts/telegram_menu_*.py",
        ),
        "telegram-menu-docs-check",
    ),
    PathRule(
        (
            "src/sevn/ui/dashboard/**",
            "src/sevn/ui/spa/dashboard/**",
            "infra/mission-control.schema.json",
            "infra/mission-control.schema.meta.json",
            "infra/e2e-mission-control-workspace/**",
            "scripts/check_mission_control_schema.py",
            "scripts/generate_mission_control_schema.py",
            "scripts/mission_control_schema_lib.py",
        ),
        "mission-control-schema-check",
    ),
    PathRule(
        (
            "src/sevn/agent/context_manifest.py",
            "src/sevn/agent/executors/b_harness.py",
            "src/sevn/agent/persona.py",
            "src/sevn/agent/triager/prompt.py",
            "src/sevn/agent/executors/cd_harness.py",
            "infra/agent-context.manifest.json",
            "infra/agent-context.schema.meta.json",
            "scripts/generate_agent_context_manifest.py",
            "scripts/agent_context_manifest_lib.py",
        ),
        "agent-context-manifest-check",
    ),
    PathRule(
        (
            "src/sevn/data/bundled_skills/**",
            "skills/**",
            "scripts/check_skills_core_manifest.py",
        ),
        "skills-core-check",
    ),
    PathRule(
        (
            "src/sevn/data/bundled_skills/**",
            "skills/**",
            "scripts/check_skillspector.py",
        ),
        "skillspector-check",
    ),
    PathRule(
        (
            "src/sevn/data/skills/INDEX.md",
            "src/sevn/data/bundled_skills/core/**",
            "scripts/check_skills_index.py",
        ),
        "skills-index-check",
    ),
    PathRule(
        (
            "src/sevn/tools/**",
            "src/sevn/data/bundled_skills/**",
            "scripts/check_tools_skills_inventory.py",
        ),
        "tools-skills-inventory-check",
    ),
    PathRule(
        ("src/sevn/dreaming/**", "scripts/check_dreaming_allowlist.py"),
        "dreaming-allowlist-check",
    ),
    PathRule(
        (
            "infra/sevn.schema.json",
            "infra/onboarding_*.schema.json",
            "src/sevn/data/onboarding_capabilities.json",
            "src/sevn/onboarding/capabilities_manifest.py",
            "scripts/check_onboarding_capabilities.py",
            "tests/fixtures/config/**",
            "src/sevn/data/onboarding_profiles/**",
            "scripts/check_infra_parity.py",
            "scripts/export_triage_schema.py",
        ),
        "config-schema",
    ),
    PathRule(
        (
            "infra/onboarding_catalog.schema.json",
            "infra/onboarding_fragment.schema.json",
            "src/sevn/data/onboarding_profiles/**",
        ),
        "onboarding-profiles-schema",
    ),
    PathRule(
        (
            "infra/**",
            "scripts/check_infra_parity.py",
            "scripts/export_triage_schema.py",
        ),
        "infra-check",
    ),
    PathRule(
        (
            "src/sevn/docs/readme/**",
            "README.md",
            "scripts/readme_*.py",
        ),
        "readme-check",
    ),
    PathRule(
        (
            "about-sevn.bot/**",
            "scripts/build_about_site.py",
            "scripts/check_telegram_menu_docs.py",
            "scripts/check_mission_control_docs.py",
            "scripts/agent_context_manifest_lib.py",
            "scripts/generate_agent_context_manifest.py",
            "infra/agent-context.manifest.json",
            "tests/fixtures/agent_context/**",
        ),
        "about-site-check",
    ),
    PathRule(
        (
            "scripts/build_code_index.py",
            ".index/code_index/**",
        ),
        "code-index-check",
    ),
    PathRule(
        ("reports/remote-deploy-*.json",),
        "deploy-remote-report-check",
    ),
)

# ``make`` target order when multiple path rules fire (stable, tier-ish).
TARGET_ORDER: tuple[str, ...] = (
    "lockcheck",
    "wave-orchestrator-check",
    "telegram-menu-check",
    "telegram-menu-docs-check",
    "mission-control-schema-check",
    "agent-context-manifest-check",
    "config-schema",
    "onboarding-profiles-schema",
    "infra-check",
    "skills-core-check",
    "skillspector-check",
    "skills-index-check",
    "tools-skills-inventory-check",
    "dreaming-allowlist-check",
    "readme-check",
    "about-site-check",
    "code-index-check",
    "deploy-remote-report-check",
    "security",
)


def _git_lines(args: list[str]) -> list[str]:
    """Return non-empty lines from a git command (empty when git fails).

    Args:
        args (list[str]): Arguments after ``git``.

    Returns:
        list[str]: Trimmed stdout lines.

    Examples:
        >>> isinstance(_git_lines(["rev-parse", "--show-toplevel"]), list)
        True
    """
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return []
    if proc.returncode != 0:
        return []
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def collect_changed_paths() -> list[str]:
    """Union changed repo-relative paths (working tree, index, branch vs base).

    Returns:
        list[str]: Sorted unique paths.

    Examples:
        >>> isinstance(collect_changed_paths(), list)
        True
    """
    base = os.environ.get("SEVN_CI_BASE", "origin/main")
    seen: set[str] = set()
    for rel in (
        *_git_lines(["diff", "--name-only", "--diff-filter=ACMR"]),
        *_git_lines(["diff", "--cached", "--name-only", "--diff-filter=ACMR"]),
        *_git_lines(["diff", "--name-only", f"{base}...HEAD", "--diff-filter=ACMR"]),
    ):
        if rel:
            seen.add(rel)
    return sorted(seen)


def collect_changed_py() -> list[Path]:
    """Union changed ``.py`` files under ``src/``, ``tests/``, ``scripts/``.

    Returns:
        list[Path]: Absolute paths, sorted unique.

    Examples:
        >>> paths = collect_changed_py()
        >>> all(p.suffix == ".py" for p in paths)
        True
    """
    return sorted(
        REPO_ROOT / rel
        for rel in collect_changed_paths()
        if rel.endswith(".py") and rel.startswith(_PY_SCAN_ROOTS)
    )


def _pattern_matches(rel_path: str, pattern: str) -> bool:
    """Return True when ``rel_path`` matches a repo-relative glob pattern.

    Args:
        rel_path (str): Repo-relative file path.
        pattern (str): Glob (``**`` supported via ``fnmatch`` segments).

    Returns:
        bool: True on match.

    Examples:
        >>> _pattern_matches("src/sevn/gateway/menu/menu_registry.py", "src/sevn/gateway/menu/**")
        True
    """
    if fnmatch.fnmatch(rel_path, pattern):
        return True
    if "**" in pattern:
        prefix = pattern.split("**", 1)[0]
        if prefix and rel_path.startswith(prefix):
            return True
    return False


def match_path_rules(changed: list[str]) -> list[str]:
    """Map changed paths to deduped ``make`` targets (stable order).

    Args:
        changed (list[str]): Repo-relative changed paths.

    Returns:
        list[str]: ``make`` target names to run.

    Examples:
        >>> match_path_rules([".ignorelocal/kits/wave-orchestrator/src/waveorch/engine.py"])
        ['wave-orchestrator-check']
    """
    matched: set[str] = set()
    for rel in changed:
        for rule in PATH_RULES:
            if any(_pattern_matches(rel, pat) for pat in rule.patterns):
                matched.add(rule.target)
    order = {name: idx for idx, name in enumerate(TARGET_ORDER)}
    return sorted(matched, key=lambda t: (order.get(t, len(TARGET_ORDER)), t))


def _is_under(path: Path, root: Path) -> bool:
    """Return True when ``path`` is inside ``root``.

    Args:
        path (Path): Candidate file.
        root (Path): Directory prefix.

    Returns:
        bool: True when ``path`` is under ``root``.

    Examples:
        >>> _is_under(REPO_ROOT / "src/sevn/proxy/forward.py", REPO_ROOT / "src/sevn")
        True
    """
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _module_dotted_name(src_path: Path) -> str | None:
    """Map ``src/sevn/pkg/mod.py`` → ``sevn.pkg.mod``.

    Args:
        src_path (Path): Source file under ``src/``.

    Returns:
        str | None: Dotted module name or ``None``.

    Examples:
        >>> p = REPO_ROOT / "src/sevn/gateway/turn/turn_bundle.py"
        >>> _module_dotted_name(p)
        'sevn.gateway.turn.turn_bundle'
    """
    try:
        rel = src_path.relative_to(REPO_ROOT / "src")
    except ValueError:
        return None
    return ".".join(rel.with_suffix("").parts)


def _import_needles(modules: set[str]) -> set[str]:
    """Build substring needles for tests that import ``modules``.

    Args:
        modules (set[str]): Dotted module names.

    Returns:
        set[str]: Import-line substrings to search for.

    Examples:
        >>> "from sevn.gateway" in _import_needles({"sevn.gateway.turn.turn_bundle"})
        True
    """
    needles: set[str] = set()
    for mod in modules:
        needles.add(f"from {mod} ")
        needles.add(f"from {mod}\n")
        needles.add(f"import {mod}")
        parts = mod.split(".")
        for i in range(len(parts), 0, -1):
            pkg = ".".join(parts[:i])
            needles.add(f"from {pkg} import")
            needles.add(f"import {pkg}")
    return needles


def _paired_test(src: Path) -> Path | None:
    """Map ``src/sevn/pkg/mod.py`` to ``tests/pkg/test_mod.py`` when present.

    Args:
        src (Path): Changed source file under ``src/sevn/``.

    Returns:
        Path | None: Matching test module or ``None``.

    Examples:
        >>> p = REPO_ROOT / "src/sevn/gateway/bootstrap/bootstrap_capture.py"
        >>> _paired_test(p) == REPO_ROOT / "tests/gateway/test_bootstrap_capture.py"
        True
    """
    try:
        rel = src.relative_to(REPO_ROOT / "src" / "sevn")
    except ValueError:
        return None
    candidate = REPO_ROOT / "tests" / rel.parent / f"test_{rel.stem}.py"
    if candidate.is_file():
        return candidate
    if rel.parts[0] == "gateway" and len(rel.parts) >= 2:
        flat = REPO_ROOT / "tests" / "gateway" / f"test_{rel.stem}.py"
        return flat if flat.is_file() else None
    return None


def discover_related_tests(src_sevn: list[Path]) -> list[Path]:
    """Select tests for changed ``src/sevn`` modules (paired + import graph).

    Args:
        src_sevn (list[Path]): Changed files under ``src/sevn/``.

    Returns:
        list[Path]: Absolute test paths, sorted unique.

    Examples:
        >>> discover_related_tests([]) == []
        True
    """
    modules = {m for p in src_sevn if (m := _module_dotted_name(p)) is not None}
    if not modules:
        return []

    selected: dict[Path, None] = {}
    for src in src_sevn:
        paired = _paired_test(src)
        if paired is not None:
            selected[paired] = None

    needles = _import_needles(modules)
    tests_root = REPO_ROOT / "tests"
    if tests_root.is_dir():
        for test_file in tests_root.rglob("*.py"):
            if test_file.name == "conftest.py" or not test_file.name.startswith("test_"):
                continue
            try:
                text = test_file.read_text(encoding="utf-8")
            except OSError:
                continue
            if any(needle in text for needle in needles):
                selected[test_file] = None

    return sorted(selected)


def run_step(label: str, cmd: list[str], *, prefix: str = "ci-changed") -> int:
    """Run one subprocess step; print a banner and return exit code.

    Args:
        label (str): Step name for logs.
        cmd (list[str]): Executable + args.
        prefix (str): Log prefix (``ci-changed`` or ``ci-affected``).

    Returns:
        int: Subprocess exit code.

    Examples:
        >>> run_step.__name__
        'run_step'
    """
    rel_cmd = [
        str(Path(part).relative_to(REPO_ROOT)) if part.startswith(str(REPO_ROOT)) else part
        for part in cmd
    ]
    print(f"[{prefix}] {label}: {' '.join(rel_cmd)}", flush=True)
    proc = subprocess.run(cmd, cwd=REPO_ROOT, check=False)
    return int(proc.returncode)


def run_make_targets(targets: list[str], *, prefix: str = "ci-affected") -> int:
    """Run ``make`` targets in order; stop aggregating failures.

    Args:
        targets (list[str]): ``make`` target names.
        prefix (str): Log prefix.

    Returns:
        int: First non-zero exit code, or ``0``.

    Examples:
        >>> run_make_targets([]) == 0
        True
    """
    exit_code = 0
    for target in targets:
        code = run_step(f"make {target}", ["make", target], prefix=prefix)
        if code != 0 and exit_code == 0:
            exit_code = code
    return exit_code


def build_python_gate_steps(changed: list[Path]) -> list[tuple[str, list[str]]]:
    """Build ruff/mypy/pytest steps for changed Python files.

    Args:
        changed (list[Path]): Absolute paths under ``src/``, ``tests/``, ``scripts/``.

    Returns:
        list[tuple[str, list[str]]]: Ordered subprocess steps.

    Examples:
        >>> steps = build_python_gate_steps([])
        >>> steps == []
        True
    """
    if not changed:
        return []

    rel_paths = [str(p.relative_to(REPO_ROOT)) for p in changed]
    src_sevn = [p for p in changed if _is_under(p, REPO_ROOT / "src" / "sevn")]
    scripts_changed = [p for p in changed if _is_under(p, REPO_ROOT / "scripts")]
    test_files = [p for p in changed if _is_under(p, REPO_ROOT / "tests")]
    for src in src_sevn:
        paired = _paired_test(src)
        if paired is not None and paired not in test_files:
            test_files.append(paired)
    for related in discover_related_tests(src_sevn):
        if related not in test_files:
            test_files.append(related)

    uv = ["uv", "run"]
    steps: list[tuple[str, list[str]]] = [
        ("ruff check", [*uv, "ruff", "check", *rel_paths]),
        ("ruff format --check", [*uv, "ruff", "format", "--check", *rel_paths]),
    ]
    if src_sevn:
        src_rel = [str(p.relative_to(REPO_ROOT)) for p in src_sevn]
        steps.extend(
            [
                ("check_docstrings", [*uv, "python", "scripts/check_docstrings.py", *src_rel]),
                ("mypy", [*uv, "mypy", *src_rel]),
                ("check_type_hints", [*uv, "python", "scripts/check_type_hints.py", *src_rel]),
                ("pyright", [*uv, "pyright", *src_rel]),
            ],
        )
        steps.append(("lint-imports", ["make", "lint-imports"]))
    if scripts_changed:
        script_rel = [str(p.relative_to(REPO_ROOT)) for p in scripts_changed]
        steps.append(
            (
                "check_docstrings scripts",
                [*uv, "python", "scripts/check_docstrings.py", *script_rel],
            ),
        )
    if test_files:
        test_rel = [str(p.relative_to(REPO_ROOT)) for p in sorted(test_files)]
        xdist = os.environ.get("SEVN_PYTEST_JOBS", "auto")
        xdist_args = ["-n", xdist] if xdist and xdist != "0" else []
        steps.append(("pytest", [*uv, "pytest", *test_rel, *xdist_args, "-q"]))
    if src_sevn:
        bundled = REPO_ROOT / "src" / "sevn" / "data" / "bundled_skills"
        src_rel = [str(p.relative_to(REPO_ROOT)) for p in src_sevn if not _is_under(p, bundled)]
        if src_rel:
            steps.append(("doctest", [*uv, "pytest", "--doctest-modules", *src_rel, "-q"]))
    return steps


def run_python_gates(changed: list[Path], *, prefix: str = "ci-changed") -> int:
    """Execute Python partial gates for ``changed`` paths.

    Args:
        changed (list[Path]): Absolute ``.py`` paths.
        prefix (str): Log prefix.

    Returns:
        int: ``0`` on success; first failure code otherwise.

    Examples:
        >>> run_python_gates([]) == 0
        True
    """
    steps = build_python_gate_steps(changed)
    exit_code = 0
    for label, cmd in steps:
        code = run_step(label, cmd, prefix=prefix)
        if code != 0 and exit_code == 0:
            exit_code = code
    return exit_code
