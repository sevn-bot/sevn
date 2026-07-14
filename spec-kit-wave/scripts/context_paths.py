#!/usr/bin/env python3
"""Resolve glossary/ADR/wayfinder paths from ``skw.toml``.

Reads the ``[context]`` and ``[wayfinder]`` tables of ``skw.toml`` directly with
stdlib ``tomllib`` — deliberately **not** via ``skw.validate.load_skw_config``,
which does not surface unknown tables (it only merges keys it already knows
about into its returned config). Skills loaded raw by an IDE (no ``skw``
package on ``sys.path``) call this script instead, so glossary/ADR/wayfinder
paths are never hardcoded in a ``SKILL.md``.

Falls back to the documented defaults (matching
``docs/mattpocock-skills-integration.md`` §5.5.3/§5.8) when ``skw.toml`` is
missing or the tables are absent, so vendored skills stay portable to a host
repo that hasn't configured ``[context]``/``[wayfinder]`` yet.

Usage:
    python3 scripts/context_paths.py [--slug SLUG] [--kit-root PATH]

Prints ``KEY=VALUE`` lines with absolute, resolved paths, e.g.::

    glossary=/repo/about-sevn.bot/GLOSSARY.md
    decisions_dir=/repo/about-sevn.bot/decisions
    wayfinder_maps_dir=/repo/spec-kit-wave/spec/demo/wayfinder
"""

from __future__ import annotations

import argparse
import tomllib
from pathlib import Path

_DEFAULT_GLOSSARY = "about-sevn.bot/GLOSSARY.md"
_DEFAULT_DECISIONS_DIR = "about-sevn.bot/decisions"
_DEFAULT_WAYFINDER_MAPS_DIR = "spec/{slug}/wayfinder"
_DEFAULT_GITHUB_TRIAGE_POLICY = (
    "spec-kit-wave/skills/github-issue-triage/references/triage-policy.md"
)
_DEFAULT_GITHUB_WAVE_PLANS_DIR = ".ignorelocal/waves"
_DEFAULT_GITHUB_CONTRIBUTING = "CONTRIBUTING.md"
_DEFAULT_GITHUB_SECURITY = "SECURITY.md"
_DEFAULT_SLUG = "default"


def _kit_root() -> Path:
    """Return the spec-kit-wave kit root (parent of this ``scripts/`` dir)."""
    return Path(__file__).resolve().parent.parent


