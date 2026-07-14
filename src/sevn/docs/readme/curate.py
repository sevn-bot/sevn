"""Agent-driven curation of curated READMEs (`sevn readme curate`).

Module: sevn.docs.readme.curate
Depends: os, shutil, subprocess, dataclasses, pathlib, sevn.docs.readme.manifest,
    sevn.docs.readme.templates

When a curated subsystem's source changes, the offline generator must not rewrite
its hand-authored Level 1-2 prose. Instead this module drives a coding agent
(``cursor-agent`` or ``claude``) to *edit* the README so its prose reflects the new
behaviour, staying within the slug's template outline. The runner is pluggable and
auto-detected; the driver assembles a self-contained prompt (template + source diff),
invokes the runner to edit exactly the one file, then re-validates.

Exports:
    RunnerKind — supported agent runners.
    CurateResult — outcome of one curation attempt.
    resolve_runner — pick an available runner (config/env/PATH).
    diff_for_globs — git diff of an entry's source_globs.
    build_prompt — assemble the curator prompt.
    invoke_runner — run the resolved runner with a prompt on stdin.
    curate_entry — end-to-end: assemble → invoke → validate.

Examples:
    >>> from sevn.docs.readme.curate import build_prompt
    >>> isinstance(build_prompt(slug="gateway", output="README.md",
    ...     template_text="# <t>", diff="", summary="s"), str)
    True
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from sevn.docs.readme.manifest import ReadmeEntry
from sevn.docs.readme.templates import resolve_template_path, validate_against_template

# Runner binaries in auto-detect preference order.
_RUNNER_BINS: tuple[tuple[str, str], ...] = (
    ("cursor", "cursor-agent"),
    ("claude", "claude"),
)
_DEFAULT_TIMEOUT_S = 300
_RUNNER_ENV_KEYS = ("PATH", "HOME", "USER", "LANG", "LC_ALL", "TMPDIR", "TERM")
_SECRET_RE = re.compile(
    r"(?i)(api[_-]?key|token|secret|authorization|password)\s*[:=]\s*\S+|"
    r"sk-[a-zA-Z0-9_-]{8,}|"
    r"Bearer\s+\S+"
)


def _runner_env() -> dict[str, str]:
    """Return a minimal env for external agent runners (no inherited secrets).

    Returns:
        dict[str, str]: Subset of ``os.environ`` safe to pass to ``subprocess.run``.

    Examples:
        >>> isinstance(_runner_env(), dict)
        True
    """
    return {key: value for key, value in os.environ.items() if key in _RUNNER_ENV_KEYS}


def _sanitize_runner_output(raw: str, *, max_len: int = 200) -> str:
    """Redact likely secrets and truncate runner stderr/stdout for callers.

    Args:
        raw (str): Raw runner output.
        max_len (int): Maximum returned length after redaction.

    Returns:
        str: Safe summary text.

    Examples:
        >>> _sanitize_runner_output("token=abc123")
        '<redacted>'
    """
    text = _SECRET_RE.sub("<redacted>", raw.strip())
    if not text:
        return "(no output)"
    if len(text) > max_len:
        return text[:max_len] + "…"
    return text


@dataclass(frozen=True)
class RunnerKind:
    """A resolved agent runner (name + executable)."""

    name: str
    bin: str

    def command(self, *, model: str | None = None) -> list[str]:
        """Return the non-interactive, edit-capable argv for this runner.

            Args:
        model (str | None): Optional model override.

            Returns:
                list[str]: Argv prefix; the prompt is delivered on stdin.

            Examples:
                >>> RunnerKind("claude", "claude").command()[:2]
                ['claude', '-p']
                >>> "--force" in RunnerKind("cursor", "cursor-agent").command()
                True
        """
        if self.name == "cursor":
            argv = [self.bin, "-p", "--force", "--output-format", "text"]
            if model:
                argv += ["--model", model]
            return argv
        # claude: accept file edits without prompting; the driver validates afterward.
        argv = [self.bin, "-p", "--permission-mode", "acceptEdits"]
        if model:
            argv += ["--model", model]
        return argv


@dataclass
class CurateResult:
    """Outcome of one ``curate_entry`` attempt."""

    slug: str
    status: str  # "updated" | "unchanged" | "skipped" | "invalid" | "error" | "dry-run"
    detail: str = ""
    prompt: str = ""
    template_errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """Return True when curation succeeded or was a no-op.

        Returns:
            bool: True for updated/unchanged/dry-run/skipped states.

        Examples:
            >>> CurateResult("g", "updated").ok
            True
            >>> CurateResult("g", "invalid").ok
            False
        """
        return self.status in {"updated", "unchanged", "dry-run", "skipped"}


def resolve_runner(preference: str | None = None) -> RunnerKind | None:
    """Pick an available agent runner from preference, env, then PATH.

        Args:
    preference (str | None): Explicit runner name (``cursor``/``claude``/``auto``).

        Returns:
            RunnerKind | None: Resolved runner, or None when none is available.

        Examples:
            >>> isinstance(resolve_runner("auto"), (RunnerKind, type(None)))
            True
    """
    want = (preference or os.environ.get("SEVN_README_RUNNER") or "auto").strip().lower()
    for name, binary in _RUNNER_BINS:
        if want in {"auto", name} and shutil.which(binary):
            return RunnerKind(name=name, bin=binary)
    return None


def _glob_to_pathspec(glob: str) -> str:
    """Reduce a source glob to a git pathspec prefix (strip wildcard tail).

        Args:
    glob (str): A manifest source glob (e.g. ``src/sevn/gateway/**``).

        Returns:
            str: Pathspec usable with ``git diff -- <spec>``.

        Examples:
            >>> _glob_to_pathspec("src/sevn/gateway/**")
            'src/sevn/gateway'
            >>> _glob_to_pathspec("src/sevn/config/sections/subagents.py")
            'src/sevn/config/sections/subagents.py'
    """
    out: list[str] = []
    for part in glob.split("/"):
        if any(ch in part for ch in "*?[]"):
            break
        out.append(part)
    return "/".join(out) or glob


def diff_for_globs(
    repo_root: Path,
    source_globs: tuple[str, ...],
    *,
    base: str | None = None,
    staged: bool = False,
    max_chars: int = 24000,
) -> str:
    """Return the git diff of an entry's source files.

    ``base`` diffs ``base..worktree``; ``staged`` diffs the index; otherwise the
    unstaged worktree against HEAD. Output is truncated to ``max_chars`` to bound
    the prompt.

        Args:
    repo_root (Path): Repository root.
    source_globs (tuple[str, ...]): Entry source globs.
    base (str | None): Base ref to diff against.
    staged (bool): Diff the staged index instead of the worktree.
    max_chars (int): Truncation bound.

        Returns:
            str: Unified diff text (possibly truncated), or "" when no diff.

        Examples:
            >>> isinstance(diff_for_globs(Path("."), ("pyproject.toml",)), str)
            True
    """
    pathspecs = sorted({_glob_to_pathspec(g) for g in source_globs})
    argv = ["git", "-C", str(repo_root), "diff"]
    if base:
        argv.append(base)
    elif staged:
        argv.append("--cached")
    argv += ["--", *pathspecs]
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):
        return ""
    diff = proc.stdout
    if len(diff) > max_chars:
        diff = diff[:max_chars] + "\n… (diff truncated)\n"
    return diff


def build_prompt(
    *,
    slug: str,
    output: str,
    template_text: str,
    diff: str,
    summary: str,
) -> str:
    """Assemble the curator prompt for the agent runner.

        Args:
    slug (str): Manifest slug.
    output (str): Repo-relative README path to edit.
    template_text (str): The slug's template outline.
    diff (str): Source diff (may be empty).
    summary (str): Manifest one-line summary.

        Returns:
            str: A self-contained instruction prompt.

        Examples:
            >>> "Edit exactly ONE file" in build_prompt(slug="g", output="o.md",
            ...     template_text="# t", diff="", summary="s")
            True
    """
    diff_block = diff.strip() or "(no source diff supplied — reconcile against the current tree)"
    return f"""You are the **sevn.bot README curator**. Edit exactly ONE file: `{output}` \
(the curated README for the `{slug}` subsystem).

Goal: the subsystem's source changed. Update the curated **Level 1-2** prose so it \
accurately describes the new behaviour, staying within the template outline below.

Hard rules:
- Edit ONLY `{output}`. Touch no other file.
- Preserve the first-line `<!-- curated: … -->` stamp comment verbatim.
- Do NOT hand-author any `<!-- generated -->` … `<!-- /generated -->` region (Level 3
  module inventory and per-module sections). The offline pipeline owns those.
- Keep every required heading from the template outline, at the same level and order.
  You may add subsections between anchors.
- Cite only symbols and paths that actually exist (check with your Read tool). Keep
  Level 1 free of `src/` paths and spec numbers.
- Match the house voice: active, second person, concrete. See `docs/readmes/self-improve.md`
  (reference doc) and `docs/readmes/STANDARD.md` (contract).
- If the diff does not change anything the prose asserts, make NO edit.

Manifest summary for `{slug}`: {summary}

## Template outline (`docs/readmes/_templates/{slug}.md`)
{template_text}

## Source diff (git diff of the subsystem's source_globs)
```diff
{diff_block}
```

When finished, stop. Do not print explanations or summaries.
"""


def invoke_runner(
    runner: RunnerKind,
    prompt: str,
    *,
    repo_root: Path,
    model: str | None = None,
    timeout_s: int = _DEFAULT_TIMEOUT_S,
) -> tuple[bool, str]:
    """Run the agent runner with ``prompt`` on stdin, returning (ok, detail).

        Args:
    runner (RunnerKind): Resolved runner.
    prompt (str): Assembled curator prompt.
    repo_root (Path): Working directory for the runner.
    model (str | None): Optional model override.
    timeout_s (int): Hard timeout.

        Returns:
            tuple[bool, str]: ``(succeeded, detail)`` where detail holds any error text.

        Examples:
            >>> ok, _ = invoke_runner(
            ...     RunnerKind("x", "sevn-no-such-runner-xyz"), "hi", repo_root=Path(".")
            ... )
            >>> ok
            False
    """
    argv = runner.command(model=model)
    try:
        proc = subprocess.run(
            argv,
            input=prompt,
            capture_output=True,
            text=True,
            cwd=str(repo_root),
            env=_runner_env(),
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False, f"{runner.name} timed out after {timeout_s}s"
    except OSError as exc:
        return False, f"{runner.name} failed to launch: {exc}"
    if proc.returncode != 0:
        summary = _sanitize_runner_output(proc.stderr or proc.stdout or "")
        return False, f"{runner.name} exited {proc.returncode}: {summary}"
    return True, ""


def curate_entry(
    repo_root: Path,
    entry: ReadmeEntry,
    *,
    base: str | None = None,
    staged: bool = False,
    runner_preference: str | None = None,
    model: str | None = None,
    dry_run: bool = False,
    validate: bool = True,
    timeout_s: int = _DEFAULT_TIMEOUT_S,
) -> CurateResult:
    """Curate one README end-to-end: assemble prompt, invoke runner, validate.

        Args:
    repo_root (Path): Repository root.
    entry (ReadmeEntry): Manifest row (must be curated).
    base (str | None): Base ref for the source diff.
    staged (bool): Diff the staged index (pre-commit use).
    runner_preference (str | None): Explicit runner name or ``auto``.
    model (str | None): Optional model override.
    dry_run (bool): Assemble and return the prompt without invoking a runner.
    validate (bool): Run template validation on the result.
    timeout_s (int): Runner timeout.

        Returns:
            CurateResult: Structured outcome.

        Examples:
            >>> from sevn.docs.readme.manifest import ReadmeEntry
            >>> e = ReadmeEntry("gateway", "G", "s", "subsystem", "g",
            ...     "docs/readmes/gateway.md", ("src/sevn/gateway/**",), (), curated=True)
            >>> curate_entry(Path("."), e, dry_run=True).status
            'dry-run'
    """
    if not entry.curated:
        return CurateResult(entry.slug, "skipped", "entry is not curated")

    template_path = resolve_template_path(repo_root, entry)
    if not template_path.is_file():
        return CurateResult(entry.slug, "skipped", f"no template at {template_path}")
    template_text = template_path.read_text(encoding="utf-8")
    output_path = repo_root / entry.output

    diff = diff_for_globs(repo_root, entry.source_globs, base=base, staged=staged)
    prompt = build_prompt(
        slug=entry.slug,
        output=entry.output,
        template_text=template_text,
        diff=diff,
        summary=entry.summary,
    )
    if dry_run:
        return CurateResult(entry.slug, "dry-run", "prompt assembled", prompt=prompt)

    runner = resolve_runner(runner_preference)
    if runner is None:
        return CurateResult(entry.slug, "skipped", "no agent runner on PATH (cursor-agent/claude)")

    before = output_path.read_text(encoding="utf-8") if output_path.is_file() else ""
    ok, detail = invoke_runner(
        runner, prompt, repo_root=repo_root, model=model, timeout_s=timeout_s
    )
    if not ok:
        return CurateResult(entry.slug, "error", detail, prompt=prompt)

    after = output_path.read_text(encoding="utf-8") if output_path.is_file() else ""
    status = "updated" if after != before else "unchanged"

    if validate and output_path.is_file():
        errs = [str(e) for e in validate_against_template(template_text, after)]
        if errs:
            return CurateResult(entry.slug, "invalid", "template drift", template_errors=errs)

    return CurateResult(entry.slug, status, f"via {runner.name}")
