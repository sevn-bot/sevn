"""Human-verification resolver for the CLI."""

from __future__ import annotations

import os
import sys

from proton_cli.hv import helper as hv_helper
from proton_cli.proton.errors import ErrHVUnavailable, HumanVerificationError


def cli_hv_resolver(hv_err: HumanVerificationError) -> tuple[str, str]:
    """Resolve a Proton HV challenge.

    Order of resolution:
    1. ``PROTON_HV_TOKEN`` / ``PROTON_HV_TYPE`` environment variables
    2. Embedded/desktop ``proton-cli-hv`` helper (when available)
    3. Print challenge URL and raise :class:`~proton_cli.proton.errors.ErrHVUnavailable`
    """
    token = os.environ.get("PROTON_HV_TOKEN", "").strip()
    kind = os.environ.get("PROTON_HV_TYPE", "captcha").strip() or "captcha"
    if token:
        return token, kind

    methods = hv_err.methods or ["captcha"]
    if "captcha" in methods and hv_err.token:
        try:
            solved = hv_helper.resolve_with_helper(hv_err.token)
            if ":" in solved:
                _, response = solved.split(":", 1)
                return response.strip(), "captcha"
            return solved, "captcha"
        except hv_helper.HVCancelledError as exc:
            raise ErrHVUnavailable(str(exc)) from exc
        except hv_helper.HVUnavailableError:
            pass
        except Exception:
            pass

    if "captcha" in methods and hv_err.web_url:
        sys.stderr.write(f"Complete verification at {hv_err.web_url}, then set PROTON_HV_TOKEN.\n")
    raise ErrHVUnavailable(str(hv_err))
