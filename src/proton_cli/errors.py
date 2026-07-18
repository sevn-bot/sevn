"""Typed errors that drive the CLI exit-code scheme."""

from __future__ import annotations


class ExitCoder(Exception):
    """Base for errors carrying a process exit code."""

    def exit_code(self) -> int:
        return 1


class NotFound(ExitCoder):
    """REF matched no resource. Exit 3."""

    def __init__(self, kind: str, ref: str = "") -> None:
        self.kind = kind
        self.ref = ref
        if ref:
            super().__init__(f"no {kind} matching {ref!r}")
        else:
            super().__init__(f"no {kind} found")

    def exit_code(self) -> int:
        return 3


class Ambiguous(ExitCoder):
    """REF matched more than one resource. Exit 4."""

    def __init__(self, kind: str, ref: str, candidates: list[tuple[str, str]]) -> None:
        self.kind = kind
        self.ref = ref
        self.candidates = candidates
        lines = [f"ambiguous: {len(candidates)} {kind}s match {ref!r}:"]
        for cid, label in candidates:
            line = f"  {cid}"
            if label:
                line += f"  {label}"
            lines.append(line)
        super().__init__("\n".join(lines))

    def exit_code(self) -> int:
        return 4


class Exit(ExitCoder):
    """Wrap an error with an explicit exit code."""

    def __init__(self, code: int, err: Exception) -> None:
        self.code = code
        self.err = err
        super().__init__(str(err))

    def exit_code(self) -> int:
        return self.code


def classify_exit_code(err: BaseException | None) -> int:
    """Map an exception to a CLI exit code."""
    if err is None:
        return 0
    if isinstance(err, ExitCoder):
        return err.exit_code()
    from proton_cli.proton.errors import ErrUnauthorized

    if isinstance(err, ErrUnauthorized):
        return 2
    msg = str(err).lower()
    if "unauthorized" in msg or ("auth" in msg and "required" in msg):
        return 2
    return 1
