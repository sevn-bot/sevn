"""Human-verification resolver for the CLI."""

from __future__ import annotations

import os
import sys

from proton_cli.proton.errors import ErrHVUnavailable, HumanVerificationError


def cli_hv_resolver(hv_err: HumanVerificationError) -> tuple[str, str]:
    """Resolve a Proton HV challenge.

    Uses ``PROTON_HV_TOKEN`` (and optional ``PROTON_HV_TYPE``, default ``captcha``)
    when set. Otherwise prints the challenge URL to stderr and raises
    :class:`~proton_cli.proton.errors.ErrHVUnavailable`.
    """
    token = os.environ.get("PROTON_HV_TOKEN", "").strip()
    kind = os.environ.get("PROTON_HV_TYPE", "captcha").strip() or "captcha"
    if token:
        return token, kind

    methods = hv_err.methods or ["captcha"]
    if "captcha" in methods and hv_err.web_url:
        sys.stderr.write(f"Complete verification at {hv_err.web_url}, then set PROTON_HV_TOKEN.\n")
    raise ErrHVUnavailable(str(hv_err))
