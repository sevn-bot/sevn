"""Minimal protobuf decode for Proton Pass vault content."""

from __future__ import annotations


def decode_vault_name_description(data: bytes) -> tuple[str, str]:
    """Decode vault protobuf fields 1 (name) and 2 (description)."""
    name = ""
    description = ""
    i = 0
    while i < len(data):
        tag, i = _read_varint(data, i)
        field = tag >> 3
        wire = tag & 0x7
        if wire == 2:
            length, i = _read_varint(data, i)
            value = data[i : i + length].decode("utf-8", errors="replace")
            i += length
            if field == 1:
                name = value
            elif field == 2:
                description = value
        elif wire == 0:
            _, i = _read_varint(data, i)
        elif wire == 1:
            i += 8
        elif wire == 5:
            i += 4
        else:
            break
    return name, description


def _read_varint(data: bytes, i: int) -> tuple[int, int]:
    result = 0
    shift = 0
    while i < len(data):
        b = data[i]
        i += 1
        result |= (b & 0x7F) << shift
        if (b & 0x80) == 0:
            return result, i
        shift += 7
    return result, i
