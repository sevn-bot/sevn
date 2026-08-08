"""Prod-ready Batch A W1.8 guard — landed C1.1 suites stay green and unmodified (D40).

``tests/proxy/test_auth.py`` and ``tests/proxy/test_post_audit_proxy_auth_w4_red.py``
must not be edited by Batch A. Critical fail-closed / opt-in / boot-warning contracts
are re-asserted here (nested pytest is avoided — it deadlocks under the parent runner).
Full suite greenness is also required at wave close-out.

D40 amendment (Batch E W19/W20) — three obsolete tests that pinned pre-W19/W20
behavior the implementation inverts (D51 sandbox-family service-secret rejection,
E-V1 run-id binding) may be deleted; replacements live in
``tests/proxy/test_prod_ready_egress_token_e_reverify.py``. The amendment is
narrow: only the test functions enumerated in ``_D40_AMENDMENT_OBSOLETE_TESTS``
are excised; every other change still triggers D40.
"""

from __future__ import annotations

import ast
import os
import subprocess
from pathlib import Path

import httpx
import pytest
from starlette.requests import Request

from sevn.proxy.app import create_app
from sevn.proxy.auth import (
    PROXY_UNCONFIGURED_DETAIL,
    llm_post_auth_failure,
    log_proxy_allow_unauthenticated_boot_warning,
)
from sevn.proxy.settings import ProxySettings

_REPO_ROOT = Path(__file__).resolve().parents[2]
_C11_SUITES = (
    "tests/proxy/test_auth.py",
    "tests/proxy/test_post_audit_proxy_auth_w4_red.py",
)
_UNCONFIGURED_BODY = b'{"detail":"proxy authentication not configured"}'

# D40 amendment — Batch E W19/W20 obsoleted the following landed tests (which
# pinned pre-W19/W20 behavior the implementation inverts). Replacement coverage
# lives in tests/proxy/test_prod_ready_egress_token_e_reverify.py. The amendment
# is narrow: only the test functions enumerated here are excised from the
# "unmodified vs base" comparison; every other change still triggers D40.
_D40_AMENDMENT_OBSOLETE_TESTS: tuple[tuple[str, str], ...] = (
    (
        "tests/proxy/test_auth.py",
        "def test_llm_post_auth_failure_guarded_web_prefix",
    ),
    (
        "tests/proxy/test_post_audit_proxy_auth_w4_red.py",
        "async def test_valid_sandbox_session_token_accepted_on_web_route",
    ),
    (
        "tests/proxy/test_post_audit_proxy_auth_w4_red.py",
        "async def test_concurrent_same_session_token_requests_consistent",
    ),
)