def load_context_config(kit_root: Path) -> dict[str, str]:
    """Read ``[context]``/``[wayfinder]`` from ``kit_root/skw.toml``.

    Args:
        kit_root: spec-kit-wave kit root (contains ``skw.toml``).

    Returns:
        Raw, unresolved config strings keyed ``glossary``, ``decisions_dir``,
        ``wayfinder_maps_dir``. ``wayfinder_maps_dir`` may still contain a
        ``{slug}`` placeholder. Falls back to documented defaults when
        ``skw.toml`` is absent, unparsable, or missing a table/key.
    """
    cfg = {
        "glossary": _DEFAULT_GLOSSARY,
        "decisions_dir": _DEFAULT_DECISIONS_DIR,
        "wayfinder_maps_dir": _DEFAULT_WAYFINDER_MAPS_DIR,
        "github_triage_policy": _DEFAULT_GITHUB_TRIAGE_POLICY,
        "github_wave_plans_dir": _DEFAULT_GITHUB_WAVE_PLANS_DIR,
        "github_contributing": _DEFAULT_GITHUB_CONTRIBUTING,
        "github_security": _DEFAULT_GITHUB_SECURITY,
        "github_default_repo": "",
    }
    skw_path = kit_root / "skw.toml"
    if not skw_path.is_file():
        return cfg
    try:
        data = tomllib.loads(skw_path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError:
        return cfg

    context = data.get("context")
    if isinstance(context, dict):
        glossary = context.get("glossary")
        if isinstance(glossary, str) and glossary.strip():
            cfg["glossary"] = glossary.strip()
        decisions_dir = context.get("decisions_dir")
        if isinstance(decisions_dir, str) and decisions_dir.strip():
            cfg["decisions_dir"] = decisions_dir.strip()

    wayfinder = data.get("wayfinder")
    if isinstance(wayfinder, dict):
        maps_dir = wayfinder.get("maps_dir")
        if isinstance(maps_dir, str) and maps_dir.strip():
            cfg["wayfinder_maps_dir"] = maps_dir.strip()

    github = data.get("github")
    if isinstance(github, dict):
        for key, default, out_key in (
            ("triage_policy", _DEFAULT_GITHUB_TRIAGE_POLICY, "github_triage_policy"),
            ("wave_plans_dir", _DEFAULT_GITHUB_WAVE_PLANS_DIR, "github_wave_plans_dir"),
            ("contributing", _DEFAULT_GITHUB_CONTRIBUTING, "github_contributing"),
            ("security", _DEFAULT_GITHUB_SECURITY, "github_security"),
        ):
            val = github.get(key)
            if isinstance(val, str) and val.strip():
                cfg[out_key] = val.strip()
            else:
                cfg[out_key] = default
        default_repo = github.get("default_repo")
        cfg["github_default_repo"] = default_repo.strip() if isinstance(default_repo, str) else ""
    else:
        cfg["github_triage_policy"] = _DEFAULT_GITHUB_TRIAGE_POLICY
        cfg["github_wave_plans_dir"] = _DEFAULT_GITHUB_WAVE_PLANS_DIR
        cfg["github_contributing"] = _DEFAULT_GITHUB_CONTRIBUTING
        cfg["github_security"] = _DEFAULT_GITHUB_SECURITY
        cfg["github_default_repo"] = ""

    return cfg


def resolve_context_paths(kit_root: Path, slug: str) -> dict[str, Path]:
    """Resolve raw ``skw.toml`` config strings to absolute filesystem paths.

    ``glossary``/``decisions_dir`` are **repo-root relative** (``about-sevn.bot/``
    lives beside the kit, not inside it); ``wayfinder_maps_dir`` is **kit-root
    relative** and may contain a ``{slug}`` placeholder, expanded here.

    Args:
        kit_root: spec-kit-wave kit root.
        slug: value to substitute for ``{slug}`` in ``wayfinder_maps_dir``.

    Returns:
        dict with keys ``glossary``, ``decisions_dir``, ``wayfinder_maps_dir``
        mapped to resolved absolute ``Path`` objects.
    """
    raw = load_context_config(kit_root)
    repo_root = kit_root.parent
    wayfinder_rel = raw["wayfinder_maps_dir"].format(slug=slug)
    return {
        "glossary": (repo_root / raw["glossary"]).resolve(),
        "decisions_dir": (repo_root / raw["decisions_dir"]).resolve(),
        "wayfinder_maps_dir": (kit_root / wayfinder_rel).resolve(),
        "github_triage_policy": (repo_root / raw["github_triage_policy"]).resolve(),
        "github_wave_plans_dir": (repo_root / raw["github_wave_plans_dir"]).resolve(),
        "github_contributing": (repo_root / raw["github_contributing"]).resolve(),
        "github_security": (repo_root / raw["github_security"]).resolve(),
        "github_default_repo": raw["github_default_repo"],
    }


def main() -> None:
    """CLI entry point: print resolved paths as ``KEY=VALUE`` lines."""
    parser = argparse.ArgumentParser(
        description=(
            "Resolve glossary/ADR/wayfinder paths from skw.toml's "
            "[context]/[wayfinder] tables (stdlib-only)."
        )
    )
    parser.add_argument(
        "--slug",
        default=_DEFAULT_SLUG,
        help=f"Slug to expand {{slug}} in wayfinder.maps_dir (default: {_DEFAULT_SLUG}).",
    )
    parser.add_argument(
        "--kit-root",
        type=Path,
        default=None,
        help="spec-kit-wave kit root (defaults to this script's parent directory).",
    )
    args = parser.parse_args()

    kit_root = (args.kit_root or _kit_root()).resolve()
    paths = resolve_context_paths(kit_root, args.slug)

    print(f"glossary={paths['glossary']}")
    print(f"decisions_dir={paths['decisions_dir']}")
    print(f"wayfinder_maps_dir={paths['wayfinder_maps_dir']}")
    print(f"github_triage_policy={paths['github_triage_policy']}")
    print(f"github_wave_plans_dir={paths['github_wave_plans_dir']}")
    print(f"github_contributing={paths['github_contributing']}")
    print(f"github_security={paths['github_security']}")
    print(f"github_default_repo={paths['github_default_repo']}")


if __name__ == "__main__":
    main()
