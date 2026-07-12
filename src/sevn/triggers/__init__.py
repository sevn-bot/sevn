"""Non-interactive triggers (`specs/30-non-interactive-triggers.md`).

Public entrypoints are mounted from :mod:`sevn.gateway.http_server`.
"""

from sevn.triggers.dispatcher import (
    TriggerDispatchGate,
    dispatch_notify_only,
    dispatch_run,
)
from sevn.triggers.hooks_protocol import TriggerPluginHookSurface
from sevn.triggers.request import DispatchRequest, NotifyHandle, RunHandle

__all__ = [
    "DispatchRequest",
    "NotifyHandle",
    "RunHandle",
    "TriggerDispatchGate",
    "TriggerPluginHookSurface",
    "dispatch_notify_only",
    "dispatch_run",
]
