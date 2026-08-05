"""Sandbox suite fixtures — process-lifetime digest-cache isolation (D43 / Batch B).

``_SANDBOX_IMAGE_DIGEST_CACHE`` is process-scoped. Shared mock tags across pin and
pull-cache suites (and within a file under pytest-randomly) must not leak. Keep this
in the package conftest so ``test_post_audit_image_pin_w4_red.py`` stays unmodified.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def _clear_sandbox_image_digest_cache() -> Iterator[None]:
    """Clear the W8 process-lifetime digest cache around every sandbox test."""
    from sevn.security import sandbox_runtime as mod

    mod._SANDBOX_IMAGE_DIGEST_CACHE.clear()
    yield
    mod._SANDBOX_IMAGE_DIGEST_CACHE.clear()
