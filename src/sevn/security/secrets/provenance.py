"""Secret resolution provenance without exposing plaintext (``specs/06-secrets.md`` §2.2).

Module: sevn.security.secrets.provenance
Depends: sevn.security.secrets.chain

Exports:
    SecretProvenanceReport — winning source label + logical key; never carries values.
    resolve_secret_provenance — which chain backend answered for a logical key.
    provenance_for_cache_entry — provenance snapshot for a cached resolution.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sevn.security.secrets.cache import ResolvedSecretsCache
    from sevn.security.secrets.chain import SecretsChain


@dataclass(frozen=True, slots=True)
class SecretProvenanceReport:
    """Which backend answered a lookup — never includes the secret value."""

    source: str
    logical_key: str
    value: None = None

    def __repr__(self) -> str:
        """Return a debug representation without secret material.

        Returns:
            str: Source label and logical key only.

        Examples:
            >>> repr(SecretProvenanceReport(source="encrypted_file", logical_key="k"))
            "SecretProvenanceReport(source='encrypted_file', logical_key='k')"
        """
        return f"SecretProvenanceReport(source={self.source!r}, logical_key={self.logical_key!r})"


async def resolve_secret_provenance(
    chain: SecretsChain,
    logical_key: str,
) -> SecretProvenanceReport | None:
    """Return the label of the first chain backend that holds ``logical_key``.

    Args:
        chain (SecretsChain): Ordered workspace backends.
        logical_key (str): Logical secret id.

    Returns:
        SecretProvenanceReport | None: Provenance when found; ``None`` when absent.

    Examples:
        >>> # See tests/open_issues_sweep/batch_e/test_secret_precedence_w23_red.py.
        >>> True
        True
    """
    for label, backend in zip(chain.backend_labels, chain.backends, strict=True):
        hit = await backend.get(logical_key)
        if hit is not None:
            return SecretProvenanceReport(source=label, logical_key=logical_key)
    return None


def provenance_for_cache_entry(
    cache: ResolvedSecretsCache,
    *,
    logical_key: str,
) -> SecretProvenanceReport:
    """Return provenance recorded for a cached ``logical_key`` (no plaintext).

    Args:
        cache (ResolvedSecretsCache): Cache that previously resolved the key.
        logical_key (str): Logical secret id used in ``get_resolved``.

    Returns:
        SecretProvenanceReport: Source label and key only.

    Raises:
        KeyError: When no provenance was recorded for ``logical_key``.

    Examples:
        >>> # See tests/open_issues_sweep/batch_e/test_secret_precedence_w23_red.py.
        >>> True
        True
    """
    report = cache.lookup_provenance(logical_key=logical_key)
    if report is None:
        msg = f"no provenance recorded for logical_key={logical_key!r}"
        raise KeyError(msg)
    return report
