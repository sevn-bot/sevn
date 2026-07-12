"""Pydantic types for code-understanding settings and digest payloads.

Module: sevn.code_understanding.models
Depends: pydantic

Exports:
    Classes:
        MycodeScanDigest — deterministic scan result for one repository tree.
        MycodeFileEntry — per-file symbol summary inside a digest.
        MycodeSettings — ``code_understanding.mycode`` subtree (`specs/28-code-understanding.md` §2.1).
        CodeGraphRagSettings — ``code_understanding.code_graph_rag`` subtree.
        RoamCodeSettings — ``code_understanding.roam_code`` subtree.
        GraphifyProfile — one Graphify profile (`specs/28-code-understanding.md` §3.2).
        GraphifySettings — ``code_understanding.graphify`` subtree.
        CodeReviewGraphSettings — ``code_understanding.code_review_graph`` subtree.
        CodeUnderstandingSettings — root ``code_understanding.*`` block.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

_ALLOWED_CLI_FLAGS: frozenset[str] = frozenset(
    {
        "--no-viz",
        "--mode",
        "deep",
        "shallow",
        "--keep-cache",
        "--force",
    }
)


class MycodeFileEntry(BaseModel):
    """One file's deterministic summary inside a ``MycodeScanDigest``.

    Attributes:
        path: Repository-relative POSIX path.
        language: Language tag (``python``, ``typescript``, ``go``, ``rust``, ``other``).
        line_count: Total number of lines in the file at scan time.
        symbols: Best-effort list of declared module/class/function names.
        imports: Best-effort list of imports referenced from the file.

    Example:
        >>> MycodeFileEntry(path="a.py", language="python", line_count=3).path
        'a.py'
    """

    model_config = ConfigDict(extra="forbid")

    path: str
    language: str
    line_count: int = Field(default=0, ge=0)
    symbols: list[str] = Field(default_factory=list)
    imports: list[str] = Field(default_factory=list)


class MycodeScanDigest(BaseModel):
    """Deterministic walk result for one repository tree.

    Attributes:
        root: Absolute repository root path (string form).
        files: Per-file summaries in deterministic (sorted) order.
        ignored: Patterns that were honoured during the walk.

    Example:
        >>> MycodeScanDigest(root="/r", files=[], ignored=[]).root
        '/r'
    """

    model_config = ConfigDict(extra="forbid")

    root: str
    files: list[MycodeFileEntry] = Field(default_factory=list)
    ignored: list[str] = Field(default_factory=list)


class MycodeSettings(BaseModel):
    """``code_understanding.mycode`` subtree (`specs/28-code-understanding.md` §2.1).

    Attributes:
        enabled: Master toggle for the MYCODE layer.
        default_root_path: Workspace-relative root override; resolved by caller.
        output_path: Destination ``MYCODE.md``; when unset, callers resolve
            ``<repo>/.index/mycode/MYCODE.md`` (constant ``DEFAULT_MYCODE_OUTPUT_RELATIVE`` in
            ``sevn.config.defaults``).
        ignore_patterns: gitignore-style fragments merged with ``.llmignore``.

    Example:
        >>> MycodeSettings().enabled
        True
    """

    model_config = ConfigDict(extra="allow")

    enabled: bool = True
    default_root_path: str | None = None
    output_path: str | None = None
    ignore_patterns: list[str] = Field(default_factory=list)


class CodeGraphRagSettings(BaseModel):
    """``code_understanding.code_graph_rag`` subtree.

    Attributes:
        enabled: Off by default; requires optional extra install.
        host_ref: Secret-handle reference for Memgraph host.
        port_ref: Secret-handle reference for Memgraph port.
        database_ref: Secret-handle reference for the database name.
        auth_ref: Secret-handle reference for credentials.
        index_path: Workspace-relative index path aligned with sandbox mounts.
        repo_root: Workspace-relative repo root for CGR ingestion.

    Example:
        >>> CodeGraphRagSettings().enabled
        False
    """

    model_config = ConfigDict(extra="allow")

    enabled: bool = False
    host_ref: str | None = None
    port_ref: str | None = None
    database_ref: str | None = None
    auth_ref: str | None = None
    index_path: str | None = None
    repo_root: str | None = None


class RoamCodeSettings(BaseModel):
    """``code_understanding.roam_code`` subtree.

    Attributes:
        enabled: On by default; concrete wiring lands in a later spec.

    Example:
        >>> RoamCodeSettings().enabled
        True
    """

    model_config = ConfigDict(extra="allow")

    enabled: bool = True


class GraphifyProfile(BaseModel):
    """One Graphify profile (`specs/28-code-understanding.md` §3.2).

    ``cli_flags`` are validated against a small server-side allowlist so the
    skill wrapper can build argv from config alone without accepting model
    input. Unknown flags fail fast at validation time.

    Attributes:
        id: Stable identifier (``default`` for bootstrap).
        label: Optional human label for dashboards.
        root_path: Absolute repo root the graph covers.
        output_dir: Absolute directory holding ``GRAPH_REPORT.md`` / ``graph.json``.
        graphifyignore: Optional path to a ``graphifyignore`` file.
        cli_flags: Allowlisted Graphify CLI flags.

    Example:
        >>> GraphifyProfile(id="default", root_path="/r", output_dir="/o").id
        'default'
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    label: str | None = None
    root_path: str = Field(min_length=1)
    output_dir: str = Field(min_length=1)
    graphifyignore: str | None = None
    cli_flags: list[str] = Field(default_factory=list)

    def validated_cli_flags(self) -> list[str]:
        """Return ``cli_flags`` after checking each entry against the allowlist.

        Args:
            self (GraphifyProfile): Profile instance.

        Returns:
            list[str]: Validated flag list (copy of ``self.cli_flags``).

        Raises:
            ValueError: When any flag is not in the server-side allowlist.

        Examples:
            >>> GraphifyProfile(
            ...     id="d", root_path="/r", output_dir="/o",
            ... ).validated_cli_flags()
            []
        """
        out: list[str] = []
        for flag in self.cli_flags:
            if flag not in _ALLOWED_CLI_FLAGS:
                msg = (
                    f"unsupported graphify cli_flag {flag!r}; allowed: "
                    f"{sorted(_ALLOWED_CLI_FLAGS)} (specs/28-code-understanding.md §3.2)"
                )
                raise ValueError(msg)
            out.append(flag)
        return out


