"""Provider-adaptive WebSearch/WebFetch + Thinking for tier B (W7).

Local fallbacks re-enter :meth:`sevn.tools.base.ToolExecutor.dispatch` via registry
``Tool`` runners from :mod:`sevn.agent.adapters.tier_b_tools`.

Module: sevn.agent.adapters.tier_b_capabilities
Depends: pydantic_ai, sevn.agent.adapters.native_model, sevn.config.llm_params

Exports:
    WebEgressDomainPolicy — allowed/blocked hostname lists for web capabilities.
    resolve_web_egress_domain_policy — read domain policy from workspace config.
    provider_supports_native_web_search — whether native provider search is available.
    provider_supports_native_web_fetch — whether native provider fetch is available.
    resolve_thinking_effort — map ``minimax_thinking`` config to ``Thinking`` effort.
    build_serp_local_tool — ``serp`` local fallback via ``ToolExecutor``.
    build_get_page_content_local_tool — ``get_page_content`` local fallback via ``ToolExecutor``.
    make_codemode_web_registry_tool — web registry ``Tool`` with egress policy + ``code_mode=True``.
    url_passes_domain_policy — hostname allow/block check for one URL.
    build_web_thinking_extra_capabilities — optional W7 capabilities for one turn.
    registry_tool_names_owned_by_web_capabilities — registry names delegated to W7 caps.

Examples:
    >>> from sevn.config.model_resolution import is_minimax_catalog_model
    >>> provider_supports_native_web_search("minimax/MiniMax-M2", None)
    False
    >>> provider_supports_native_web_search("anthropic/claude-sonnet-4-20250514", None)
    True
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, cast
from urllib.parse import urlparse

from pydantic_ai import RunContext, Tool
from pydantic_ai.capabilities import Thinking, WebFetch, WebSearch

from sevn.agent.adapters.native_model import _catalog_provider_family
from sevn.agent.adapters.tier_b_tools import (
    _dispatch_tool,
    tool_definition_to_args_model,
)
from sevn.config.llm_params import resolve_minimax_thinking_request
from sevn.config.model_resolution import is_minimax_catalog_model
from sevn.config.sections.providers import providers_section_dict
from sevn.tools.base import enveloped_failure
from sevn.tools.codes import ToolResultCode

if TYPE_CHECKING:
    from collections.abc import Sequence

    from pydantic_ai.capabilities.abstract import AbstractCapability

    from sevn.agent.executors.b_types import BTierDeps
    from sevn.config.workspace_config import WorkspaceConfig
    from sevn.tools.base import ToolDefinition, ToolExecutor

ThinkingEffort = Literal["minimal", "low", "medium", "high", "xhigh"]
ThinkingLevel = bool | ThinkingEffort
_WEB_TOOL_NAMES: frozenset[str] = frozenset({"serp", "web_search"})
_FETCH_TOOL_NAMES: frozenset[str] = frozenset({"get_page_content", "web_fetch"})
CODEMODE_LOCAL_WEB_TOOL_NAMES: frozenset[str] = _WEB_TOOL_NAMES | _FETCH_TOOL_NAMES
"""Registry web tools routed locally through ``run_code`` when CodeMode is on (W8+B)."""


@dataclass(frozen=True)
class WebEgressDomainPolicy:
    """Hostname allow/block lists for web search and fetch capabilities."""

    allowed_domains: tuple[str, ...] = ()
    blocked_domains: tuple[str, ...] = ()


def _read_domain_list(raw: object) -> tuple[str, ...]:
    """Normalize a config domain list to bare hostnames.

    Args:
        raw (object): JSON list fragment or ``None``.

    Returns:
        tuple[str, ...]: Lowercased hostname entries.

    Examples:
        >>> _read_domain_list(["Example.COM", " docs.python.org "])
        ('example.com', 'docs.python.org')
        >>> _read_domain_list(None)
        ()
    """
    if not isinstance(raw, list):
        return ()
    out: list[str] = []
    for item in raw:
        if isinstance(item, str) and item.strip():
            out.append(item.strip().lower().lstrip("."))
    return tuple(out)


def _nested_web_domains(section: object) -> WebEgressDomainPolicy | None:
    """Parse ``allowed_domains`` / ``blocked_domains`` from one config object.

    Args:
        section (object): Mapping that may contain a ``web`` subtree.

    Returns:
        WebEgressDomainPolicy | None: Parsed policy or ``None`` when absent.

    Examples:
        >>> _nested_web_domains({"web": {"blocked_domains": ["evil.com"]}})
        WebEgressDomainPolicy(allowed_domains=(), blocked_domains=('evil.com',))
    """
    if not isinstance(section, dict):
        return None
    web = section.get("web")
    if not isinstance(web, dict):
        return None
    allowed = _read_domain_list(web.get("allowed_domains"))
    blocked = _read_domain_list(web.get("blocked_domains"))
    if not allowed and not blocked:
        return None
    return WebEgressDomainPolicy(allowed_domains=allowed, blocked_domains=blocked)


def resolve_web_egress_domain_policy(workspace: WorkspaceConfig) -> WebEgressDomainPolicy:
    """Resolve web domain allow/block lists from workspace config extras.

    Reads ``agent.web.{allowed,blocked}_domains`` then ``proxy.web.*`` when present.

    Args:
        workspace (WorkspaceConfig): Parsed ``sevn.json``.

    Returns:
        WebEgressDomainPolicy: Policy (empty lists when unset).

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> resolve_web_egress_domain_policy(WorkspaceConfig.minimal())
        WebEgressDomainPolicy(allowed_domains=(), blocked_domains=())
    """
    if workspace.agent is not None:
        policy = _nested_web_domains(workspace.agent.model_dump(mode="python"))
        if policy is not None:
            return policy
    extra = workspace.model_extra or {}
    for key in ("agent", "proxy"):
        policy = _nested_web_domains(extra.get(key))
        if policy is not None:
            return policy
    if isinstance(workspace.proxy, dict):
        policy = _nested_web_domains(workspace.proxy)
        if policy is not None:
            return policy
    return WebEgressDomainPolicy()


def provider_supports_native_web_search(
    model_id: str,
    providers_obj: dict[str, Any] | None,
) -> bool:
    """Return whether the resolved model may use provider-native web search.

    MiniMax-via-gateway and Bedrock do not expose native search; Anthropic and OpenAI do.

    Args:
        model_id (str): Catalog model id for the tier-B slot.
        providers_obj (dict[str, Any] | None): Merged ``providers`` block.

    Returns:
        bool: ``True`` when native ``WebSearchTool`` should be attempted.

    Examples:
        >>> provider_supports_native_web_search("minimax/MiniMax-M2", None)
        False
        >>> provider_supports_native_web_search("anthropic/claude-sonnet-4-20250514", None)
        True
    """
    if is_minimax_catalog_model(model_id):
        return False
    family = _catalog_provider_family(model_id, providers_obj)
    return family in {"anthropic", "openai"}


def provider_supports_native_web_fetch(
    model_id: str,
    providers_obj: dict[str, Any] | None,
) -> bool:
    """Return whether the resolved model may use provider-native URL fetch.

    Args:
        model_id (str): Catalog model id for the tier-B slot.
        providers_obj (dict[str, Any] | None): Merged ``providers`` block.

    Returns:
        bool: ``True`` when native ``WebFetchTool`` should be attempted.

    Examples:
        >>> provider_supports_native_web_fetch("bedrock/anthropic.claude-3-haiku", None)
        False
        >>> provider_supports_native_web_fetch("anthropic/claude-sonnet-4-20250514", None)
        True
    """
    if is_minimax_catalog_model(model_id):
        return False
    return _catalog_provider_family(model_id, providers_obj) == "anthropic"


def _host_matches_domain(host: str, domain: str) -> bool:
    """Return True when ``host`` equals or is a subdomain of ``domain``.

    Args:
        host (str): Lowercased hostname.
        domain (str): Allow/block entry (bare hostname).

    Returns:
        bool: Suffix or exact match.

    Examples:
        >>> _host_matches_domain("docs.python.org", "python.org")
        True
        >>> _host_matches_domain("evil.com", "python.org")
        False
    """
    h = host.lower().rstrip(".")
    d = domain.lower().strip().lstrip(".")
    return h == d or h.endswith("." + d)


def url_passes_domain_policy(url: str, policy: WebEgressDomainPolicy) -> bool:
    """Return False when ``url`` violates allow/block hostname policy.

    Args:
        url (str): Candidate http(s) URL.
        policy (WebEgressDomainPolicy): Active egress domain policy.

    Returns:
        bool: ``True`` when the host is allowed (or policy is empty).

    Examples:
        >>> pol = WebEgressDomainPolicy(blocked_domains=("evil.com",))
        >>> url_passes_domain_policy("https://docs.python.org/3/", pol)
        True
        >>> url_passes_domain_policy("https://evil.com/x", pol)
        False
    """
    host = urlparse(url.strip()).hostname
    if not host:
        return False
    h = host.lower()
    for blocked in policy.blocked_domains:
        if _host_matches_domain(h, blocked):
            return False
    if policy.allowed_domains:
        return any(_host_matches_domain(h, allowed) for allowed in policy.allowed_domains)
    return True


def _filter_serp_envelope(raw: str, policy: WebEgressDomainPolicy) -> str:
    """Drop serp result rows whose URLs violate domain policy.

    Args:
        raw (str): §3.1 envelope string from ``serp`` dispatch.
        policy (WebEgressDomainPolicy): Domain policy to enforce.

    Returns:
        str: Filtered envelope (unchanged when policy is empty or parse fails).

    Examples:
        >>> import json
        >>> from sevn.tools.base import enveloped_success
        >>> payload = {
        ...     "query": "q",
        ...     "count": 2,
        ...     "results": [
        ...         {"title": "a", "url": "https://good.com", "description": ""},
        ...         {"title": "b", "url": "https://evil.com", "description": ""},
        ...     ],
        ... }
        >>> pol = WebEgressDomainPolicy(blocked_domains=("evil.com",))
        >>> out = _filter_serp_envelope(enveloped_success(payload), pol)
        >>> json.loads(out)["data"]["count"]
        1
    """
    if not policy.allowed_domains and not policy.blocked_domains:
        return raw
    try:
        blob = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    data = blob.get("data")
    if not isinstance(data, dict):
        return raw
    results = data.get("results")
    if not isinstance(results, list):
        return raw
    kept = [
        row
        for row in results
        if isinstance(row, dict)
        and isinstance(row.get("url"), str)
        and url_passes_domain_policy(str(row["url"]), policy)
    ]
    data["results"] = kept
    data["count"] = len(kept)
    blob["data"] = data
    return json.dumps(blob, separators=(",", ":"))


def _registry_definition(executor: ToolExecutor, name: str) -> ToolDefinition | None:
    """Look up one registry tool definition by name.

    Args:
        executor (ToolExecutor): Active registry executor.
        name (str): Tool name.

    Returns:
        ToolDefinition | None: Definition when registered.

    Examples:
        >>> from sevn.tools.base import ToolExecutor
        >>> _registry_definition(ToolExecutor(), "missing") is None
        True
    """
    for defn in executor.definitions():
        if defn.name == name:
            return defn
    return None


def build_serp_local_tool(
    executor: ToolExecutor,
    *,
    policy: WebEgressDomainPolicy,
) -> Tool[BTierDeps] | None:
    """Build a ``serp`` local fallback ``Tool`` that dispatches via ``ToolExecutor``.

    Args:
        executor (ToolExecutor): Active registry whose ``serp`` row backs dispatch.
        policy (WebEgressDomainPolicy): Domain policy applied to result URLs.

    Returns:
        Tool[BTierDeps] | None: Wrapped tool or ``None`` when ``serp`` is absent.

    Examples:
        >>> from sevn.tools.base import ToolExecutor
        >>> build_serp_local_tool(ToolExecutor(), policy=WebEgressDomainPolicy()) is None
        True
    """
    defn = _registry_definition(executor, "serp")
    if defn is None:
        return None
    args_model = tool_definition_to_args_model(defn)

    async def _runner(ctx: RunContext[BTierDeps], **data: Any) -> str:
        payload = args_model.model_validate(data).model_dump(exclude_none=True)
        raw = await _dispatch_tool(ctx, defn, payload)
        return _filter_serp_envelope(raw, policy)

    _runner.__name__ = "serp"
    return Tool.from_schema(
        _runner,
        name="serp",
        description=defn.description,
        json_schema=args_model.model_json_schema(),
        takes_ctx=True,
    )


def make_codemode_web_registry_tool(
    defn: ToolDefinition,
    *,
    policy: WebEgressDomainPolicy,
) -> Tool[BTierDeps]:
    """Build a triager-scoped web registry tool for CodeMode with egress policy (W8+B).

    Args:
        defn (ToolDefinition): Registry row for ``serp``, ``web_search``, ``get_page_content``,
            or ``web_fetch``.
        policy (WebEgressDomainPolicy): Host allow/block policy (same as W7 local fallbacks).

    Returns:
        Tool[BTierDeps]: Tool tagged ``code_mode=True`` for ``CodeMode(tools={'code_mode': True})``.

    Examples:
        >>> from sevn.tools.base import ToolDefinition
        >>> from sevn.agent.adapters.tier_b_capabilities import WebEgressDomainPolicy
        >>> make_codemode_web_registry_tool(
        ...     ToolDefinition(
        ...         name="serp",
        ...         category="web",
        ...         description="search",
        ...         parameters={"type": "object", "properties": {"query": {"type": "string"}}},
        ...     ),
        ...     policy=WebEgressDomainPolicy(),
        ... ).metadata
        {'code_mode': True}
    """
    from sevn.agent.adapters.tier_b_tools import _after_dispatch_update_loaded

    args_model = tool_definition_to_args_model(defn)
    name = defn.name

    async def _runner(ctx: RunContext[BTierDeps], **data: Any) -> str:
        payload = args_model.model_validate(data).model_dump(exclude_none=True)
        if name in _FETCH_TOOL_NAMES:
            url = str(payload.get("url") or "").strip()
            if url and not url_passes_domain_policy(url, policy):
                return enveloped_failure(
                    f"URL host blocked by egress domain policy: {url!r}",
                    code=ToolResultCode.PERMISSION_DENIED,
                )
        raw = await _dispatch_tool(ctx, defn, payload)
        if name in _WEB_TOOL_NAMES:
            raw = _filter_serp_envelope(raw, policy)
        _after_dispatch_update_loaded(ctx.deps, name, payload, raw)
        return raw

    _runner.__name__ = name
    tool = Tool.from_schema(
        _runner,
        name=name,
        description=defn.description,
        json_schema=args_model.model_json_schema(),
        takes_ctx=True,
    )
    if defn.requires_human:
        tool.requires_approval = True
    tool.metadata = {"code_mode": True}
    return tool


def build_get_page_content_local_tool(
    executor: ToolExecutor,
    *,
    policy: WebEgressDomainPolicy,
) -> Tool[BTierDeps] | None:
    """Build a ``get_page_content`` local fallback ``Tool`` via ``ToolExecutor``.

    Args:
        executor (ToolExecutor): Active registry executor.
        policy (WebEgressDomainPolicy): Domain policy enforced before fetch dispatch.

    Returns:
        Tool[BTierDeps] | None: Wrapped tool or ``None`` when absent from registry.

    Examples:
        >>> from sevn.tools.base import ToolExecutor
        >>> build_get_page_content_local_tool(ToolExecutor(), policy=WebEgressDomainPolicy()) is None
        True
    """
    defn = _registry_definition(executor, "get_page_content")
    if defn is None:
        return None
    args_model = tool_definition_to_args_model(defn)

    async def _runner(ctx: RunContext[BTierDeps], **data: Any) -> str:
        url = str(data.get("url") or "").strip()
        if url and not url_passes_domain_policy(url, policy):
            return enveloped_failure(
                f"URL host blocked by egress domain policy: {url!r}",
                code=ToolResultCode.PERMISSION_DENIED,
            )
        payload = args_model.model_validate(data).model_dump(exclude_none=True)
        return await _dispatch_tool(ctx, defn, payload)

    _runner.__name__ = "get_page_content"
    return Tool.from_schema(
        _runner,
        name="get_page_content",
        description=defn.description,
        json_schema=args_model.model_json_schema(),
        takes_ctx=True,
    )


def resolve_thinking_effort(
    agent: str,
    model_id: str,
    *,
    content_root: object | None = None,
) -> ThinkingLevel | None:
    """Map workspace ``minimax_thinking`` config to pydantic-ai ``Thinking`` effort.

    Returns ``None`` when thinking is disabled or the model/agent is out of scope.

    Args:
        agent (str): Agent key (``tier_b`` / ``tier_cd``).
        model_id (str): Resolved catalog model id.
        content_root (object | None): Workspace content root for overrides.

    Returns:
        ThinkingLevel | None: Effort level for ``Thinking(effort=...)``.

    Examples:
        >>> resolve_thinking_effort("tier_b", "openai/gpt-4o") is None
        True
        >>> resolve_thinking_effort("tier_b", "minimax/MiniMax-M2") is None
        True
    """
    from pathlib import Path

    root = content_root if isinstance(content_root, Path) else None
    thinking_body = resolve_minimax_thinking_request(agent, model_id, content_root=root)
    if thinking_body is None:
        return None
    thinking_type = str(thinking_body.get("type", "adaptive"))
    if thinking_type == "adaptive":
        return "medium"
    budget = thinking_body.get("budget_tokens")
    if isinstance(budget, int):
        if budget >= 4096:
            return "high"
        if budget >= 2048:
            return "medium"
        return "low"
    return "medium"


def build_web_thinking_extra_capabilities(
    *,
    workspace: WorkspaceConfig,
    model_id: str,
    tool_executor: ToolExecutor,
    triage_tools: tuple[str, ...] | list[str] | frozenset[str],
    content_root: object | None = None,
    codemode_enabled: bool = False,
) -> tuple[list[AbstractCapability[BTierDeps]], bool]:
    """Build optional W7 capabilities for one tier-B turn.

    Args:
        workspace (WorkspaceConfig): Parsed workspace config.
        model_id (str): Resolved tier-B catalog model id.
        tool_executor (ToolExecutor): Active registry executor (local fallbacks).
        triage_tools (tuple[str, ...] | frozenset[str]): Triager-provisioned tool names.
        content_root (object | None): Workspace content root for thinking overrides.
        codemode_enabled (bool): When ``True``, omit ``WebSearch`` / ``WebFetch`` so triager-scoped
            web tools stay on the registry path with ``code_mode=True`` (W8+B).

    Returns:
        tuple[list[AbstractCapability[BTierDeps]], bool]: Capabilities and whether
            ``Thinking`` replaced manual MiniMax thinking-body injection.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> from sevn.tools.base import ToolExecutor
        >>> caps, thinking = build_web_thinking_extra_capabilities(
        ...     workspace=WorkspaceConfig.minimal(),
        ...     model_id="anthropic/claude-sonnet-4-20250514",
        ...     tool_executor=ToolExecutor(),
        ...     triage_tools=("read",),
        ... )
        >>> caps == [] and thinking is False
        True
    """
    providers_obj = providers_section_dict(workspace.providers)
    policy = resolve_web_egress_domain_policy(workspace)
    allowed = list(policy.allowed_domains) or None
    blocked = list(policy.blocked_domains) or None
    names = frozenset(triage_tools)
    extras: list[AbstractCapability[BTierDeps]] = []

    if not codemode_enabled and names & _WEB_TOOL_NAMES:
        native_search = provider_supports_native_web_search(model_id, providers_obj)
        local_serp = build_serp_local_tool(tool_executor, policy=policy)
        if native_search:
            extras.append(
                WebSearch(
                    native=True,
                    local=local_serp,
                    allowed_domains=allowed,
                    blocked_domains=blocked,
                ),
            )
        elif local_serp is not None:
            extras.append(WebSearch(native=False, local=local_serp))

    if not codemode_enabled and names & _FETCH_TOOL_NAMES:
        native_fetch = provider_supports_native_web_fetch(model_id, providers_obj)
        local_fetch = build_get_page_content_local_tool(tool_executor, policy=policy)
        if native_fetch:
            extras.append(
                WebFetch(
                    native=True,
                    local=local_fetch,
                    allowed_domains=allowed,
                    blocked_domains=blocked,
                ),
            )
        elif local_fetch is not None:
            extras.append(
                WebFetch(
                    native=False,
                    local=local_fetch,
                    allowed_domains=allowed,
                    blocked_domains=blocked,
                ),
            )

    effort = resolve_thinking_effort("tier_b", model_id, content_root=content_root)
    thinking_via_capability = effort is not None
    if thinking_via_capability:
        extras.append(Thinking(effort=cast("ThinkingLevel", effort)))

    return extras, thinking_via_capability


def registry_tool_names_owned_by_web_capabilities(
    extras: Sequence[AbstractCapability[BTierDeps]],
) -> frozenset[str]:
    """Return registry tool names owned by W7 ``WebSearch`` / ``WebFetch`` local fallbacks.

    pydantic-ai 1.106+ rejects duplicate tool names across toolsets; when a web
    capability supplies a local ``serp`` or ``get_page_content`` runner, omit the
    same name from :class:`~sevn.agent.adapters.tier_b_toolset.SevnRegistryToolset`.

    Args:
        extras (Sequence[AbstractCapability[BTierDeps]]): W7 capabilities for this turn.

    Returns:
        frozenset[str]: Registry tool names to exclude from the registry toolset.

    Examples:
        >>> registry_tool_names_owned_by_web_capabilities([])
        frozenset()
    """
    owned: set[str] = set()
    for cap in extras:
        local = getattr(cap, "local", None)
        if local is not None and getattr(local, "name", None):
            owned.add(str(local.name))
    return frozenset(owned)


__all__ = [
    "CODEMODE_LOCAL_WEB_TOOL_NAMES",
    "WebEgressDomainPolicy",
    "build_get_page_content_local_tool",
    "build_serp_local_tool",
    "build_web_thinking_extra_capabilities",
    "make_codemode_web_registry_tool",
    "provider_supports_native_web_fetch",
    "provider_supports_native_web_search",
    "registry_tool_names_owned_by_web_capabilities",
    "resolve_thinking_effort",
    "resolve_web_egress_domain_policy",
    "url_passes_domain_policy",
]
