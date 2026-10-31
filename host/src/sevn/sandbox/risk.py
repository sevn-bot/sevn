"""approval.risk: score one shell command for the ``full`` access level (D15).

Under approval policy ``auto`` only ``low`` runs without asking, and ``full``
runs it with no confinement. So ``low`` is an allowlist: every command in the
line must be a known read-only program, with no output redirect, no command
substitution, and no argument that makes it write or run something. A line the
scorer cannot parse, or a program it does not know, is at least ``medium``.

``git`` is never ``low``: the bot can write ``.git/config`` with the file tools,
and ``core.fsmonitor`` or a pager there runs a command on ``git status``.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field
from typing import Literal

type Risk = Literal["low", "medium", "high", "destructive"]

_RANK: dict[Risk, int] = {"low": 0, "medium": 1, "high": 2, "destructive": 3}

_READ_ONLY = frozenset(
    {
        "[",
        "basename",
        "cat",
        "cd",
        "cmp",
        "column",
        "comm",
        "cut",
        "date",
        "df",
        "diff",
        "dirname",
        "du",
        "echo",
        "false",
        "file",
        "find",
        "fold",
        "grep",
        "egrep",
        "fgrep",
        "head",
        "id",
        "jq",
        "ls",
        "md5sum",
        "nl",
        "paste",
        "printf",
        "pwd",
        "readlink",
        "realpath",
        "rg",
        "sha1sum",
        "sha256sum",
        "shasum",
        "sort",
        "stat",
        "tail",
        "test",
        "tr",
        "tree",
        "true",
        "uname",
        "uniq",
        "wc",
        "which",
        "whoami",
    }
)
# Arguments that make an otherwise read-only program write files or run commands.
_WRITING_ARGS: dict[str, frozenset[str]] = {
    "find": frozenset(
        {"-delete", "-exec", "-execdir", "-ok", "-okdir", "-fprint", "-fprint0", "-fprintf", "-fls"}
    ),
    "sort": frozenset({"-o", "--output"}),
    "tree": frozenset({"-o"}),
    "rg": frozenset({"--pre"}),
    "diff": frozenset({"--to-file"}),
}
_NETWORK = frozenset(
    {"curl", "wget", "ssh", "scp", "sftp", "rsync", "nc", "ncat", "socat", "telnet", "ftp"}
)
_SHELLS = frozenset({"sh", "bash", "zsh", "dash", "ksh", "fish"})
_INTERPRETERS = frozenset({"python", "python3", "node", "perl", "ruby", "deno", "bun", "php"})
_INLINE_FLAGS = frozenset({"-c", "-e", "--eval", "-p", "--print"})
_HIGH_PROGRAMS = frozenset(
    {
        "eval",
        "exec",
        "source",
        ".",
        "xargs",
        "osascript",
        "kill",
        "pkill",
        "killall",
        "launchctl",
        "systemctl",
        "crontab",
        "defaults",
        "security",
        "dd",
        "shred",
    }
)
_ESCALATE = frozenset({"sudo", "doas", "su"})
_GIT_HIGH = frozenset({"push", "fetch", "pull", "clone", "clean", "reset", "filter-branch"})
_ROOTS = frozenset(
    {"/", "/*", "~", "~/", "~/*", "$HOME", "$HOME/", "$HOME/*", "${HOME}", "/Users", "/home"}
)
_COPIES = frozenset({"cp", "mv", "ln", "install", "rsync"})
_SYSTEM_BINS = (
    "/bin/",
    "/usr/bin/",
    "/usr/local/bin/",
    "/opt/homebrew/bin/",
    "/sbin/",
    "/usr/sbin/",
)
_SEPARATORS = frozenset({"|", "||", "&&", ";", "&", "(", ")", ";;", "|&"})
_OUT_REDIRECTS = frozenset({">", ">>", ">|", "&>", "&>>", ">&", "<>"})
_QUIET_TARGETS = frozenset({"/dev/null", "1", "2", "&1", "&2", "-"})

_SUDO = re.compile(r"(?:^|[\s;&|(])(?:sudo|doas)(?:\s|$)")
_PIPE_SHELL = re.compile(r"\b(?:curl|wget)\b[^|]*\|\s*(?:\S*/)?(?:sh|bash|zsh|dash|ksh)\b")
_REDIRECT = re.compile(r"(?:>>|>)\s*([^\s;|&]+)")
_SUBSTITUTION = re.compile(r"\$\(|`|<\(|>\(")


@dataclass(slots=True)
class _Command:
    words: list[str] = field(default_factory=list[str])
    writes: list[str] = field(default_factory=list[str])
    piped_in: bool = False


def risk_of(command: str) -> Risk:
    """Score one shell command. The listed overrides are always destructive (D15)."""
    if _raw_destructive(command):
        return "destructive"
    commands = _parse(command)
    if commands is None:
        return "medium"
    worst: Risk = "low"
    for item in commands:
        score = _score(item)
        if _RANK[score] > _RANK[worst]:
            worst = score
    if worst == "low" and (_SUBSTITUTION.search(command) or "$" in command):
        return "high" if _SUBSTITUTION.search(command) else "medium"
    return worst


def _raw_destructive(command: str) -> bool:
    if _SUDO.search(command) or _PIPE_SHELL.search(command):
        return True
    return any(_dotfile(match.group(1)) for match in _REDIRECT.finditer(command))


def _parse(command: str) -> list[_Command] | None:
    """Split a line into simple commands. ``None`` when shlex cannot read it."""
    lexer = shlex.shlex(
        command.replace("\r", "\n").replace("\n", " ; "),
        posix=True,
        punctuation_chars=True,
    )
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError:
        return None
    commands: list[_Command] = []
    current = _Command()
    pending_write = False
    for token in tokens:
        if pending_write:
            current.writes.append(token)
            pending_write = False
        elif token in _SEPARATORS:
            if current.words or current.writes:
                commands.append(current)
            current = _Command(piped_in=token in {"|", "|&"})
        elif token in _OUT_REDIRECTS:
            pending_write = True
        elif token in {"<", "<<", "<<<"}:
            continue
        else:
            current.words.append(token)
    if pending_write:
        return None
    if current.words or current.writes:
        commands.append(current)
    return commands


def _score(item: _Command) -> Risk:
    words = _without_assignments(item.words)
    writes = [target for target in item.writes if target not in _QUIET_TARGETS]
    if any(_dotfile(target) for target in writes):
        return "destructive"
    if not words:
        return "medium" if writes or item.words else "low"
    program = _program(words[0])
    args = words[1:]
    special = _special(program, args, piped_in=item.piped_in)
    if special is not None:
        return special
    if writes or item.words != words:
        return "medium"
    if program not in _READ_ONLY:
        return "medium"
    blocked = _WRITING_ARGS.get(program, frozenset())
    for arg in args:
        flag = arg.split("=", 1)[0]
        if flag in blocked or flag.startswith("--output"):
            return "high" if program == "find" else "medium"
    return "low"


def _special(program: str, args: list[str], *, piped_in: bool) -> Risk | None:
    """Scores that do not depend on the read-only allowlist."""
    if program in _ESCALATE or program.startswith("mkfs"):
        return "destructive"
    if program == "rm" and _recursive(args) and any(arg in _ROOTS for arg in args):
        return "destructive"
    if program == "dd" and any(arg.startswith("of=/dev/") for arg in args):
        return "destructive"
    if program == "diskutil" and any(arg.lower().startswith("erase") for arg in args):
        return "destructive"
    if program == "tee" and any(_dotfile(arg) for arg in args if not arg.startswith("-")):
        return "destructive"
    if program in _COPIES and any(_dotpath(arg) for arg in args if not arg.startswith("-")):
        return "high"
    if program in _NETWORK or program in _HIGH_PROGRAMS:
        return "high"
    if program in _SHELLS and (piped_in or "-c" in args or not args):
        return "high"
    if _interpreter(program) and (piped_in or any(arg in _INLINE_FLAGS for arg in args)):
        return "high"
    if program == "base64" and any(arg in {"-d", "-D", "--decode"} for arg in args):
        return "high"
    if program in {"chmod", "chown"} and any(arg in {"-R", "--recursive"} for arg in args):
        return "high"
    if program == "git":
        sub = next((arg for arg in args if not arg.startswith("-")), "")
        return "high" if sub in _GIT_HIGH else "medium"
    return None


def _program(word: str) -> str:
    """The program name. A path outside the system bins is not a known program."""
    if "/" not in word:
        return word
    if word.startswith(_SYSTEM_BINS):
        return word.rsplit("/", 1)[-1]
    return word


def _without_assignments(words: list[str]) -> list[str]:
    """Drop leading ``NAME=value`` words. ``env`` would set them the same way."""
    index = 0
    while index < len(words) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", words[index]):
        index += 1
    return words[index:]


def _interpreter(program: str) -> bool:
    return program in _INTERPRETERS or re.fullmatch(r"python3(?:\.\d+)?", program) is not None


def _recursive(args: list[str]) -> bool:
    for arg in args:
        if arg in {"--recursive", "-r", "-R"}:
            return True
        if arg.startswith("-") and not arg.startswith("--") and ("r" in arg or "R" in arg):
            return True
    return False


def _dotpath(target: str) -> bool:
    """True when any path component is hidden, such as ``~/.ssh/authorized_keys``."""
    return any(part.startswith(".") and part not in {".", ".."} for part in target.split("/"))


def _dotfile(target: str) -> bool:
    leaf = target.rstrip("/").rsplit("/", 1)[-1]
    return leaf.startswith(".") and leaf not in {".", ".."}
