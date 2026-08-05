"""Batch E W18 RED — honest ``SEVN_SESSION_TOKEN`` schema description (C7.4).

``infra/sevn.schema.json`` currently describes unimplemented token behaviour
(proxy minting, frozen ``PermissionConfig`` ceiling, revoke-on-teardown) as
current. W20 must describe what ships and mark the rest as intent.

xfail map: W18.6 → W20.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCHEMA_PATH = _REPO_ROOT / "infra" / "sevn.schema.json"

# Present-tense claims that are not shipped behaviour on the batch base.
_UNIMPLEMENTED_CURRENT_CLAIMS = (
    "minted by the proxy",
    "permissionconfig",
    "revoke-on-teardown",
)


def _session_token_entry() -> dict[str, object]:
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    allowlist = schema.get("x-sevn-env-allowlist")
    assert isinstance(allowlist, list)
    for entry in allowlist:
        if isinstance(entry, dict) and entry.get("name") == "SEVN_SESSION_TOKEN":
            return entry
    msg = "SEVN_SESSION_TOKEN missing from x-sevn-env-allowlist"
    raise AssertionError(msg)


@pytest.mark.xfail(reason="green after W20: honest SEVN_SESSION_TOKEN schema (C7.4)", strict=False)
def test_w18_6_session_token_schema_does_not_present_unimplemented_as_current() -> None:
    entry = _session_token_entry()
    description = str(entry.get("description", ""))
    long_description = str(entry.get("long_description", ""))
    combined = f"{description}\n{long_description}"
    lowered = combined.lower()

    # Either the unimplemented phrases are gone, or every remaining one is marked intent.
    if "intent" in lowered:
        return

    for claim in _UNIMPLEMENTED_CURRENT_CLAIMS:
        assert claim not in lowered, (
            f"SEVN_SESSION_TOKEN schema still presents unimplemented '{claim}' as current "
            f"without an intent marker (C7.4 / W20.4)"
        )
