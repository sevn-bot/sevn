"""W6 unit tests for sandbox spawn session-token resolution (#168, D12)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from sevn.proxy.auth import SESSION_SCOPE_SANDBOX, mint_session_token, validate_session_token
from sevn.proxy.bootstrap_secret import ensure_proxy_shared_secret_file
from sevn.security.sandbox_errors import SandboxConfigurationError
from sevn.security.sandbox_runtime import _resolve_spawn_session_token

_SIGNING_KEY = "spawn-test-signing-key-at-least-32-chars"


def test_resolve_spawn_session_token_preserves_existing_env_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without a resolved signing key the function trusts the env token as-is.

    PR #245 Codex finding 6 adds run/container binding checks when a secret
    resolves; this test pins the no-secret branch (no ``SEVN_PROXY_SHARED_SECRET``
    env, no ``SEVN_HOME`` generate-once file, no injected ``signing_key``).
    """
    monkeypatch.delenv("SEVN_PROXY_SHARED_SECRET", raising=False)
    assert (
        _resolve_spawn_session_token(
            run_id="run-keep",
            env={"SEVN_SESSION_TOKEN": "pre-minted-token"},
        )
        == "pre-minted-token"
    )


def test_resolve_spawn_session_token_mints_sandbox_scope_when_secret_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SEVN_PROXY_SHARED_SECRET", _SIGNING_KEY)
    token = _resolve_spawn_session_token(run_id="run-mint", env={})
    assert token.startswith("v1.")
    assert validate_session_token(token, signing_key=_SIGNING_KEY, path="/web/fetch") is True
    assert (
        validate_session_token(
            token,
            signing_key=_SIGNING_KEY,
            path="/llm/openai/chat/completions",
        )
        is False
    )


