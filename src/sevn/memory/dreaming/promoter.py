"""``MEMORY.md`` append + manifest IO (`specs/31-memory-dreaming.md` §2.2).

Module: sevn.memory.dreaming.promoter
Depends: json, pathlib

Exports:
    dreams_dir — ``memory/.dreams`` root under workspace.
    ensure_tree — create candidate/promoted/pending dirs.
    render_memory_lines — markdown bullets for ``MEMORY.md``.
    write_candidate_snapshot — persist scored candidate JSON.
    append_dreams_diary — human-facing ``DREAMS.md`` entries.
    promote_auto_batch — append + promoted manifest for auto mode.
    write_pending_files — ack queue JSON files.
    build_run_result — wrap a :class:`~sevn.memory.dreaming.models.DreamingRunResult`.
"""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

from sevn.memory.dreaming.models import (
    DreamingCandidate,
    DreamingRunResult,
    MemoryMdAnchor,
    PromotedBatchManifest,
    PromotedManifestRow,
    PromotionMode,
)


def _line_count(text: str) -> int:
    """Count logical lines in ``text`` (partial final line counts as one).

    Args:
        text (str): Fragment to measure.

    Returns:
        int: Number of lines (zero for empty).

    Examples:
        >>> _line_count("")
        0
        >>> _line_count("a\\nb\\n")
        2
        >>> _line_count("solo")
        1
    """

    if not text:
        return 0
    n = text.count("\n")
    if not text.endswith("\n"):
        n += 1
    return n


def dreams_dir(workspace_root: Path) -> Path:
    """Return ``workspace_root/memory/.dreams``.

    Args:
        workspace_root (Path): Workspace content root.

    Returns:
        Path: Dreaming artefact directory.

    Examples:
        >>> from pathlib import Path
        >>> dreams_dir(Path("/w")) == Path("/w") / "memory" / ".dreams"
        True
    """
    return workspace_root / "memory" / ".dreams"


def ensure_tree(workspace_root: Path) -> None:
    """Create ``candidates``, ``promoted``, ``pending`` under ``.dreams``.

    Args:
        workspace_root (Path): Workspace content root.

    Examples:
        >>> from pathlib import Path
        >>> from tempfile import TemporaryDirectory
        >>> with TemporaryDirectory() as td:
        ...     root = Path(td)
        ...     ensure_tree(root)
        ...     (dreams_dir(root) / "pending").is_dir()
        True
    """
    base = dreams_dir(workspace_root)
    for sub in ("candidates", "promoted", "pending"):
        (base / sub).mkdir(parents=True, exist_ok=True)


def render_memory_lines(candidates: list[DreamingCandidate]) -> str:
    """Render bullet lines appended to ``MEMORY.md``.

    Args:
        candidates (list[DreamingCandidate]): Promotion rows.

    Returns:
        str: Markdown fragment (empty string when no candidates).

    Examples:
        >>> from sevn.memory.dreaming.models import DreamingCandidate
        >>> render_memory_lines([]) == ""
        True
    """
    lines: list[str] = []
    for c in candidates:
        sources = ",".join(c.source_keys[:6])
        line = f"- **{c.topic}**: {c.value}"
        if sources:
            line += f" _(`{sources}`)_"
        lines.append(line)
    if not lines:
        return ""
    return "\n".join(lines) + "\n"


def write_candidate_snapshot(
    workspace_root: Path, run_id: str, candidates: list[DreamingCandidate]
) -> Path:
    """Persist full candidate list for the run.

    Args:
        workspace_root (Path): Workspace content root.
        run_id (str): Dreaming run identifier.
        candidates (list[DreamingCandidate],): Snapshot rows.

    Returns:
        Path: Written JSON path under ``candidates/``.

    Examples:
        >>> from pathlib import Path
        >>> from tempfile import TemporaryDirectory
        >>> from sevn.memory.dreaming.models import DreamingCandidate
        >>> with TemporaryDirectory() as td:
        ...     root = Path(td)
        ...     c = DreamingCandidate(candidate_id="x", topic="t", value="v", score=0.5)
        ...     p = write_candidate_snapshot(root, "rid", [c])
        ...     p.name
        'rid.json'
    """
    ensure_tree(workspace_root)
    path = dreams_dir(workspace_root) / "candidates" / f"{run_id}.json"
    path.write_text(
        json.dumps([c.model_dump(mode="json") for c in candidates], indent=2),
        encoding="utf-8",
    )
    return path


def append_dreams_diary(workspace_root: Path, *, run_id: str, body: str) -> None:
    """Append a human-facing section to ``DREAMS.md``.

    Args:
        workspace_root (Path): Workspace content root.
        run_id (str): Dreaming run identifier for heading text.
        body (str): Markdown body without outer heading.

    Examples:
        >>> from pathlib import Path
        >>> from tempfile import TemporaryDirectory
        >>> with TemporaryDirectory() as td:
        ...     root = Path(td)
        ...     append_dreams_diary(root, run_id="r1", body="hello")
        ...     (root / "DREAMS.md").read_text(encoding="utf-8").count("r1") >= 1
        True
    """
    path = workspace_root / "DREAMS.md"
    if body and not body.endswith("\n"):
        body += "\n"
    hdr = f"\n## Dreaming run `{run_id}`\n\n"
    if not path.is_file():
        path.write_text("# Dreams diary\n" + hdr + body, encoding="utf-8")
        return
    with path.open("a", encoding="utf-8") as fh:
        fh.write(hdr + body)


