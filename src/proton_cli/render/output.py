"""Output rendering: text tables and JSON/YAML."""

from __future__ import annotations

import json
import sys
from enum import Enum
from typing import Any, TextIO

import yaml


class Format(str, Enum):
    TEXT = "text"
    JSON = "json"
    YAML = "yaml"


def parse_format(value: str) -> Format:
    try:
        return Format(value.lower())
    except ValueError as exc:
        msg = f"invalid output format: {value!r} (expected text, json, yaml)"
        raise ValueError(msg) from exc


class Renderer:
    def __init__(
        self,
        fmt: Format,
        stdout: TextIO | None = None,
        stderr: TextIO | None = None,
        *,
        quiet: bool = False,
    ) -> None:
        self.format = fmt
        self.stdout = stdout or sys.stdout
        self.stderr = stderr or sys.stderr
        self.quiet = quiet

    def json_body(self, body: bytes) -> None:
        """Print raw JSON bytes (API passthrough)."""
        if self.format == Format.JSON:
            try:
                parsed = json.loads(body)
                json.dump(parsed, self.stdout, indent=2)
                self.stdout.write("\n")
            except json.JSONDecodeError:
                self.stdout.write(body.decode("utf-8", errors="replace"))
                if not body.endswith(b"\n"):
                    self.stdout.write("\n")
        elif self.format == Format.YAML:
            try:
                parsed = json.loads(body)
                yaml.safe_dump(parsed, self.stdout, sort_keys=False)
            except json.JSONDecodeError:
                self.stdout.write(body.decode("utf-8", errors="replace"))
        else:
            self.stdout.write(body.decode("utf-8", errors="replace"))
            if not body.endswith(b"\n"):
                self.stdout.write("\n")

    def object(self, data: Any) -> None:
        if self.format == Format.JSON:
            json.dump(_to_snake_obj(data), self.stdout, indent=2, default=str)
            self.stdout.write("\n")
        elif self.format == Format.YAML:
            yaml.safe_dump(_to_snake_obj(data), self.stdout, sort_keys=False)
        else:
            if isinstance(data, list):
                for row in data:
                    self.stdout.write(f"{row}\n")
            else:
                self.stdout.write(f"{data}\n")

    def info(self, msg: str) -> None:
        if not self.quiet:
            print(msg, file=self.stderr)

    def success(self, msg: str) -> None:
        if not self.quiet:
            print(f"✓ {msg}", file=self.stderr)

    def table(self, columns: list[str], rows: list[list[str]]) -> None:
        if self.format != Format.TEXT:
            payload = {"columns": columns, "rows": rows}
            self.object(payload)
            return
        widths = [len(c) for c in columns]
        for row in rows:
            for i, cell in enumerate(row):
                widths[i] = max(widths[i], len(cell))
        header = "  ".join(c.ljust(widths[i]) for i, c in enumerate(columns))
        print(header, file=self.stdout)
        print("  ".join("─" * w for w in widths), file=self.stdout)
        for row in rows:
            print("  ".join(row[i].ljust(widths[i]) for i in range(len(columns))), file=self.stdout)


def _to_snake_obj(data: Any) -> Any:
    if hasattr(data, "__dataclass_fields__"):
        from dataclasses import asdict

        return {k: _to_snake_obj(v) for k, v in asdict(data).items()}
    if isinstance(data, list):
        return [_to_snake_obj(x) for x in data]
    if isinstance(data, dict):
        return {k: _to_snake_obj(v) for k, v in data.items()}
    return data
