"""Stable import path removed — use :mod:`sevn.triggers.operator_notify`.

This module previously exposed a sync ``message_tool`` that only logged and
returned a fake ``ok`` envelope (Thermos correctness). Callers must use
:func:`sevn.triggers.operator_notify.deliver_operator_notify` (or the agent
async :func:`sevn.tools.outbound.message_tool` with a real ``ToolContext``).
"""

from __future__ import annotations

from sevn.triggers.operator_notify import deliver_operator_notify

__all__ = ["deliver_operator_notify"]
