"""Doctor solutions catalog loader (`specs/23-cli.md` §3).

Module: sevn.cli.doctor.solutions
Depends: importlib.resources, json, dataclasses, typing

Exports:
    DoctorSolution — one catalog row for a check id.
    SolutionsCatalog — parsed ``doctor_solutions.json``.
    catalog_resource_path — packaged JSON filename.
    load_solutions_catalog — parse bundled catalog (fail-soft on IO errors).
    lookup_solution — resolve a check id to a catalog row or fallback text.
    solution_for_json — JSON ``solution`` object for ``--json`` envelopes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import resources
from typing import Any

NO_CANNED_SOLUTION = "no canned solution — try `sevn doctor --with-agent`"


@dataclass(frozen=True, slots=True)
class DoctorSolution:
    """One remediation row from ``doctor_solutions.json``."""

    check_id: str
    title: str
    severity: str
    explanation: str
    remediation: tuple[str, ...]
    fix_command: str | None
    auto_fixable: bool
    docs_url: str | None
    agent_only: bool = False

    def to_json(self) -> dict[str, Any]:
        """Serialize for ``--json`` check rows.

        Returns:
            dict[str, Any]: Additive ``solution`` object.

        Examples:
            >>> DoctorSolution(
            ...     "operator_lock", "Operator lock", "warn", "stale", ("remove lock",),
            ...     "sevn doctor --fix --yes", True, None,
            ... ).to_json()["auto_fixable"]
            True
        """
        out: dict[str, Any] = {
            "title": self.title,
            "severity": self.severity,
            "explanation": self.explanation,
            "remediation": list(self.remediation),
            "fix_command": self.fix_command,
            "auto_fixable": self.auto_fixable,
            "docs_url": self.docs_url,
        }
        if self.agent_only:
            out["agent_only"] = True
        return out


@dataclass(frozen=True, slots=True)
class SolutionsCatalog:
    """Parsed bundled doctor solutions catalog."""

    schema_version: int
    by_id: dict[str, DoctorSolution]

    def get(self, check_id: str) -> DoctorSolution | None:
        """Return the catalog row for ``check_id`` when present.

        Args:
            check_id (str): Doctor probe id.

        Returns:
            DoctorSolution | None: Catalog row or ``None``.

        Examples:
            >>> isinstance(SolutionsCatalog(1, {}).get("missing"), (DoctorSolution, type(None)))
            True
        """
        return self.by_id.get(check_id)


def catalog_resource_path() -> str:
    """Return the packaged JSON filename under ``sevn.data``.

    Returns:
        str: Relative resource path.

    Examples:
        >>> catalog_resource_path()
        'doctor_solutions.json'
    """
    return "doctor_solutions.json"


def _parse_solution(check_id: str, raw: dict[str, Any]) -> DoctorSolution:
    """Parse one catalog row from raw JSON.

    Args:
        check_id (str): Doctor probe id.
        raw (dict[str, Any]): Raw catalog object.

    Returns:
        DoctorSolution: Parsed row.

    Examples:
        >>> _parse_solution("operator_lock", {"title": "t", "severity": "warn", "explanation": "e", "remediation": ["a"], "auto_fixable": True}).check_id
        'operator_lock'
    """
    remediation = raw.get("remediation")
    if not isinstance(remediation, list):
        msg = f"{check_id}: remediation must be a list"
        raise ValueError(msg)
    return DoctorSolution(
        check_id=check_id,
        title=str(raw["title"]),
        severity=str(raw["severity"]),
        explanation=str(raw["explanation"]),
        remediation=tuple(str(step) for step in remediation),
        fix_command=raw.get("fix_command") if raw.get("fix_command") is not None else None,
        auto_fixable=bool(raw.get("auto_fixable", False)),
        docs_url=raw.get("docs_url") if raw.get("docs_url") is not None else None,
        agent_only=bool(raw.get("agent_only", False)),
    )


def load_solutions_catalog() -> SolutionsCatalog:
    """Load and parse the bundled solutions catalog.

    Returns:
        SolutionsCatalog: Parsed catalog; empty on load/parse failure (fail-soft).

    Examples:
        >>> cat = load_solutions_catalog()
        >>> cat.schema_version >= 1
        True
        >>> "operator_lock" in cat.by_id
        True
    """
    try:
        ref = resources.files("sevn.data") / catalog_resource_path()
        doc = json.loads(ref.read_text(encoding="utf-8"))
    except (OSError, TypeError, json.JSONDecodeError, AttributeError):
        return SolutionsCatalog(schema_version=1, by_id={})
    if not isinstance(doc, dict):
        return SolutionsCatalog(schema_version=1, by_id={})
    solutions_raw = doc.get("solutions")
    if not isinstance(solutions_raw, dict):
        return SolutionsCatalog(schema_version=1, by_id={})
    by_id: dict[str, DoctorSolution] = {}
    for check_id, row in solutions_raw.items():
        if isinstance(row, dict):
            try:
                by_id[str(check_id)] = _parse_solution(str(check_id), row)
            except (KeyError, TypeError, ValueError):
                continue
    schema_version = int(doc.get("schema_version", 1))
    return SolutionsCatalog(schema_version=schema_version, by_id=by_id)


def lookup_solution(
    check_id: str, catalog: SolutionsCatalog | None = None
) -> DoctorSolution | None:
    """Resolve a check id against the bundled catalog.

    Args:
        check_id (str): Doctor probe id.
        catalog (SolutionsCatalog | None): Optional pre-loaded catalog.

    Returns:
        DoctorSolution | None: Catalog row when present.

    Examples:
        >>> lookup_solution("operator_lock") is not None
        True
    """
    doc = catalog or load_solutions_catalog()
    return doc.get(check_id)


def solution_for_json(check_id: str, catalog: SolutionsCatalog | None = None) -> dict[str, Any]:
    """Build the additive ``solution`` object for a failing/warn check row.

    Args:
        check_id (str): Doctor probe id.
        catalog (SolutionsCatalog | None): Optional pre-loaded catalog.

    Returns:
        dict[str, Any]: Catalog payload or fallback explanation-only object.

    Examples:
        >>> solution_for_json("operator_lock")["explanation"]
        'An advisory operator lock file blocks mutating CLI commands.'
    """
    row = lookup_solution(check_id, catalog)
    if row is None:
        return {"explanation": NO_CANNED_SOLUTION}
    return row.to_json()


__all__ = [
    "NO_CANNED_SOLUTION",
    "DoctorSolution",
    "SolutionsCatalog",
    "catalog_resource_path",
    "load_solutions_catalog",
    "lookup_solution",
    "solution_for_json",
]