class GraphifySettings(BaseModel):
    """``code_understanding.graphify`` subtree.

    Attributes:
        enabled: Off by default; heavy deps optional.
        profiles: Explicit profile list; bootstrap when empty + enabled.
        mcp: Optional MCP opt-in object (per-profile or default-profile).

    Example:
        >>> GraphifySettings().enabled
        False
    """

    model_config = ConfigDict(extra="allow")

    enabled: bool = False
    profiles: list[GraphifyProfile] = Field(default_factory=list)
    mcp: dict[str, object] | None = None


class CodeReviewGraphSettings(BaseModel):
    """``code_understanding.code_review_graph`` subtree (`specs/28-code-understanding.md` §2.1).

    Attributes:
        enabled: Off by default; MCP requires explicit ``mcp.enabled`` opt-in.
        repo_root: Workspace-relative repo root; default primary repo root at runtime.
        command: Optional ``argv[0]`` override; default ships via ``code-review-graph`` extra.
        tool_preset: ``read_only`` (curated MCP tools) or ``full`` (upstream-wide exposure).
        mcp: Optional explicit MCP opt-in object (``enabled`` boolean).

    Example:
        >>> CodeReviewGraphSettings().enabled
        False
    """

    model_config = ConfigDict(extra="allow")

    enabled: bool = False
    repo_root: str | None = None
    command: str | None = None
    tool_preset: str = "read_only"
    mcp: dict[str, object] | None = None

    @field_validator("tool_preset")
    @classmethod
    def _validate_tool_preset(cls, v: str) -> str:
        """Reject unknown ``tool_preset`` values at parse time.

        Args:
            cls (type): Model class.
            v (str): Preset string from JSON.

        Returns:
            str: Validated preset.

        Raises:
            ValueError: When preset is not ``read_only`` or ``full``.

        Examples:
            >>> CodeReviewGraphSettings._validate_tool_preset("read_only")
            'read_only'
        """
        if v not in {"read_only", "full"}:
            msg = f"unsupported code_review_graph.tool_preset {v!r}; allowed: read_only, full"
            raise ValueError(msg)
        return v


class CodeUnderstandingSettings(BaseModel):
    """Root ``code_understanding.*`` block (`specs/28-code-understanding.md` §2.1).

    Attributes:
        mycode: ``mycode.*`` subtree.
        code_graph_rag: ``code_graph_rag.*`` subtree.
        code_review_graph: ``code_review_graph.*`` subtree.
        roam_code: ``roam_code.*`` subtree.
        graphify: ``graphify.*`` subtree.

    Example:
        >>> CodeUnderstandingSettings().mycode.enabled
        True
    """

    model_config = ConfigDict(extra="allow")

    mycode: MycodeSettings = Field(default_factory=MycodeSettings)
    code_graph_rag: CodeGraphRagSettings = Field(default_factory=CodeGraphRagSettings)
    code_review_graph: CodeReviewGraphSettings = Field(default_factory=CodeReviewGraphSettings)
    roam_code: RoamCodeSettings = Field(default_factory=RoamCodeSettings)
    graphify: GraphifySettings = Field(default_factory=GraphifySettings)
