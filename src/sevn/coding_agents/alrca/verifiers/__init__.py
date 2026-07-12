"""ALRCA verifier registry — pluggable deterministic + fuzzy verifiers (CA3.4).

Module: sevn.coding_agents.alrca.verifiers
Depends: sevn.coding_agents.alrca.verifiers.base

Exports:
    BuiltinVerifierKind — known verifier spec prefixes.
    VerifierResult — pass/fail result envelope.
    build_verifier — construct a verifier callable from a spec string.
    run_verifier_spec — resolve and run a verifier spec in one call.
"""

from sevn.coding_agents.alrca.verifiers.base import (
    BuiltinVerifierKind,
    VerifierResult,
    build_verifier,
    run_verifier_spec,
)

__all__ = [
    "BuiltinVerifierKind",
    "VerifierResult",
    "build_verifier",
    "run_verifier_spec",
]
