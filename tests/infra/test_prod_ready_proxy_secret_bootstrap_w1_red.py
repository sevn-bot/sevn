"""Prod-ready Batch A W1.5 — generate proxy secret on first boot (C1.2; D37).

Bootstrap contract: clean ``sevn-state`` gets ``/operator/.sevn/proxy-shared-secret``
(mode ``0600``, uid ``10001``); not regenerated on next boot; explicit env wins;
``.env.example`` has no blank ``SEVN_PROXY_SHARED_SECRET=`` line.
"""

from __future__ import annotations

import importlib.util
import os
import re
import stat
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ENV_EXAMPLE = _REPO_ROOT / ".env.example"
_BASE_COMPOSE = _REPO_ROOT / "docker" / "docker-compose.yml"
_BROWSER_COMPOSE = _REPO_ROOT / "docker" / "docker-compose.browser.yml"
_GUI_COMPOSE = _REPO_ROOT / "docker" / "docker-compose.gui.yml"
_SECRET_REL = ".sevn/proxy-shared-secret"
_SECRET_ABS = f"/operator/{_SECRET_REL}"
_OPERATOR_UID = 10001

_BLANK_SECRET_LINE_RE = re.compile(
    r"^SEVN_PROXY_SHARED_SECRET=\s*(?:#.*)?$",
    re.MULTILINE,
)


def _load_services(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    services = data.get("services")
    return services if isinstance(services, dict) else {}


def _compose_corpus() -> str:
    parts = [
        _BASE_COMPOSE.read_text(encoding="utf-8"),
        _BROWSER_COMPOSE.read_text(encoding="utf-8") if _BROWSER_COMPOSE.is_file() else "",
        _GUI_COMPOSE.read_text(encoding="utf-8") if _GUI_COMPOSE.is_file() else "",
    ]
    # Include likely init / entrypoint helpers W4 may extend.
    for rel in (
        "infra/docker/gateway-entrypoint.sh",
        "infra/docker/compose-bootstrap.py",
        "scripts/generate_proxy_shared_secret.py",
        "scripts/ensure_proxy_shared_secret.py",
    ):
        path = _REPO_ROOT / rel
        if path.is_file():
            parts.append(path.read_text(encoding="utf-8"))
    return "\n".join(parts)


def _load_ensure_helper() -> Any:
    """Load the W4 generate-once helper (script or package module)."""
    candidates = [
        _REPO_ROOT / "scripts" / "ensure_proxy_shared_secret.py",
        _REPO_ROOT / "scripts" / "generate_proxy_shared_secret.py",
        _REPO_ROOT / "infra" / "docker" / "ensure_proxy_shared_secret.py",
    ]
    for path in candidates:
        if not path.is_file():
            continue
        spec = importlib.util.spec_from_file_location("prod_ready_proxy_secret_helper", path)
        assert spec is not None
        assert spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module
    # Package import fallback once W4 lands the helper under sevn.
    return importlib.import_module("sevn.proxy.bootstrap_secret")


def test_env_example_has_no_blank_proxy_shared_secret_assignment() -> None:
    """W1.5 / D37: blank placeholder recreates the silent-empty path — remove it."""
    text = _ENV_EXAMPLE.read_text(encoding="utf-8")
    assert not _BLANK_SECRET_LINE_RE.search(text), (
        ".env.example still assigns a blank SEVN_PROXY_SHARED_SECRET= (D37)"
    )
    assert "SEVN_PROXY_SHARED_SECRET" in text, (
        ".env.example must still document the variable (generation / override)"
    )


def test_compose_mentions_generated_secret_path() -> None:
    """W1.5: one-shot init writes the agreed path under sevn-state."""
    corpus = _compose_corpus()
    assert _SECRET_ABS in corpus or _SECRET_REL in corpus, (
        f"compose/bootstrap must generate {_SECRET_ABS}"
    )


def test_proxy_and_gateway_read_generated_secret_with_env_override() -> None:
    """W1.5: both services consume the generated file; explicit env interpolation still allowed."""
    services = _load_services(_BASE_COMPOSE)
    corpus = _compose_corpus()
    for name in ("sevn-proxy", "sevn-gateway"):
        env = (services.get(name) or {}).get("environment") or {}
        assert "SEVN_PROXY_SHARED_SECRET" in env, f"{name} missing SEVN_PROXY_SHARED_SECRET"
    # Generated file path must appear in the compose/bootstrap corpus (not only ${VAR:-}).
    assert _SECRET_ABS in corpus or _SECRET_REL in corpus, (
        "services must be wired to the generated sevn-state secret file"
    )
    # One-shot init / perms command must create the file (not just document the path).
    assert re.search(
        r"(?:proxy-shared-secret|ensure_proxy_shared_secret|generate.*secret)",
        corpus,
        re.IGNORECASE,
    ), "compose stack must include a generate-once secret step"


def test_ensure_helper_creates_secret_once_with_mode_and_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W1.5: generate-once helper creates mode 0600 / uid 10001 and is idempotent."""
    monkeypatch.delenv("SEVN_PROXY_SHARED_SECRET", raising=False)
    module = _load_ensure_helper()
    ensure = getattr(module, "ensure_proxy_shared_secret_file", None) or getattr(
        module,
        "ensure_generated_proxy_shared_secret",
        None,
    )
    assert callable(ensure), "W4 must export ensure_proxy_shared_secret_file(...)"

    operator_root = tmp_path / "operator"
    operator_root.mkdir()
    first = ensure(operator_root)
    path = Path(first) if not isinstance(first, Path) else first
    assert path.is_file()
    assert path.name == "proxy-shared-secret"
    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == 0o600, f"expected mode 0600, got {oct(mode)}"
    # uid check: on platforms where chown is allowed; otherwise skip ownership.
    if hasattr(os, "geteuid") and os.geteuid() == 0:  # pragma: no cover
        assert path.stat().st_uid == _OPERATOR_UID

    first_text = path.read_text(encoding="utf-8")
    assert len(first_text.strip()) >= 24, "generated secret must be high-entropy"

    second = ensure(operator_root)
    path2 = Path(second) if not isinstance(second, Path) else second
    assert path2 == path
    assert path.read_text(encoding="utf-8") == first_text, "must not regenerate on next boot"


def test_explicit_env_takes_precedence_over_generated_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W1.5 / D37: explicitly-set env wins for external secret managers."""
    module = _load_ensure_helper()
    ensure = getattr(module, "ensure_proxy_shared_secret_file", None) or getattr(
        module,
        "ensure_generated_proxy_shared_secret",
        None,
    )
    assert callable(ensure)
    operator_root = tmp_path / "operator"
    operator_root.mkdir()
    ensure(operator_root)

    resolve = getattr(module, "resolve_effective_proxy_shared_secret", None)
    assert callable(resolve), (
        "W4 must export resolve_effective_proxy_shared_secret(env, state_root)"
    )
    monkeypatch.setenv("SEVN_PROXY_SHARED_SECRET", "explicit-operator-secret")
    effective = resolve(env=os.environ, state_root=operator_root)
    assert effective == "explicit-operator-secret"