def promote_auto_batch(
    workspace_root: Path,
    *,
    run_id: str,
    mode: PromotionMode,
    candidates: list[DreamingCandidate],
) -> tuple[str, Path, PromotedBatchManifest]:
    """Append promoted lines to ``MEMORY.md`` and write rollback manifest.

    Args:
        workspace_root (Path): Workspace content root.
        run_id (str): Dreaming run identifier.
        mode (PromotionMode): ``auto`` or ``ack_required`` (stored in manifest).
        candidates (list[DreamingCandidate]): Rows to append this batch.

    Returns:
        tuple[str, Path, PromotedBatchManifest]: Markdown fragment, manifest path, manifest model.

    Examples:
        >>> from pathlib import Path
        >>> from tempfile import TemporaryDirectory
        >>> from sevn.memory.dreaming.models import DreamingCandidate
        >>> with TemporaryDirectory() as td:
        ...     root = Path(td)
        ...     c = DreamingCandidate(candidate_id="c1", topic="t", value="v", score=0.9)
        ...     txt, man, m = promote_auto_batch(root, run_id="r1", mode="auto", candidates=[c])
        ...     "v" in txt and m.run_id == "r1"
        True
    """
    ensure_tree(workspace_root)
    memory_path = workspace_root / "MEMORY.md"
    pre = memory_path.read_bytes() if memory_path.is_file() else b""
    pre_len = len(pre)
    pre_text = pre.decode("utf-8", errors="replace")
    line_cursor = _line_count(pre_text)
    text = render_memory_lines(candidates)
    if text:
        with memory_path.open("ab") as fh:
            fh.write(text.encode("utf-8"))
    post = memory_path.read_bytes()
    post_len = len(post)
    anchors: list[PromotedManifestRow] = []
    cursor = pre_len
    for c in candidates:
        line = render_memory_lines([c])
        b = line.encode("utf-8")
        start = cursor
        end = cursor + len(b)
        block_lines = _line_count(line)
        line_start = line_cursor + 1
        line_end = line_cursor + block_lines
        line_cursor = line_end
        digest = sha256(b).hexdigest()
        anchors.append(
            PromotedManifestRow(
                topic=c.topic,
                value=c.value,
                score=c.score,
                source_keys=list(c.source_keys),
                memory_md_anchor=MemoryMdAnchor(
                    line_start=line_start,
                    line_end=line_end,
                    content_sha256=digest,
                    byte_start=start,
                    byte_end=end,
                ),
            ),
        )
        cursor = end
    manifest = PromotedBatchManifest(
        run_id=run_id,
        mode=mode,
        memory_md_pre_bytes=pre_len,
        memory_md_post_bytes=post_len,
        rows=anchors,
    )
    man_path = dreams_dir(workspace_root) / "promoted" / f"{run_id}.json"
    man_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    return text, man_path, manifest


def write_pending_files(
    workspace_root: Path,
    *,
    run_id: str,
    candidates: list[DreamingCandidate],
) -> int:
    """Write ``ack_required`` JSON files; return count written.

    Args:
        workspace_root (Path): Workspace content root.
        run_id (str): Dreaming run identifier prefix.
        candidates (list[DreamingCandidate]): Rows awaiting operator ack.

    Returns:
        int: Number of pending JSON files written.

    Examples:
        >>> from pathlib import Path
        >>> from tempfile import TemporaryDirectory
        >>> from sevn.memory.dreaming.models import DreamingCandidate
        >>> with TemporaryDirectory() as td:
        ...     root = Path(td)
        ...     c = DreamingCandidate(candidate_id="c1", topic="t", value="v", score=0.9)
        ...     write_pending_files(root, run_id="r1", candidates=[c]) == 1
        True
    """
    ensure_tree(workspace_root)
    pending_dir = dreams_dir(workspace_root) / "pending"
    n = 0
    for c in candidates:
        pid = f"{run_id}_{c.candidate_id}"
        path = pending_dir / f"{pid}.json"
        payload = {"run_id": run_id, "candidate": c.model_dump(mode="json")}
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        n += 1
    return n


def build_run_result(
    *,
    run_id: str,
    mode: PromotionMode,
    promoted: list[DreamingCandidate],
    skipped: list[tuple[DreamingCandidate, str]],
    dreams_md_append: str,
    promoted_manifest_path: Path,
) -> DreamingRunResult:
    """Assemble typed run result.

    Args:
        run_id (str): Run identifier.
        mode (PromotionMode): Promotion mode for this pass.
        promoted (list[DreamingCandidate]): Successful ``MEMORY.md`` promotions.
        skipped (list[tuple[DreamingCandidate, str]]): Skipped ledger.
        dreams_md_append (str): Diary body fragment.
        promoted_manifest_path (Path): Manifest or queue summary path.

    Returns:
        DreamingRunResult: Pydantic payload for callers.

    Examples:
        >>> from pathlib import Path
        >>> from sevn.memory.dreaming.models import DreamingRunResult
        >>> isinstance(
        ...     build_run_result(
        ...         run_id="r",
        ...         mode="auto",
        ...         promoted=[],
        ...         skipped=[],
        ...         dreams_md_append="",
        ...         promoted_manifest_path=Path("m.json"),
        ...     ),
        ...     DreamingRunResult,
        ... )
        True
    """
    return DreamingRunResult(
        run_id=run_id,
        mode=mode,
        promoted=promoted,
        skipped=skipped,
        dreams_md_append=dreams_md_append,
        promoted_manifest_path=promoted_manifest_path,
    )