def _synthesize_blessed_file(suite_path: str, base: str) -> str:
    """Return the file content at ``base`` with D40-amendment obsolete tests removed.

    Uses ``ast`` to locate obsolete top-level ``FunctionDef`` /
    ``AsyncFunctionDef`` nodes by name; for each match the function
    definition (decorators + signature + body + the trailing blank-line
    separator) is excised and replaced with a single ``\\n`` separator.
    """
    proc = _git("show", f"{base}:{suite_path}")
    if proc.returncode != 0:
        msg = f"C1.1 guard could not read {suite_path} at {base}:\n{proc.stdout}{proc.stderr}"
        raise AssertionError(msg)
    source = proc.stdout
    obsolete_names: set[str] = {
        # The signature may start with "def " or "async def ". The function
        # name is the last whitespace-separated token in the signature.
        sig.split()[-1]
        for amend_suite, sig in _D40_AMENDMENT_OBSOLETE_TESTS
        if amend_suite == suite_path
    }
    if not obsolete_names:
        return source

    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        msg = f"C1.1 guard could not parse {suite_path} at {base}: {exc}"
        raise AssertionError(msg) from exc

    lines = source.splitlines(keepends=True)
    n = len(lines)

    # Compute (start_line, end_line) 1-based inclusive ranges to excise.
    # start_line = min decorator lineno or signature lineno.
    # end_line = node.end_lineno.
    # We extend each range DOWNWARD through any trailing blank lines, and
    # UPWARD through any preceding blank line (one). This leaves exactly
    # one blank line as the separator to the next block.
    obsolete_ranges: list[tuple[int, int]] = []
    for node in tree.body:
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name in obsolete_names
        ):
            start = node.lineno
            for dec in node.decorator_list:
                start = min(start, dec.lineno)
            end = node.end_lineno
            # Extend end through trailing blank lines
            while end < n and lines[end].strip() == "":
                end += 1
            # Extend start backward through preceding blank lines (one only)
            if start > 1 and lines[start - 2].strip() == "":
                start -= 1
            obsolete_ranges.append((start, end))

    if not obsolete_ranges:
        return source

    # Merge overlapping ranges (shouldn't happen but be safe).
    obsolete_ranges.sort()
    merged: list[list[int]] = []
    for start, end in obsolete_ranges:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])

    out: list[str] = []
    cursor = 1  # 1-based
    for start, end in merged:
        # Emit lines [cursor, start) unchanged
        while cursor < start:
            out.append(lines[cursor - 1])
            cursor += 1
        # Skip lines [start, end]
        cursor = end + 1
        # Emit a single blank line as the new separator
        out.append("\n")
    # Emit the tail
    while cursor <= n:
        out.append(lines[cursor - 1])
        cursor += 1
    return "".join(out)


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    # Use absolute git — repo ``bin/git`` PATH wrapper can hang under nested pytest.
    return subprocess.run(
        ["/usr/bin/git", *args],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def _rev_ok(ref: str) -> bool:
    return _git("rev-parse", "--verify", f"{ref}^{{commit}}").returncode == 0


def _resolve_c11_diff_base() -> str:
    """Resolve a git base for the unmodified-suite guard (shallow CI safe).

    Preference order: ``SEVN_CI_BASE``, ``GITHUB_BASE_SHA``, ``origin/$GITHUB_BASE_REF``,
    then ``origin/pre-0.0.1``. When the preferred tip is missing (Actions shallow
    checkout), fetch the base branch tip once and use ``FETCH_HEAD``.
    """
    candidates: list[str] = []
    for key in ("SEVN_CI_BASE", "GITHUB_BASE_SHA"):
        raw = (os.environ.get(key) or "").strip()
        if raw:
            candidates.append(raw)
    base_ref = (os.environ.get("GITHUB_BASE_REF") or "").strip() or "pre-0.0.1"
    if not base_ref.startswith("origin/"):
        candidates.append(f"origin/{base_ref}")
    candidates.append(base_ref)
    if "origin/pre-0.0.1" not in candidates:
        candidates.append("origin/pre-0.0.1")

    for cand in candidates:
        if _rev_ok(cand):
            return cand

    fetch_ref = base_ref.removeprefix("origin/")
    fetch = _git("fetch", "--depth=1", "origin", fetch_ref)
    assert fetch.returncode == 0, (
        f"C1.1 guard could not resolve base ref (tried {candidates!r}); "
        f"fetch origin {fetch_ref} failed:\n{fetch.stdout}{fetch.stderr}"
    )
    for cand in (f"origin/{fetch_ref}", "FETCH_HEAD"):
        if _rev_ok(cand):
            return cand
    msg = f"C1.1 guard fetch succeeded but no usable tip for {fetch_ref!r}"
    raise AssertionError(msg)


def _request(*, path: str = "/web/fetch") -> Request:
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "path": path,
        "headers": [],
        "query_string": b"",
        "client": ("127.0.0.1", 12345),
    }
    return Request(scope)


def test_c11_suite_files_unmodified_vs_ci_base() -> None:
    """D40: Batch A must not edit the landed C1.1 regression suites.

    D40 amendment (Batch E W19/W20): the obsolete tests enumerated in
    ``_D40_AMENDMENT_OBSOLETE_TESTS`` may be deleted; their replacements
    live in ``tests/proxy/test_prod_ready_egress_token_e_reverify.py``.
    Any other change to a C1.1 suite is still a D40 violation.
    """
    import difflib

    base = _resolve_c11_diff_base()
    violations: list[str] = []
    for suite in _C11_SUITES:
        working = Path(suite).read_text(encoding="utf-8")
        blessed = _synthesize_blessed_file(suite, base)
        if working != blessed:
            diff = "".join(
                difflib.unified_diff(
                    blessed.splitlines(keepends=True),
                    working.splitlines(keepends=True),
                    fromfile=f"{base}:{suite}",
                    tofile=f"working:{suite}",
                    n=3,
                )
            )
            violations.append(f"{suite} differs from {base} (D40 violation):\n{diff}")
    assert not violations, "\n".join(violations)


def test_c11_fail_closed_503_when_secret_unconfigured() -> None:
    """D40 smoke: deleting the fail-closed branch must break this guard."""
    resp = llm_post_auth_failure(_request(), None)
    assert resp is not None
    assert resp.status_code == 503
    assert resp.body == _UNCONFIGURED_BODY
    assert PROXY_UNCONFIGURED_DETAIL in resp.body.decode()


def test_c11_healthz_unguarded_when_secret_unconfigured() -> None:
    """D40 smoke: ``/healthz`` stays open when the secret is unset."""
    assert llm_post_auth_failure(_request(path="/healthz"), None) is None


@pytest.mark.anyio
async def test_c11_proxy_app_503_on_guarded_route_without_secret() -> None:
    """D40 smoke: ASGI app returns 503 on guarded routes without a secret."""
    app = create_app(
        settings=ProxySettings(anthropic_api_key="ak", openai_api_key="ok"),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/web/fetch", json={"url": "https://example.com"})
    assert resp.status_code == 503
    assert resp.json()["detail"] == PROXY_UNCONFIGURED_DETAIL


def test_c11_allow_unauthenticated_opt_in_still_exported() -> None:
    """D40 smoke: boot-warning helper for the explicit opt-in remains importable."""
    assert callable(log_proxy_allow_unauthenticated_boot_warning)
