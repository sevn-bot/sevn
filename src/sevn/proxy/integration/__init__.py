"""Egress proxy third-party integration dispatch (`specs/29-cursor-cloud-agent.md`).

Module: sevn.proxy.integration
Depends: sevn.proxy.integration.router

Exports:
    integration_post — ASGI handler for ``POST /integration``.
"""

from __future__ import annotations

from sevn.proxy.integration.router import integration_post

__all__ = ["integration_post"]
