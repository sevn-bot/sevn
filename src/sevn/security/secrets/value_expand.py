"""Order-sensitive ``${ENV:…}`` and ``${SECRET:…}`` expansion (``specs/02 §2.4``, ``specs/06 §2.2``).

Module: sevn.security.secrets.value_expand
Depends: os, re, sevn.security.secrets.cache, sevn.security.secrets.errors

Exports:
    EnvUnresolvedError — missing ``${ENV:VAR}`` when ``strict``.
    expand_env_refs — substitute ``${ENV:VAR_NAME}`` from ``os.environ``.
    expand_secret_refs — substitute ``${SECRET:…}`` using a resolved cache.
    expand_refs_env_then_secret — alternating env-then-secret passes until stable.
"""

from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING

from sevn.security.secrets.errors import SecretUnresolvedError

if TYPE_CHECKING:
    from sevn.security.secrets.cache import ResolvedSecretsCache

_ENV_REF = re.compile(r"\$\{ENV:([^}]+)\}")
# Inner payload is `source:logical_key` (logical may contain colons; split once).
_SECRET_REF = re.compile(r"\$\{SECRET:([^}]+)\}")


class EnvUnresolvedError(ValueError):
    """Process environment lacked a referenced ``${ENV:VAR}`` name."""

    def __init__(self, message: str, *, var_name: str) -> None:
        """Initialize.

        Args:
            message (str): Human-readable message.
            var_name (str): Variable name referenced without a value.

        Returns:
            None: Always.

        Examples:
            >>> EnvUnresolvedError("x", var_name="Y").var_name
            'Y'
        """

        super().__init__(message)
        self.var_name = var_name


def expand_env_refs(text: str, *, strict: bool = True) -> str:
    """Replace every ``${ENV:VAR_NAME}`` segment using ``os.environ``.

    When ``strict`` is false, unresolved variables keep their original ``${ENV:…}``
    substring (see ``telegram_resolve`` probing paths).

    Args:
        text (str): Possibly containing references.
        strict (bool): When true, raises ``EnvUnresolvedError`` on missing vars.

    Returns:
        str: Expanded string.

    Examples:
        >>> import os
        >>> prev = os.environ.get("SEVN_EXPAND_TEST_VAR")
        >>> os.environ["SEVN_EXPAND_TEST_VAR"] = "ok"
        >>> expand_env_refs("x=${ENV:SEVN_EXPAND_TEST_VAR}", strict=True)
        'x=ok'
        >>> del os.environ["SEVN_EXPAND_TEST_VAR"]
        >>> if prev is not None:
        ...     os.environ["SEVN_EXPAND_TEST_VAR"] = prev
        >>> isinstance(expand_env_refs("${ENV:X_MISSING___}", strict=False), str)
        True
    """

    def repl(match: re.Match[str]) -> str:
        name = match.group(1).strip()
        hit = os.environ.get(name)
        if hit is None:
            if strict:
                msg = f"environment variable {name} is not set"
                raise EnvUnresolvedError(msg, var_name=name)
            return match.group(0)
        return hit

    return _ENV_REF.sub(repl, text)


async def expand_secret_refs(text: str, cache: ResolvedSecretsCache) -> str:
    """Expand ``${SECRET:…}`` segments using ``ResolvedSecretsCache`` hits.

    Args:
        text (str): Possibly containing ``${SECRET:source:logical_key}`` segments.
        cache (ResolvedSecretsCache): TTL cache keyed by resolved logical keys.

    Returns:
        str: Expanded string without remaining ``${SECRET:…}``.

    Raises:
        ValueError — malformed bracket payload.
        SecretUnresolvedError — no backend exposes the logical key.

    Examples:
        >>> import asyncio
        >>> from sevn.security.secrets.cache import ResolvedSecretsCache
        >>> from sevn.security.secrets.chain import SecretsChain
        >>> class _M:
        ...     async def get(self, k: str) -> str | None:
        ...         return {"k": "V"}.get(k)
        ...     async def set(self, k: str, v: str) -> None: ...
        ...     async def delete(self, k: str) -> None: ...
        >>> async def _run():
        ...     cache = ResolvedSecretsCache(SecretsChain([_M()]), ttl_seconds=0)
        ...     return await expand_secret_refs("${SECRET:p:k}", cache)
        >>> asyncio.run(_run())
        'V'
    """

    async def repl_secret(match: re.Match[str]) -> str:
        inner = match.group(1)
        if ":" not in inner:
            msg = f"invalid SECRET ref (expected source:key): {inner!r}"
            raise ValueError(msg)
        source, logical_key = inner.split(":", 1)
        value = await cache.get_resolved(source, logical_key)
        if value is None:
            msg = f"unresolved secret ref source={source!r} key={logical_key!r}"
            raise SecretUnresolvedError(
                msg,
                logical_key=logical_key,
                source=source,
            )
        return value

    out: list[str] = []
    pos = 0
    for m in _SECRET_REF.finditer(text):
        out.append(text[pos : m.start()])
        out.append(await repl_secret(m))
        pos = m.end()
    out.append(text[pos:])
    return "".join(out)


async def expand_refs_env_then_secret(text: str, cache: ResolvedSecretsCache) -> str:
    """Iterate env pass then secret pass until stable (`specs/02 §2.4 ordering`).

    Each round applies strict ``expand_env_refs`` followed by ``expand_secret_refs``.
    Resolved env values may surface additional ``${SECRET:…}`` segments; resolved
    secrets likewise may reveal further ``${ENV:…}`` references.

    Args:
        text (str): Possibly nested ``${ENV:…}`` / ``${SECRET:…}`` segments.
        cache (ResolvedSecretsCache): TTL cache for secret hits.

    Returns:
        str: Fully-expanded string once no substitutions remain.

    Examples:
        >>> import asyncio
        >>> import os
        >>> from sevn.security.secrets.cache import ResolvedSecretsCache
        >>> from sevn.security.secrets.chain import SecretsChain
        >>> class _M:
        ...     async def get(self, k: str) -> str | None:
        ...         return {"mykey": "z"}.get(k)
        ...     async def set(self, k: str, v: str) -> None: ...
        ...     async def delete(self, k: str) -> None: ...
        >>> prev_a = os.environ.get("PRE")
        >>> prev_b = os.environ.get("SUF")
        >>> os.environ["PRE"] = "he"
        >>> os.environ["SUF"] = "llo:${SECRET:p:mykey}"
        >>> async def _run():
        ...     raw = "${ENV:PRE}${ENV:SUF}"
        ...     cache = ResolvedSecretsCache(SecretsChain([_M()]), ttl_seconds=0)
        ...     return await expand_refs_env_then_secret(raw, cache)
        >>> asyncio.run(_run())
        'hello:z'
        >>> del os.environ["PRE"]
        >>> del os.environ["SUF"]
        >>> if prev_a is not None:
        ...     os.environ["PRE"] = prev_a
        >>> if prev_b is not None:
        ...     os.environ["SUF"] = prev_b
    """

    cur = text
    for _ in range(128):  # defensive cap (pathological self-referential configs)
        nxt = await expand_secret_refs(expand_env_refs(cur, strict=True), cache)
        if nxt == cur:
            return nxt
        cur = nxt
    msg = "${ENV:}/${SECRET:} expansion did not converge"
    raise ValueError(msg)
