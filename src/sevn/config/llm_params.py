"""Per-agent LLM call config (`LLM_params_config.json`).

Module: sevn.config.llm_params
Depends: json, pathlib, sevn.config.defaults, sevn.config.model_resolution

``LLM_params_config.json`` carries **sampling** (temperature, top_p, top_k, seed),
**max_output_tokens**, and optional **reasoning** (MiniMax extended thinking) keyed
per-agent with optional per-model overrides. ``sevn.json`` keeps model selection and
**ceiling** caps in ``gateway.budget.*_max_output_tokens``; runtime applies
``min(sevn.json ceiling, LLM_params_config.json resolved value)``.

Precedence for sampling and max_output_tokens: built-in default → built-in MiniMax
default (when the id is a MiniMax catalog id) → workspace per-agent block →
workspace per-model override. The resolved :class:`SamplingParams` is then
filtered to the keys the **resolved transport** accepts (anthropic:
temperature/top_p/top_k; chat_completions: temperature/top_p/seed; bedrock:
temperature/top_p/top_k) — the transport layer applies no whitelist, so
unsupported keys must be dropped here (W1.1).

Exports:
    SamplingParams — resolved per-call sampling bundle.
    ReasoningParams — resolved optional extended-reasoning request metadata.
    builtin_llm_params_doc — the packaged default document (also the seed source).
    validate_llm_params_doc — structural validation; raises ``ValueError``.
    resolve_llm_params — agent+model → resolved (unfiltered) sampling bundle.
    resolve_llm_params_max_output_tokens — agent+model → LLM_params-side token cap.
    resolve_effective_max_output_tokens — agent+model+workspace → min(sevn, LLM_params).
    resolve_llm_request_params — agent+model+transport → filtered request kwargs.
    resolve_reasoning_params — resolved reasoning config for one call.
    resolve_reasoning_request — optional provider ``thinking`` body (B/C, default off).
    resolve_minimax_thinking_request — deprecated alias for :func:`resolve_reasoning_request`.
    load_or_create_llm_params_doc — read workspace params or copy built-in defaults.
    write_llm_params_doc — validate and atomically persist ``LLM_params_config.json``.
    set_agent_model_max_output_tokens — set agent- or model-level ``max_output_tokens``.
    transport_for — resolve the transport label for a model id.

Examples:
    >>> resolve_effective_max_output_tokens("tier_b", "minimax/M2", None, content_root=None)
    4096
    >>> p = resolve_llm_request_params("tier_b", "minimax/MiniMax-M2", "anthropic")
    >>> p["temperature"], p["top_p"], p["top_k"]
    (1.0, 0.95, 40)
    >>> "seed" in p  # anthropic wire drops seed
    False
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from sevn.config.defaults import (
    DREAMING_MAX_OUTPUT_TOKENS,
    GUARD_MAX_OUTPUT_TOKENS,
    LCM_MAX_OUTPUT_TOKENS,
    MINIMAX_MAX_OUTPUT_TOKENS,
    TIER_B_MAX_OUTPUT_TOKENS,
    TIER_CD_MAX_OUTPUT_TOKENS,
    TRIAGER_MAX_OUTPUT_TOKENS,
    USER_MODEL_MAX_OUTPUT_TOKENS,
)
from sevn.config.model_resolution import (
    is_minimax_catalog_model,
    resolve_transport_for_model_id,
)

if TYPE_CHECKING:
    from pathlib import Path

    from sevn.config.sections.root import WorkspaceConfig

LLM_PARAMS_FILENAME: Final[str] = "LLM_params_config.json"
LLM_PARAMS_SCHEMA_VERSION: Final[int] = 2

AGENT_NAMES: Final[tuple[str, ...]] = (
    "triager",
    "tier_b",
    "tier_cd",
    "guard",
    "lcm",
    "dreaming",
    "user_model",
)

# Extended-reasoning request object — tier B/C executors only (never triager/guard).
REASONING_AGENTS: Final[frozenset[str]] = frozenset({"tier_b", "tier_cd"})
MINIMAX_THINKING_AGENTS: Final[frozenset[str]] = REASONING_AGENTS

_REASONING_TYPES: Final[frozenset[str]] = frozenset({"adaptive", "enabled"})

# MiniMax officially recommended sampling values (plan D4).
_MINIMAX_SAMPLING_DEFAULTS: Final[dict[str, float | int]] = {
    "temperature": 1.0,
    "top_p": 0.95,
    "top_k": 40,
}

_AGENT_MAX_OUTPUT_DEFAULTS: Final[dict[str, int]] = {
    "triager": TRIAGER_MAX_OUTPUT_TOKENS,
    "tier_b": TIER_B_MAX_OUTPUT_TOKENS,
    "tier_cd": TIER_CD_MAX_OUTPUT_TOKENS,
    "guard": GUARD_MAX_OUTPUT_TOKENS,
    "lcm": LCM_MAX_OUTPUT_TOKENS,
    "dreaming": DREAMING_MAX_OUTPUT_TOKENS,
    "user_model": USER_MODEL_MAX_OUTPUT_TOKENS,
}

# Non-MiniMax per-agent sampling defaults.
_AGENT_SAMPLING_DEFAULTS: Final[dict[str, dict[str, float]]] = {
    "triager": {"temperature": 0.0},
    "tier_b": {"temperature": 0.0},
    "tier_cd": {"temperature": 0.0},
    "guard": {"temperature": 0.0},
    "lcm": {"temperature": 0.2},
    "dreaming": {"temperature": 0.0},
    "user_model": {"temperature": 0.0},
}

_DEFAULT_REASONING: Final[dict[str, object]] = {"enabled": False, "type": "adaptive"}

# Sampling keys each resolved transport accepts (W1.1). Keys outside these sets
# are dropped before the request leaves the resolver.
_TRANSPORT_KEYS: Final[dict[str, frozenset[str]]] = {
    "anthropic": frozenset({"temperature", "top_p", "top_k"}),
    "chat_completions": frozenset({"temperature", "top_p", "seed"}),
    "bedrock": frozenset({"temperature", "top_p", "top_k"}),
    "responses_api": frozenset({"temperature", "top_p", "seed"}),
}

_SAMPLING_KEYS: Final[tuple[str, ...]] = ("temperature", "top_p", "top_k", "seed")


@dataclass(frozen=True, slots=True)
class SamplingParams:
    """Resolved sampling parameters for one LLM call.

    Attributes:
        temperature (float | None): Sampling temperature.
        top_p (float | None): Nucleus sampling cutoff.
        top_k (int | None): Top-k sampling (Anthropic/MiniMax/Bedrock only).
        seed (int | None): Deterministic seed (chat_completions only).

    Examples:
        >>> SamplingParams(temperature=0.0).as_request_kwargs("chat_completions")
        {'temperature': 0.0}
    """

    temperature: float | None = None
    top_p: float | None = None
    top_k: int | None = None
    seed: int | None = None

    def as_request_kwargs(self, transport_name: str) -> dict[str, float | int]:
        """Return non-None sampling keys the named transport accepts.

        Args:
            transport_name (str): Resolved transport label (case-insensitive).

        Returns:
            dict[str, float | int]: Filtered ``{key: value}`` ready to splice
            into the provider request dict. Keys unsupported by the transport
            (e.g. ``seed`` on ``anthropic``, ``top_k`` on ``chat_completions``)
            are silently dropped.

        Examples:
            >>> sp = SamplingParams(temperature=1.0, top_p=0.95, top_k=40, seed=7)
            >>> sp.as_request_kwargs("anthropic")
            {'temperature': 1.0, 'top_p': 0.95, 'top_k': 40}
            >>> sp.as_request_kwargs("chat_completions")
            {'temperature': 1.0, 'top_p': 0.95, 'seed': 7}
        """
        allowed = _TRANSPORT_KEYS.get(transport_name.strip().lower(), frozenset())
        out: dict[str, float | int] = {}
        for key in _SAMPLING_KEYS:
            value = getattr(self, key)
            if value is not None and key in allowed:
                out[key] = value
        return out


@dataclass(frozen=True, slots=True)
class ReasoningParams:
    """Resolved extended-reasoning configuration for one LLM call.

    Attributes:
        enabled (bool): When ``True``, emit a provider ``thinking`` body.
        type (str): ``adaptive`` or ``enabled`` (MiniMax extended thinking).
        budget_tokens (int | None): Token budget when ``type`` is ``enabled``.

    Examples:
        >>> ReasoningParams().as_thinking_request() is None
        True
    """

    enabled: bool = False
    type: str = "adaptive"
    budget_tokens: int | None = None

    def as_thinking_request(self) -> dict[str, object] | None:
        """Return provider ``thinking`` body when enabled.

        Returns:
            dict[str, object] | None: Request fragment, or ``None`` when disabled.

        Examples:
            >>> ReasoningParams(enabled=True).as_thinking_request()
            {'type': 'adaptive'}
            >>> ReasoningParams(
            ...     enabled=True, type="enabled", budget_tokens=1024
            ... ).as_thinking_request()
            {'type': 'enabled', 'budget_tokens': 1024}
        """
        if not self.enabled:
            return None
        if self.type == "enabled" and self.budget_tokens is not None:
            return {"type": "enabled", "budget_tokens": self.budget_tokens}
        return {"type": self.type}


def _minimax_model_override_block() -> dict[str, Any]:
    """Return the packaged ``minimax/*`` override block.

    Returns:
        dict[str, Any]: Sampling, ``max_output_tokens``, and ``reasoning`` defaults.

    Examples:
        >>> _minimax_model_override_block()["max_output_tokens"]
        4096
    """
    block: dict[str, Any] = dict(_MINIMAX_SAMPLING_DEFAULTS)
    block["max_output_tokens"] = MINIMAX_MAX_OUTPUT_TOKENS
    block["reasoning"] = dict(_DEFAULT_REASONING)
    return block


def builtin_llm_params_doc() -> dict[str, Any]:
    """Return the packaged default ``LLM_params_config.json`` document.

    This is both the in-code fallback (when no workspace file exists) and the
    structure mirrored by the seed file written into the workspace.

    Returns:
        dict[str, Any]: Per-agent blocks plus a MiniMax ``model_overrides``
        entry applying sampling, ``max_output_tokens``, and ``reasoning``.

    Examples:
        >>> doc = builtin_llm_params_doc()
        >>> doc["lcm"]["temperature"]
        0.2
        >>> doc["tier_b"]["model_overrides"]["minimax/*"]["top_k"]
        40
    """
    doc: dict[str, Any] = {"schema_version": LLM_PARAMS_SCHEMA_VERSION}
    minimax_override = _minimax_model_override_block()
    for agent in AGENT_NAMES:
        block: dict[str, Any] = dict(_AGENT_SAMPLING_DEFAULTS[agent])
        block["max_output_tokens"] = _AGENT_MAX_OUTPUT_DEFAULTS[agent]
        block["reasoning"] = dict(_DEFAULT_REASONING)
        block["model_overrides"] = {"minimax/*": dict(minimax_override)}
        doc[agent] = block
    return doc


def _is_number(value: object) -> bool:
    """Return ``True`` for real numbers (``int``/``float`` but not ``bool``).

    Args:
        value (object): Candidate value.

    Returns:
        bool: ``True`` when ``value`` is an ``int`` or ``float`` and not a ``bool``.

    Examples:
        >>> _is_number(0.2), _is_number(3), _is_number(True), _is_number("x")
        (True, True, False, False)
    """
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _validate_max_output_tokens(value: object, where: str) -> None:
    """Validate an optional ``max_output_tokens`` field.

    Args:
        value (object): Parsed value (``None`` skips validation).
        where (str): Human-readable location for error messages.

    Raises:
        ValueError: When the value is not a positive integer.

    Examples:
        >>> _validate_max_output_tokens(4096, "tier_b")
        >>> _validate_max_output_tokens(0, "tier_b")
        Traceback (most recent call last):
        ValueError: tier_b.max_output_tokens must be >= 1
    """
    if value is None:
        return
    if not isinstance(value, int) or isinstance(value, bool):
        msg = f"{where}.max_output_tokens must be an integer"
        raise ValueError(msg)
    if value < 1:
        msg = f"{where}.max_output_tokens must be >= 1"
        raise ValueError(msg)


def _validate_reasoning_block(block: object, where: str) -> None:
    """Validate optional ``reasoning`` (or legacy ``minimax_thinking``) block.

    Args:
        block (object): Parsed reasoning object.
        where (str): Human-readable location for error messages.

    Raises:
        ValueError: When structure or values are invalid.

    Examples:
        >>> _validate_reasoning_block({"enabled": False, "type": "adaptive"}, "tier_b")
        >>> _validate_reasoning_block({"enabled": True, "type": "bogus"}, "tier_b")
        Traceback (most recent call last):
        ValueError: tier_b.reasoning.type must be one of ['adaptive', 'enabled']
    """
    if not isinstance(block, dict):
        msg = f"{where}.reasoning must be a JSON object"
        raise ValueError(msg)
    enabled = block.get("enabled", False)
    if not isinstance(enabled, bool):
        msg = f"{where}.reasoning.enabled must be a boolean"
        raise ValueError(msg)
    reasoning_type = block.get("type", "adaptive")
    if reasoning_type not in _REASONING_TYPES:
        msg = f"{where}.reasoning.type must be one of {sorted(_REASONING_TYPES)}"
        raise ValueError(msg)
    if "budget_tokens" in block and block["budget_tokens"] is not None:
        if not isinstance(block["budget_tokens"], int):
            msg = f"{where}.reasoning.budget_tokens must be an integer"
            raise ValueError(msg)
        if block["budget_tokens"] < 1:
            msg = f"{where}.reasoning.budget_tokens must be >= 1"
            raise ValueError(msg)
        if reasoning_type != "enabled":
            msg = f"{where}.reasoning.budget_tokens requires reasoning.type == 'enabled'"
            raise ValueError(msg)


def _validate_param_block(block: dict[str, Any], where: str) -> None:
    """Validate one agent or override block's sampling and token keys.

    Args:
        block (dict[str, Any]): The block to check.
        where (str): Human-readable location for error messages.

    Raises:
        ValueError: When a key has the wrong type or range.

    Examples:
        >>> _validate_param_block({"temperature": 0.0, "top_p": 0.95, "top_k": 40}, "x")
        >>> _validate_param_block({"top_p": 1.5}, "x")
        Traceback (most recent call last):
        ValueError: x.top_p must be within [0.0, 1.0]
    """
    for key in ("temperature", "top_p"):
        if key in block and block[key] is not None and not _is_number(block[key]):
            msg = f"{where}.{key} must be a number"
            raise ValueError(msg)
    if "top_p" in block and _is_number(block.get("top_p")):
        top_p = float(block["top_p"])
        if not 0.0 <= top_p <= 1.0:
            msg = f"{where}.top_p must be within [0.0, 1.0]"
            raise ValueError(msg)
    for key in ("top_k", "seed"):
        if key in block and block[key] is not None and not isinstance(block[key], int):
            msg = f"{where}.{key} must be an integer"
            raise ValueError(msg)
    _validate_max_output_tokens(block.get("max_output_tokens"), where)


def _reasoning_block_from_agent_dict(block: dict[str, Any]) -> dict[str, Any] | None:
    """Return ``reasoning`` config, accepting legacy ``minimax_thinking``.

    Args:
        block (dict[str, Any]): One agent block from ``LLM_params_config.json``.

    Returns:
        dict[str, Any] | None: Reasoning sub-block when present.

    Examples:
        >>> _reasoning_block_from_agent_dict({"reasoning": {"enabled": False}})["enabled"]
        False
        >>> _reasoning_block_from_agent_dict(
        ...     {"minimax_thinking": {"enabled": True, "type": "adaptive"}}
        ... )["enabled"]
        True
    """
    reasoning = block.get("reasoning")
    if isinstance(reasoning, dict):
        return reasoning
    legacy = block.get("minimax_thinking")
    if isinstance(legacy, dict):
        return legacy
    return None


def validate_llm_params_doc(doc: object) -> dict[str, Any]:
    """Validate a parsed ``LLM_params_config.json`` document.

    Args:
        doc (object): Parsed JSON (expected ``dict``).

    Returns:
        dict[str, Any]: The same document when valid.

    Raises:
        ValueError: When the structure or a value is invalid. Unknown top-level
        keys other than the seven agents and ``schema_version`` are rejected so
        typos surface early.

    Examples:
        >>> validate_llm_params_doc({"triager": {"temperature": 0.0}})["triager"]["temperature"]
        0.0
        >>> validate_llm_params_doc({"triager": {"top_p": 2.0}})
        Traceback (most recent call last):
        ValueError: triager.top_p must be within [0.0, 1.0]
    """
    if not isinstance(doc, dict):
        msg = "LLM_params_config.json must be a JSON object"
        raise ValueError(msg)
    allowed_top = {*AGENT_NAMES, "schema_version"}
    for top_key, block in doc.items():
        if top_key not in allowed_top:
            msg = f"unknown top-level key {top_key!r} (expected one of {sorted(allowed_top)})"
            raise ValueError(msg)
        if top_key == "schema_version":
            continue
        if not isinstance(block, dict):
            msg = f"{top_key} must be a JSON object"
            raise ValueError(msg)
        _validate_param_block(block, top_key)
        reasoning = _reasoning_block_from_agent_dict(block)
        if reasoning is not None:
            _validate_reasoning_block(reasoning, top_key)
        legacy = block.get("minimax_thinking")
        if legacy is not None and legacy is not reasoning:
            _validate_reasoning_block(legacy, top_key)
        overrides = block.get("model_overrides")
        if overrides is not None:
            if not isinstance(overrides, dict):
                msg = f"{top_key}.model_overrides must be a JSON object"
                raise ValueError(msg)
            for model_id, ov in overrides.items():
                if not isinstance(ov, dict):
                    msg = f"{top_key}.model_overrides.{model_id} must be a JSON object"
                    raise ValueError(msg)
                where = f"{top_key}.model_overrides.{model_id}"
                _validate_param_block(ov, where)
                ov_reasoning = ov.get("reasoning")
                if ov_reasoning is not None:
                    _validate_reasoning_block(ov_reasoning, where)
    return doc


def _load_workspace_doc(content_root: Path | None) -> dict[str, Any] | None:
    """Read + validate the workspace params file, or ``None`` when absent/invalid.

    Args:
        content_root (Path | None): Workspace content root, or ``None`` to skip.

    Returns:
        dict[str, Any] | None: Validated document, or ``None`` to fall back to
        built-in defaults (missing file or unreadable/invalid content).

    Examples:
        >>> _load_workspace_doc(None) is None  # no workspace ⇒ built-in defaults
        True
    """
    if content_root is None:
        return None
    path = content_root / LLM_PARAMS_FILENAME
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        parsed = json.loads(raw)
        return validate_llm_params_doc(parsed)
    except (ValueError, json.JSONDecodeError):
        return None


def load_or_create_llm_params_doc(content_root: Path) -> dict[str, Any]:
    """Return the workspace params document, seeding from built-in defaults when absent.

    Args:
        content_root (Path): Workspace content root.

    Returns:
        dict[str, Any]: Validated on-disk document, or a deep copy of
        :func:`builtin_llm_params_doc` when the file is missing or invalid.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> root = Path(tempfile.mkdtemp())
        >>> doc = load_or_create_llm_params_doc(root)
        >>> doc["schema_version"] == LLM_PARAMS_SCHEMA_VERSION
        True
    """
    loaded = _load_workspace_doc(content_root)
    if loaded is not None:
        return copy.deepcopy(loaded)
    return copy.deepcopy(builtin_llm_params_doc())


def write_llm_params_doc(content_root: Path, doc: dict[str, Any]) -> Path:
    """Validate and atomically write ``LLM_params_config.json``.

    Args:
        content_root (Path): Workspace content root.
        doc (dict[str, Any]): Params document to persist.

    Returns:
        Path: Written file path.

    Raises:
        ValueError: When ``doc`` fails structural validation.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> root = Path(tempfile.mkdtemp())
        >>> path = write_llm_params_doc(root, builtin_llm_params_doc())
        >>> path.name == LLM_PARAMS_FILENAME
        True
    """
    validated = validate_llm_params_doc(doc)
    path = content_root / LLM_PARAMS_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(validated, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def set_agent_model_max_output_tokens(
    content_root: Path,
    *,
    agent: str,
    max_output_tokens: int,
    model_id: str | None = None,
) -> Path:
    """Set ``max_output_tokens`` on an agent block or a ``model_overrides`` entry.

    Creates ``LLM_params_config.json`` from built-in defaults when missing. When
    ``model_id`` is ``None``, updates the per-agent block; otherwise updates or
    creates ``model_overrides[model_id]``.

    Args:
        content_root (Path): Workspace content root.
        agent (str): One of :data:`AGENT_NAMES`.
        max_output_tokens (int): Token cap (``>= 1``).
        model_id (str | None): Optional model id or override pattern (e.g.
            ``minimax/*``).

    Returns:
        Path: Written ``LLM_params_config.json`` path.

    Raises:
        ValueError: When ``agent`` or ``max_output_tokens`` is invalid.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> root = Path(tempfile.mkdtemp())
        >>> path = set_agent_model_max_output_tokens(
        ...     root, agent="tier_b", max_output_tokens=8192, model_id="minimax/*"
        ... )
        >>> path.name == LLM_PARAMS_FILENAME
        True
    """
    if agent not in AGENT_NAMES:
        msg = f"unknown agent {agent!r}; expected one of {sorted(AGENT_NAMES)}"
        raise ValueError(msg)
    _validate_max_output_tokens(max_output_tokens, agent)
    doc = load_or_create_llm_params_doc(content_root)
    block = doc.setdefault(agent, {})
    if not isinstance(block, dict):
        msg = f"{agent} must be a JSON object"
        raise ValueError(msg)
    if model_id is None:
        block["max_output_tokens"] = max_output_tokens
    else:
        overrides = block.setdefault("model_overrides", {})
        if not isinstance(overrides, dict):
            msg = f"{agent}.model_overrides must be a JSON object"
            raise ValueError(msg)
        override = overrides.setdefault(model_id, {})
        if not isinstance(override, dict):
            msg = f"{agent}.model_overrides.{model_id} must be a JSON object"
            raise ValueError(msg)
        override["max_output_tokens"] = max_output_tokens
    return write_llm_params_doc(content_root, doc)


def _match_override(overrides: dict[str, Any], model_id: str) -> dict[str, Any] | None:
    """Pick a ``model_overrides`` entry for ``model_id``.

    Exact id wins; otherwise ``minimax/*`` matches any MiniMax catalog id, and a
    trailing-``*`` prefix glob matches by prefix.

    Args:
        overrides (dict[str, Any]): The ``model_overrides`` mapping.
        model_id (str): Resolved model id.

    Returns:
        dict[str, Any] | None: The matched override block, or ``None``.

    Examples:
        >>> ov = {"minimax/*": {"top_k": 40}}
        >>> _match_override(ov, "minimax/MiniMax-M2")["top_k"]
        40
        >>> _match_override(ov, "openai:gpt-4o-mini") is None
        True
    """
    exact = overrides.get(model_id)
    if isinstance(exact, dict):
        return exact
    for pattern, block in overrides.items():
        if not isinstance(block, dict):
            continue
        if pattern == "minimax/*" and is_minimax_catalog_model(model_id):
            return block
        if pattern.endswith("*") and model_id.startswith(pattern[:-1]):
            return block
    return None


def _merged_agent_values(
    agent: str,
    model_id: str,
    *,
    content_root: Path | None,
) -> dict[str, Any]:
    """Merge built-in, MiniMax, workspace agent, and model-override values.

    Args:
        agent (str): One of :data:`AGENT_NAMES`.
        model_id (str): Resolved model id for the call.
        content_root (Path | None): Workspace content root for overrides.

    Returns:
        dict[str, Any]: Merged sampling, ``max_output_tokens``, and ``reasoning`` map.

    Examples:
        >>> _merged_agent_values("lcm", "openai:gpt-4o", content_root=None)["temperature"]
        0.2
    """
    values: dict[str, Any] = {}
    values.update(_AGENT_SAMPLING_DEFAULTS.get(agent, {}))
    values["max_output_tokens"] = _AGENT_MAX_OUTPUT_DEFAULTS.get(agent, TRIAGER_MAX_OUTPUT_TOKENS)
    if agent in REASONING_AGENTS:
        values["reasoning"] = dict(_DEFAULT_REASONING)
    if is_minimax_catalog_model(model_id):
        values.update(_MINIMAX_SAMPLING_DEFAULTS)
        values["max_output_tokens"] = MINIMAX_MAX_OUTPUT_TOKENS
        values["reasoning"] = dict(_DEFAULT_REASONING)
    doc = _load_workspace_doc(content_root)
    if doc is None:
        return values
    block = doc.get(agent)
    if not isinstance(block, dict):
        return values
    for key in _SAMPLING_KEYS:
        if key in block and block[key] is not None:
            values[key] = block[key]
    if "max_output_tokens" in block and block["max_output_tokens"] is not None:
        values["max_output_tokens"] = int(block["max_output_tokens"])
    reasoning = _reasoning_block_from_agent_dict(block)
    if reasoning is not None:
        values["reasoning"] = dict(reasoning)
    overrides = block.get("model_overrides")
    if isinstance(overrides, dict):
        ov = _match_override(overrides, model_id)
        if ov is not None:
            for key in _SAMPLING_KEYS:
                if key in ov and ov[key] is not None:
                    values[key] = ov[key]
            if "max_output_tokens" in ov and ov["max_output_tokens"] is not None:
                values["max_output_tokens"] = int(ov["max_output_tokens"])
            ov_reasoning = ov.get("reasoning")
            if isinstance(ov_reasoning, dict):
                merged = dict(values.get("reasoning", _DEFAULT_REASONING))
                merged.update(ov_reasoning)
                values["reasoning"] = merged
    return values


def resolve_llm_params(
    agent: str,
    model_id: str,
    *,
    content_root: Path | None = None,
) -> SamplingParams:
    """Resolve sampling params for ``agent`` + ``model_id``.

    Precedence: built-in default → built-in MiniMax default (when catalog id) →
    workspace per-agent block → workspace per-model override. The returned
    :class:`SamplingParams` is *not yet* transport-filtered; call
    :meth:`SamplingParams.as_request_kwargs` with the resolved transport (or use
    :func:`resolve_llm_request_params`).

    Args:
        agent (str): One of :data:`AGENT_NAMES`.
        model_id (str): Resolved model id for the call.
        content_root (Path | None): Workspace content root holding
            ``LLM_params_config.json``. ``None`` uses built-in defaults only.

    Returns:
        SamplingParams: Resolved (unfiltered) sampling bundle.

    Examples:
        >>> resolve_llm_params("lcm", "openai:gpt-4o-mini").temperature
        0.2
        >>> sp = resolve_llm_params("triager", "minimax/MiniMax-M2")
        >>> (sp.temperature, sp.top_p, sp.top_k)
        (1.0, 0.95, 40)
    """
    values = _merged_agent_values(agent, model_id, content_root=content_root)
    return SamplingParams(
        temperature=values.get("temperature"),
        top_p=values.get("top_p"),
        top_k=values.get("top_k"),
        seed=values.get("seed"),
    )


def resolve_llm_params_max_output_tokens(
    agent: str,
    model_id: str,
    *,
    content_root: Path | None = None,
) -> int:
    """Resolve ``max_output_tokens`` from ``LLM_params_config.json`` only.

    Args:
        agent (str): One of :data:`AGENT_NAMES`.
        model_id (str): Resolved model id for the call.
        content_root (Path | None): Workspace content root for overrides.

    Returns:
        int: Resolved token cap before applying ``sevn.json`` ceilings.

    Examples:
        >>> resolve_llm_params_max_output_tokens("tier_b", "minimax/MiniMax-M2")
        4096
    """
    values = _merged_agent_values(agent, model_id, content_root=content_root)
    raw = values.get("max_output_tokens")
    if isinstance(raw, int) and raw >= 1:
        return raw
    return _AGENT_MAX_OUTPUT_DEFAULTS.get(agent, TRIAGER_MAX_OUTPUT_TOKENS)


def resolve_effective_max_output_tokens(
    agent: str,
    model_id: str,
    workspace: WorkspaceConfig | None,
    *,
    content_root: Path | None = None,
    extra_caps: tuple[int, ...] = (),
) -> int:
    """Return ``min(sevn.json ceiling, LLM_params value, *extra_caps)``.

    Args:
        agent (str): One of :data:`AGENT_NAMES`.
        model_id (str): Resolved model id for the call.
        workspace (WorkspaceConfig | None): Parsed workspace for ``sevn.json`` ceilings.
        content_root (Path | None): Workspace content root for ``LLM_params_config.json``.
        extra_caps (tuple[int, ...]): Optional additional caps (e.g. intro turn).

    Returns:
        int: Effective provider ``max_tokens`` for the call.

    Examples:
        >>> resolve_effective_max_output_tokens("tier_b", "minimax/M2", None, content_root=None)
        4096
    """
    from sevn.config.sections.accessors import agent_max_output_tokens_ceiling

    params_cap = resolve_llm_params_max_output_tokens(agent, model_id, content_root=content_root)
    sevn_cap = agent_max_output_tokens_ceiling(workspace, agent)
    caps = (params_cap, sevn_cap, *extra_caps)
    positive = [cap for cap in caps if cap >= 1]
    return min(positive) if positive else 1


def resolve_reasoning_params(
    agent: str,
    model_id: str,
    *,
    content_root: Path | None = None,
) -> ReasoningParams:
    """Resolve extended-reasoning config for ``agent`` + ``model_id``.

    Only tier B/C agents on MiniMax catalog ids may return an enabled config.

    Args:
        agent (str): One of :data:`AGENT_NAMES`.
        model_id (str): Resolved model id for the call.
        content_root (Path | None): Workspace content root for overrides.

    Returns:
        ReasoningParams: Resolved reasoning bundle (disabled when inapplicable).

    Examples:
        >>> resolve_reasoning_params("triager", "minimax/MiniMax-M2").enabled
        False
    """
    if agent not in REASONING_AGENTS or not is_minimax_catalog_model(model_id):
        return ReasoningParams()
    values = _merged_agent_values(agent, model_id, content_root=content_root)
    raw = values.get("reasoning")
    if not isinstance(raw, dict):
        return ReasoningParams()
    enabled = bool(raw.get("enabled", False))
    reasoning_type = str(raw.get("type", "adaptive"))
    budget_raw = raw.get("budget_tokens")
    budget_tokens = budget_raw if isinstance(budget_raw, int) else None
    return ReasoningParams(
        enabled=enabled,
        type=reasoning_type,
        budget_tokens=budget_tokens,
    )


def resolve_reasoning_request(
    agent: str,
    model_id: str,
    *,
    content_root: Path | None = None,
) -> dict[str, object] | None:
    """Resolve optional provider ``thinking`` body from ``reasoning`` config.

    Args:
        agent (str): Agent key (``tier_b`` or ``tier_cd`` when thinking may apply).
        model_id (str): Resolved model id for the call.
        content_root (Path | None): Workspace content root for overrides.

    Returns:
        dict[str, object] | None: ``{"type": "adaptive"}`` or
        ``{"type": "enabled", "budget_tokens": N}`` when enabled; ``None`` otherwise.

    Examples:
        >>> resolve_reasoning_request("triager", "minimax/MiniMax-M2") is None
        True
        >>> resolve_reasoning_request("tier_b", "openai:gpt-4o") is None
        True
        >>> resolve_reasoning_request("tier_b", "minimax/MiniMax-M2") is None
        True
    """
    return resolve_reasoning_params(
        agent, model_id, content_root=content_root
    ).as_thinking_request()


def resolve_minimax_thinking_request(
    agent: str,
    model_id: str,
    *,
    content_root: Path | None = None,
) -> dict[str, object] | None:
    """Deprecated alias for :func:`resolve_reasoning_request`.

    Args:
        agent (str): Agent key (``tier_b`` or ``tier_cd`` when thinking may apply).
        model_id (str): Resolved model id for the call.
        content_root (Path | None): Workspace content root for overrides.

    Returns:
        dict[str, object] | None: Provider ``thinking`` body when enabled.

    Examples:
        >>> resolve_minimax_thinking_request("triager", "minimax/MiniMax-M2") is None
        True
    """
    return resolve_reasoning_request(agent, model_id, content_root=content_root)


def resolve_llm_request_params(
    agent: str,
    model_id: str,
    transport_name: str,
    *,
    content_root: Path | None = None,
    seed: int | None = None,
) -> dict[str, float | int]:
    """Resolve transport-filtered request kwargs for one LLM call.

    Convenience wrapper combining :func:`resolve_llm_params` and
    :meth:`SamplingParams.as_request_kwargs`. An explicit ``seed`` argument
    (e.g. the triager's deterministic seed) is applied when the resolved config
    does not already set one and the transport accepts ``seed``.

    Args:
        agent (str): One of :data:`AGENT_NAMES`.
        model_id (str): Resolved model id.
        transport_name (str): Resolved transport label.
        content_root (Path | None): Workspace content root for overrides.
        seed (int | None): Caller-supplied deterministic seed fallback.

    Returns:
        dict[str, float | int]: Filtered sampling kwargs to splice into the request.

    Examples:
        >>> resolve_llm_request_params("triager", "openai:gpt-4o", "chat_completions", seed=7)
        {'temperature': 0.0, 'seed': 7}
        >>> resolve_llm_request_params("tier_b", "minimax/MiniMax-M2", "anthropic")
        {'temperature': 1.0, 'top_p': 0.95, 'top_k': 40}
    """
    params = resolve_llm_params(agent, model_id, content_root=content_root)
    if params.seed is None and seed is not None:
        params = SamplingParams(
            temperature=params.temperature,
            top_p=params.top_p,
            top_k=params.top_k,
            seed=seed,
        )
    return params.as_request_kwargs(transport_name)


def transport_for(model_id: str, providers_obj: dict[str, Any] | None = None) -> str:
    """Resolve the transport label for ``model_id`` (thin re-export helper).

    Args:
        model_id (str): Model id to classify.
        providers_obj (dict[str, Any] | None): Merged ``providers`` block.

    Returns:
        str: Lowercased transport label.

    Examples:
        >>> transport_for("minimax/MiniMax-M2")
        'chat_completions'
        >>> transport_for("openai:gpt-4o")
        'chat_completions'
    """
    return resolve_transport_for_model_id(providers_obj or {}, model_id)
