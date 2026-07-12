"""Optional daemon / service-manager tests (`specs/23-cli.md` §10.4)."""

from __future__ import annotations

import pytest


@pytest.mark.skip(
    reason="Requires launchd/systemd user units; see tests/fixtures/cli/README.md",
)
def test_sevn_gateway_restart_placeholder() -> None:
    """Reserved for paired ``sevn gateway`` / ``sevn proxy`` subprocess smoke."""

    return
