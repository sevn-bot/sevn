"""Shared literals for bot and agent records (D2, D9, D13)."""

from __future__ import annotations

from typing import Literal

type RuntimeName = Literal["pydantic_ai", "claude"]
type AccessName = Literal["workspace", "full", "isolated"]
type ApprovalPolicy = Literal["ask", "auto", "allow_all"]
type NetworkFlag = Literal["on", "off"]
type AgentStatus = Literal["running", "waiting", "idle", "done", "archived"]
