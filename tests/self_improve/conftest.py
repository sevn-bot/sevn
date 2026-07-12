"""Force in-process eval for unit tests (plan E-0A / decision E8)."""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def _self_improve_eval_in_process() -> Iterator[None]:
    """Set in-process eval + triager/patch-author stubs for graph tests (E-0A / E-2)."""
    prev_in_process = os.environ.get("SEVN_IMPROVE_EVAL_IN_PROCESS")
    prev_stub = os.environ.get("SEVN_TRIAGER_STUB")
    prev_patch_stub = os.environ.get("SEVN_PATCH_AUTHOR_STUB")
    os.environ["SEVN_IMPROVE_EVAL_IN_PROCESS"] = "1"
    os.environ["SEVN_TRIAGER_STUB"] = "1"
    os.environ["SEVN_PATCH_AUTHOR_STUB"] = "1"
    yield
    if prev_in_process is None:
        os.environ.pop("SEVN_IMPROVE_EVAL_IN_PROCESS", None)
    else:
        os.environ["SEVN_IMPROVE_EVAL_IN_PROCESS"] = prev_in_process
    if prev_stub is None:
        os.environ.pop("SEVN_TRIAGER_STUB", None)
    else:
        os.environ["SEVN_TRIAGER_STUB"] = prev_stub
    if prev_patch_stub is None:
        os.environ.pop("SEVN_PATCH_AUTHOR_STUB", None)
    else:
        os.environ["SEVN_PATCH_AUTHOR_STUB"] = prev_patch_stub
