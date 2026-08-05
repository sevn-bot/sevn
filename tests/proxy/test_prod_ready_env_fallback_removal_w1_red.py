"""Prod-ready Batch A W1.3 RED — delete env fallbacks + write-back (C3.2; D41).

Source-level contract: zero ``os.environ.get("SEVN_PROXY_SHARED_SECRET")`` reads under
``src/`` outside the documented sandbox child-env seam
(``data/bundled_skills/core/job-ops/scripts/lib/llm.py``), and no
``os.environ["SEVN_PROXY_SHARED_SECRET"] = …`` write-backs. Green after W3.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC_ROOT = _REPO_ROOT / "src"
_ALLOWED_ENV_GET_RELPATHS = frozenset(
    {
        "sevn/data/bundled_skills/core/job-ops/scripts/lib/llm.py",
    },
)
_ENV_GET_RE = re.compile(r"""os\.environ\.get\(\s*["']SEVN_PROXY_SHARED_SECRET["']""")
_ENV_SET_RE = re.compile(r"""os\.environ\[\s*["']SEVN_PROXY_SHARED_SECRET["']\s*\]\s*=""")


def _iter_python_under_src() -> list[Path]:
    return sorted(p for p in _SRC_ROOT.rglob("*.py") if p.is_file())


def _rel_src(path: Path) -> str:
    return path.relative_to(_SRC_ROOT).as_posix()


def test_zero_os_environ_get_reads_outside_sandbox_child_env_seam() -> None:
    """W1.3 / C3.2: gateway/tool call sites must not re-read the secret from os.environ."""
    offenders: list[str] = []
    for path in _iter_python_under_src():
        rel = _rel_src(path)
        text = path.read_text(encoding="utf-8")
        if not _ENV_GET_RE.search(text):
            continue
        if rel in _ALLOWED_ENV_GET_RELPATHS:
            continue
        offenders.append(rel)
    assert offenders == [], (
        "os.environ.get('SEVN_PROXY_SHARED_SECRET') remains outside the sandbox "
        f"child-env seam: {offenders}"
    )


def test_job_ops_llm_seam_keeps_documented_env_read() -> None:
    """W1.3 baseline guard: sandbox child-env seam keeps the env read (must survive W3)."""
    seam = _SRC_ROOT / "sevn/data/bundled_skills/core/job-ops/scripts/lib/llm.py"
    assert seam.is_file()
    text = seam.read_text(encoding="utf-8")
    assert _ENV_GET_RE.search(text), "sandbox child-env seam lost its env read"


def test_no_os_environ_write_back_of_proxy_shared_secret() -> None:
    """W1.3 / D41: credentials + gateway must not mutate process environ with the secret."""
    offenders: list[str] = []
    for path in _iter_python_under_src():
        text = path.read_text(encoding="utf-8")
        if _ENV_SET_RE.search(text):
            offenders.append(_rel_src(path))
    assert offenders == [], (
        f"os.environ['SEVN_PROXY_SHARED_SECRET'] = … write-back still present: {offenders}"
    )


def test_credentials_module_no_longer_writes_environ() -> None:
    """W1.3 / D41 direct symbol: credentials resolution must not write back."""
    path = _SRC_ROOT / "sevn/proxy/credentials.py"
    text = path.read_text(encoding="utf-8")
    assert not _ENV_SET_RE.search(text)


def test_http_server_no_longer_writes_environ() -> None:
    """W1.3: extra write-back at gateway boot (W0.5) must also be deleted."""
    path = _SRC_ROOT / "sevn/gateway/http_server.py"
    text = path.read_text(encoding="utf-8")
    assert not _ENV_SET_RE.search(text)
