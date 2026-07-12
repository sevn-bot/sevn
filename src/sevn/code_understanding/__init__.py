"""Code-understanding stack: MYCODE, CGR, roam-code, Graphify (`specs/28-code-understanding.md`).

Module: sevn.code_understanding
Depends: sevn.code_understanding.models, sevn.code_understanding.mycode_scan,
    sevn.code_understanding.mycode_generate, sevn.code_understanding.graphify,
    sevn.code_understanding.cgr_adapter, sevn.code_understanding.roam_code_adapter

Exports:
    Classes:
        MycodeScanDigest — deterministic scan result type.
        GraphifyProfile — Graphify profile model.
        CodeUnderstandingSettings — root ``code_understanding.*`` settings fragment.
    Functions:
        scan_repo — deterministic repository walker.
        generate_mycode_markdown — render digest to markdown.
        write_mycode — atomic ``MYCODE.md`` writer.
        resolve_profiles — apply Graphify bootstrap rule.
        graph_report_path — ``GRAPH_REPORT.md`` path helper.
        graph_json_path — ``graph.json`` path helper.
        profile_covers — path-coverage predicate.
        search_tool_prefix — executor search-tool prefix text (§2.5).
        active_profiles_with_report — filter profiles with on-disk report.
        build_cgr_argv — allowlisted CGR argv builder.
        read_export_capped — truncate CGR export payload.

Examples:
    >>> from sevn.code_understanding import CodeUnderstandingSettings
    >>> CodeUnderstandingSettings().mycode.enabled
    True
"""

from __future__ import annotations

from sevn.code_understanding.cgr_adapter import (
    CGR_ALLOWED_SUBCOMMANDS,
    build_cgr_argv,
    read_export_capped,
)
from sevn.code_understanding.graphify import (
    active_profiles_with_report,
    graph_json_path,
    graph_report_path,
    profile_covers,
    resolve_profiles,
    search_tool_prefix,
)
from sevn.code_understanding.models import (
    CodeGraphRagSettings,
    CodeUnderstandingSettings,
    GraphifyProfile,
    GraphifySettings,
    MycodeFileEntry,
    MycodeScanDigest,
    MycodeSettings,
    RoamCodeSettings,
)
from sevn.code_understanding.mycode_cache import scan_repo_cached
from sevn.code_understanding.mycode_generate import (
    Transport,
    generate_mycode_markdown,
    write_mycode,
)
from sevn.code_understanding.mycode_scan import scan_repo
from sevn.code_understanding.roam_code_adapter import RoamCodeAdapter

__all__ = [
    "CGR_ALLOWED_SUBCOMMANDS",
    "CodeGraphRagSettings",
    "CodeUnderstandingSettings",
    "GraphifyProfile",
    "GraphifySettings",
    "MycodeFileEntry",
    "MycodeScanDigest",
    "MycodeSettings",
    "RoamCodeAdapter",
    "RoamCodeSettings",
    "Transport",
    "active_profiles_with_report",
    "build_cgr_argv",
    "generate_mycode_markdown",
    "graph_json_path",
    "graph_report_path",
    "profile_covers",
    "read_export_capped",
    "resolve_profiles",
    "scan_repo",
    "scan_repo_cached",
    "search_tool_prefix",
    "write_mycode",
]