def test_resolve_spawn_session_token_raises_without_secret(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fail-closed: no env and no generate-once file → SandboxConfigurationError (Thermos T2)."""
    monkeypatch.delenv("SEVN_PROXY_SHARED_SECRET", raising=False)
    monkeypatch.setenv("SEVN_HOME", str(tmp_path))
    with pytest.raises(SandboxConfigurationError, match="SEVN_PROXY_SHARED_SECRET"):
        _resolve_spawn_session_token(run_id="run-empty", env={})


def test_resolve_spawn_session_token_mints_from_generate_once_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Compose default: blank env + generate-once file under SEVN_HOME still mints (T2)."""
    monkeypatch.delenv("SEVN_PROXY_SHARED_SECRET", raising=False)
    monkeypatch.setenv("SEVN_HOME", str(tmp_path))
    ensure_proxy_shared_secret_file(tmp_path, secret=_SIGNING_KEY)
    token = _resolve_spawn_session_token(run_id="run-file", env={})
    assert token.startswith("v1.")
    assert validate_session_token(token, signing_key=_SIGNING_KEY, path="/web/fetch") is True


def test_resolve_spawn_session_token_mints_with_injected_signing_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Chain-only installs: injected signing_key mints without env/file (D41)."""
    monkeypatch.delenv("SEVN_PROXY_SHARED_SECRET", raising=False)
    monkeypatch.setenv("SEVN_HOME", str(tmp_path))
    chain_secret = "chain-only-spawn-signing-key-32chars!"
    token = _resolve_spawn_session_token(
        run_id="run-chain",
        env={},
        signing_key=chain_secret,
    )
    assert token.startswith("v1.")
    assert validate_session_token(token, signing_key=chain_secret, path="/web/fetch") is True
    assert "SEVN_PROXY_SHARED_SECRET" not in os.environ


def test_assemble_spawn_child_env_uses_injected_signing_key_without_leaking(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Injected chain secret mints a token and is not copied into child env."""
    from sevn.security.sandbox_runtime import _assemble_spawn_child_env

    monkeypatch.delenv("SEVN_PROXY_SHARED_SECRET", raising=False)
    monkeypatch.setenv("SEVN_HOME", str(tmp_path))
    chain_secret = "assemble-chain-only-signing-key-32ch!"
    env = _assemble_spawn_child_env(
        run_id="run-assemble-chain",
        env={"SEVN_PROXY_URL": "http://127.0.0.1:9"},
        workspace_mount_path="/w",
        signing_key=chain_secret,
    )
    assert set(env.keys()) == {
        "SEVN_PROXY_URL",
        "SEVN_SESSION_TOKEN",
        "SEVN_WORKSPACE",
        "SEVN_PROXY_BINDING_SIG",
    }
    assert "SEVN_PROXY_SHARED_SECRET" not in env
    assert validate_session_token(
        env["SEVN_SESSION_TOKEN"],
        signing_key=chain_secret,
        path="/web/fetch",
    )


def test_resolve_spawn_session_token_embeds_run_id_in_minted_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SEVN_PROXY_SHARED_SECRET", _SIGNING_KEY)
    run_id = "run-correlation-42"
    token = _resolve_spawn_session_token(run_id=run_id, env={})
    expected = mint_session_token(
        signing_key=_SIGNING_KEY,
        scope=SESSION_SCOPE_SANDBOX,
        run_id=run_id,
    )
    assert token == expected


def test_resolve_spawn_session_token_rejects_existing_token_for_other_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An existing token minted for a different ``run_id`` is rejected (PR #245 Codex finding 6).

    Without the binding re-check, a sandbox could accept a session token left in
    the spawn env by a previous run and emit its own claims, letting an old
    credential extend into a fresh run's binding.
    """
    monkeypatch.setenv("SEVN_PROXY_SHARED_SECRET", _SIGNING_KEY)
    other_run_token = mint_session_token(
        signing_key=_SIGNING_KEY,
        scope=SESSION_SCOPE_SANDBOX,
        run_id="run-other",
        container_id="ctr-other",
    )
    with pytest.raises(SandboxConfigurationError, match="different run/container"):
        _resolve_spawn_session_token(
            run_id="run-current",
            env={"SEVN_SESSION_TOKEN": other_run_token},
            container_id="ctr-current",
        )


def test_resolve_spawn_session_token_rejects_existing_token_for_other_container(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An existing token minted for a different ``container_id`` is rejected."""
    monkeypatch.setenv("SEVN_PROXY_SHARED_SECRET", _SIGNING_KEY)
    other_container_token = mint_session_token(
        signing_key=_SIGNING_KEY,
        scope=SESSION_SCOPE_SANDBOX,
        run_id="run-shared",
        container_id="ctr-other",
    )
    with pytest.raises(SandboxConfigurationError, match="different run/container"):
        _resolve_spawn_session_token(
            run_id="run-shared",
            env={"SEVN_SESSION_TOKEN": other_container_token},
            container_id="ctr-current",
        )


def test_resolve_spawn_session_token_accepts_existing_token_with_matching_bindings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An existing token whose ``run_id`` / ``container_id`` match the spawn is kept."""
    monkeypatch.setenv("SEVN_PROXY_SHARED_SECRET", _SIGNING_KEY)
    matching_token = mint_session_token(
        signing_key=_SIGNING_KEY,
        scope=SESSION_SCOPE_SANDBOX,
        run_id="run-shared",
        container_id="ctr-shared",
    )
    assert (
        _resolve_spawn_session_token(
            run_id="run-shared",
            env={"SEVN_SESSION_TOKEN": matching_token},
            container_id="ctr-shared",
        )
        == matching_token
    )


def test_assemble_spawn_child_env_emits_precomputed_binding_signature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RED: sandbox child env carries the PoP binding signature so job-ops can emit it.

    PR #245 mergecraft follow-up (4b0049b9840bcde02f488190): the E-PoP HMAC
    signature over ``container_id=<cid>\\nrun_id=<rid>`` is keyed by
    ``SEVN_PROXY_SHARED_SECRET``. ``build_sandbox_child_env`` deliberately
    strips that secret from the child env, so the sandbox-side job-ops helper
    cannot recompute the signature itself. Without the gateway pre-computing
    the signature and shipping it in the child env, every sandbox-originated
    egress call is rejected with ``401``. The gateway computes the signature
    at spawn time and emits it as ``SEVN_PROXY_BINDING_SIG``; the job-ops
    helper reads that key and emits ``X-Sevn-Binding-Signature`` directly.
    """
    import base64
    import hashlib
    import hmac
    import json

    from sevn.security.sandbox_runtime import _assemble_spawn_child_env

    monkeypatch.delenv("SEVN_PROXY_SHARED_SECRET", raising=False)
    chain_secret = "assemble-red-binding-sig-signing-key-32!"
    run_id = "run-red-binding-sig"
    env = _assemble_spawn_child_env(
        run_id=run_id,
        env={"SEVN_PROXY_URL": "http://127.0.0.1:9"},
        workspace_mount_path="/w",
        signing_key=chain_secret,
    )
    # The child env must carry the pre-computed binding signature so the
    # sandbox child (no shared secret) can emit it as ``X-Sevn-Binding-Signature``.
    assert "SEVN_PROXY_BINDING_SIG" in env
    token = env["SEVN_SESSION_TOKEN"]
    assert validate_session_token(token, signing_key=chain_secret, path="/web/fetch") is True
    # Decode the minted token so the test pins the *pair* the signature
    # was computed over (the gateway's auto-generated ``bind_id`` is
    # embedded as ``container_id`` in the payload).
    parts = token.split(".")
    padded = parts[1] + "=" * (-len(parts[1]) % 4)
    payload = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
    container_id = payload["container_id"]
    expected_sig = hmac.new(
        chain_secret.encode(),
        f"container_id={container_id}\nrun_id={run_id}".encode(),
        hashlib.sha256,
    ).hexdigest()
    assert env["SEVN_PROXY_BINDING_SIG"] == expected_sig


@pytest.mark.anyio
async def test_sandbox_child_egress_admitted_with_precomputed_binding_sig(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RED end-to-end: a sandbox child egress call is admitted by the proxy.

    The mergecraft review found that ``build_sandbox_child_env`` strips
    ``SEVN_PROXY_SHARED_SECRET``, so the job-ops ``_proxy_headers`` helper
    never emits ``X-Sevn-Binding-Signature`` and the proxy rejects the call
    with ``401``. This test exercises the spawn→child-env→proxy path with a
    sandbox-only child (no shared secret in env) and asserts the proxy admits
    the request. Fails RED today; passes GREEN after the spawn seam emits
    ``SEVN_PROXY_BINDING_SIG`` and job-ops reads it.
    """
    import httpx

    from sevn.proxy.app import create_app
    from sevn.proxy.settings import ProxySettings
    from sevn.security.sandbox_runtime import build_sandbox_child_env

    chain_secret = "sandbox-child-egress-red-binding-sig-32!!"
    run_id = "run-sandbox-child-egress"
    bind_id = "sb-red-binding-sig-0000000000000000"
    monkeypatch.delenv("SEVN_PROXY_SHARED_SECRET", raising=False)
    # Mint via the spawn seam so the token carries ``container_id=bind_id``.
    token = _resolve_spawn_session_token(
        run_id=run_id,
        env={},
        signing_key=chain_secret,
        container_id=bind_id,
    )
    env = build_sandbox_child_env(
        proxy_url="http://127.0.0.1:9",
        session_token=token,
        workspace_mount_path="/w",
        binding_signing_key=chain_secret,
    )
    # Sanity: child env must not contain the shared secret.
    assert "SEVN_PROXY_SHARED_SECRET" not in env
    # RED gate: child env must carry the pre-computed binding signature.
    assert "SEVN_PROXY_BINDING_SIG" in env

    # End-to-end: the proxy (with the shared secret in its own settings)
    # admits the sandbox child request when job-ops emits the pre-computed
    # signature verbatim from ``SEVN_PROXY_BINDING_SIG``.
    app = create_app(
        settings=ProxySettings(
            anthropic_api_key="ak",
            openai_api_key="ok",
            proxy_shared_secret=chain_secret,
        ),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # Simulate the job-ops helper reading the pre-computed signature from
        # the child env and emitting it as ``X-Sevn-Binding-Signature``.
        resp = await client.post(
            "/web/fetch",
            json={"url": "https://example.com/"},
            headers={
                "X-Sevn-Session-Token": env["SEVN_SESSION_TOKEN"],
                "X-Sevn-Run-Id": run_id,
                "X-Sevn-Container-Id": bind_id,
                "X-Sevn-Binding-Signature": env["SEVN_PROXY_BINDING_SIG"],
            },
        )
    assert resp.status_code != 401, (
        f"sandbox-originated egress must be admitted; got {resp.status_code}: "
        f"{resp.text!r}. The PoP binding signature must be pre-computed by "
        f"the gateway at spawn time and shipped via SEVN_PROXY_BINDING_SIG, "
        f"not recomputed in the sandbox child (which has no shared secret)."
    )


@pytest.mark.anyio
async def test_sandbox_child_llm_egress_admitted_with_precomputed_binding_sig(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RED: sandbox child /llm/* egress is admitted (production job-ops ``complete_json``).

    PR #245 mergecraft follow-up (Codex reviewId 4889131359, run 31264795983):
    ``complete_json`` in ``src/sevn/data/bundled_skills/core/job-ops/scripts/lib/llm.py``
    routes through ``/llm/openai/chat/completions`` (and ``/llm/anthropic/messages``,
    ``/llm/openai/responses``, ``/llm/bedrock/converse``) with the sandbox-scoped
    session token + the pre-computed PoP binding signature from
    ``SEVN_PROXY_BINDING_SIG``. The new ``X-Sevn-Binding-Signature`` requirement
    landed for the sandbox family (W18 follow-up) but the proxy-side scope check
    still rejects ``sandbox``-scoped tokens on ``/llm/*``, returning 401 in
    production even when the binding signature is valid. This test boots the
    proxy with the shared secret, simulates the job-ops child env (no shared
    secret, ``SEVN_PROXY_BINDING_SIG`` present), and POSTs to
    ``/llm/openai/chat/completions`` — the proxy must NOT return 401.
    """
    import httpx

    from sevn.proxy.app import create_app
    from sevn.proxy.settings import ProxySettings
    from sevn.security.sandbox_runtime import build_sandbox_child_env

    chain_secret = "sandbox-child-llm-red-binding-sig-32chars!"
    run_id = "run-sandbox-child-llm"
    bind_id = "sb-red-llm-binding-sig-00000000000000"
    monkeypatch.delenv("SEVN_PROXY_SHARED_SECRET", raising=False)
    token = _resolve_spawn_session_token(
        run_id=run_id,
        env={},
        signing_key=chain_secret,
        container_id=bind_id,
    )
    env = build_sandbox_child_env(
        proxy_url="http://127.0.0.1:9",
        session_token=token,
        workspace_mount_path="/w",
        binding_signing_key=chain_secret,
    )
    # Sanity: the sandbox child env must not leak the shared secret; the
    # binding signature is shipped via ``SEVN_PROXY_BINDING_SIG``.
    assert "SEVN_PROXY_SHARED_SECRET" not in env
    assert "SEVN_PROXY_BINDING_SIG" in env

    app = create_app(
        settings=ProxySettings(
            anthropic_api_key="ak",
            openai_api_key="ok",
            proxy_shared_secret=chain_secret,
        ),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/llm/openai/chat/completions",
            json={
                "model": "ok-model",
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 16,
            },
            headers={
                "X-Sevn-Session-Token": env["SEVN_SESSION_TOKEN"],
                "X-Sevn-Run-Id": run_id,
                "X-Sevn-Container-Id": bind_id,
                "X-Sevn-Binding-Signature": env["SEVN_PROXY_BINDING_SIG"],
            },
        )
    # The proxy-auth 401 surface is a stable discriminator: it always returns
    # ``{"detail":"unauthorized"}`` with no upstream call. An upstream 401 (real
    # provider "invalid_api_key") is a different body and means the proxy
    # admitted the request correctly.
    assert resp.text != '{"detail":"unauthorized"}', (
        f"sandbox-originated /llm/* egress must be admitted by the proxy guard; "
        f"got proxy-auth 401 body: {resp.text!r}. The proxy must accept a "
        f"sandbox-scoped session token on /llm/* when paired with a valid "
        f"X-Sevn-Binding-Signature, so the production job-ops ``complete_json`` "
        f"path works end-to-end. (Codex reviewId 4889131359, run 31264795983)"
    )


@pytest.mark.anyio
async def test_sandbox_child_llm_egress_rejected_without_binding_signature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GREEN (security): a sandbox token on /llm/* without PoP binding sig is 401.

    The new ``/llm/*`` admission branch in ``llm_post_auth_failure`` requires a
    valid ``X-Sevn-Binding-Signature``. A missing signature must fail closed —
    the same defense-in-depth applied to the ``/web/*`` family — so a leaked
    sandbox token alone cannot reach ``/llm/*`` (PR #245 Codex reviewId
    4889131359, run 31264795983).
    """
    import httpx

    from sevn.proxy.app import create_app
    from sevn.proxy.settings import ProxySettings
    from sevn.security.sandbox_runtime import build_sandbox_child_env

    chain_secret = "sandbox-child-llm-green-binding-sig-32ch!"
    run_id = "run-sandbox-child-llm-nosig"
    bind_id = "sb-green-llm-nosig-00000000000000000"
    monkeypatch.delenv("SEVN_PROXY_SHARED_SECRET", raising=False)
    token = _resolve_spawn_session_token(
        run_id=run_id,
        env={},
        signing_key=chain_secret,
        container_id=bind_id,
    )
    env = build_sandbox_child_env(
        proxy_url="http://127.0.0.1:9",
        session_token=token,
        workspace_mount_path="/w",
        binding_signing_key=chain_secret,
    )
    app = create_app(
        settings=ProxySettings(
            anthropic_api_key="ak",
            openai_api_key="ok",
            proxy_shared_secret=chain_secret,
        ),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # No X-Sevn-Binding-Signature header — must be rejected.
        resp = await client.post(
            "/llm/openai/chat/completions",
            json={
                "model": "ok-model",
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 16,
            },
            headers={
                "X-Sevn-Session-Token": env["SEVN_SESSION_TOKEN"],
                "X-Sevn-Run-Id": run_id,
                "X-Sevn-Container-Id": bind_id,
            },
        )
    assert resp.status_code == 401, (
        f"sandbox /llm/* without binding signature must be 401; got {resp.status_code}: "
        f"{resp.text!r}. Without the PoP binding signature, a leaked sandbox "
        f"token must not be able to reach /llm/* (PR #245 Codex reviewId "
        f"4889131359, run 31264795983)."
    )
    assert resp.text == '{"detail":"unauthorized"}'

    # Wrong binding signature must also be rejected.
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp_wrong = await client.post(
            "/llm/openai/chat/completions",
            json={
                "model": "ok-model",
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 16,
            },
            headers={
                "X-Sevn-Session-Token": env["SEVN_SESSION_TOKEN"],
                "X-Sevn-Run-Id": run_id,
                "X-Sevn-Container-Id": bind_id,
                "X-Sevn-Binding-Signature": "0" * 64,  # wrong
            },
        )
    assert resp_wrong.status_code == 401
    assert resp_wrong.text == '{"detail":"unauthorized"}'
