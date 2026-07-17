"""Protobuf wire encode/decode for Proton Pass items (login-focused)."""

from __future__ import annotations


def _write_varint(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            break
    return bytes(out)


def _write_string(field: int, value: str) -> bytes:
    if not value:
        return b""
    data = value.encode("utf-8")
    tag = (field << 3) | 2
    return _write_varint(tag) + _write_varint(len(data)) + data


def _write_message(field: int, payload: bytes) -> bytes:
    if not payload:
        return b""
    tag = (field << 3) | 2
    return _write_varint(tag) + _write_varint(len(payload)) + payload


def encode_login_item(
    *,
    name: str,
    note: str = "",
    username: str = "",
    email: str = "",
    password: str = "",
    url: str = "",
    urls: list[str] | None = None,
    totp: str = "",
) -> bytes:
    """Encode a login ``Item`` protobuf."""
    url_values = list(urls or [])
    if url and not url_values:
        url_values = [url]
    login_parts = [
        _write_string(1, email),
        _write_string(2, password),
        _write_string(4, totp),
        _write_string(6, username),
    ]
    login_parts.extend(_write_string(3, value) for value in url_values if value)
    login = b"".join(login_parts)
    content = _write_message(3, login)
    metadata = b"".join([_write_string(1, name), _write_string(2, note)])
    return b"".join([_write_message(1, metadata), _write_message(2, content)])


def encode_vault(name: str, description: str = "") -> bytes:
    parts = [_write_string(1, name)]
    if description:
        parts.append(_write_string(2, description))
    return b"".join(parts)


def patch_login_item(
    data: bytes,
    *,
    name: str = "",
    note: str = "",
    username: str = "",
    email: str = "",
    password: str = "",
    url: str = "",
    totp: str = "",
) -> bytes:
    """Decode-login-patch-reencode for edit operations."""
    parsed = decode_item_content(data)
    if name:
        parsed["name"] = name
    if note:
        parsed["note"] = note
    if username:
        parsed["username"] = username
    if email:
        parsed["email"] = email
    if password:
        parsed["password"] = password
    if url:
        parsed["urls"] = [url]
    if totp:
        parsed["totp"] = totp
    return encode_login_item(
        name=str(parsed.get("name", "")),
        note=str(parsed.get("note", "")),
        username=str(parsed.get("username", "")),
        email=str(parsed.get("email", "")),
        password=str(parsed.get("password", "")),
        urls=[str(u) for u in (parsed.get("urls") or []) if str(u)],
        totp=str(parsed.get("totp", "")),
    )


def decode_item_content(data: bytes) -> dict[str, object]:
    result: dict[str, object] = {"type": "login", "urls": []}
    i = 0
    while i < len(data):
        tag, i = _read_varint(data, i)
        field = tag >> 3
        wire = tag & 0x7
        if wire == 2:
            length, i = _read_varint(data, i)
            chunk = data[i : i + length]
            i += length
            if field == 1:
                meta = _decode_metadata(chunk)
                result.update(meta)
            elif field == 2:
                login = _decode_content_chunk(chunk)
                result.update(login)
                if login:
                    result["type"] = "login"
        elif wire == 0:
            _, i = _read_varint(data, i)
        elif wire == 1:
            i += 8
        elif wire == 5:
            i += 4
        else:
            break
    return result


def _decode_metadata(data: bytes) -> dict[str, str]:
    out: dict[str, str] = {}
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
                out["name"] = value
            elif field == 2:
                out["note"] = value
        else:
            break
    return out


def _decode_content_chunk(data: bytes) -> dict[str, object]:
    """Decode ``Content`` message; login is field 3."""
    out: dict[str, object] = {}
    i = 0
    while i < len(data):
        tag, i = _read_varint(data, i)
        field = tag >> 3
        wire = tag & 0x7
        if wire == 2:
            length, i = _read_varint(data, i)
            chunk = data[i : i + length]
            i += length
            if field == 3:
                out.update(_decode_login_chunk(chunk))
        elif wire == 0:
            _, i = _read_varint(data, i)
        elif wire == 1:
            i += 8
        elif wire == 5:
            i += 4
        else:
            break
    return out


def _decode_login_chunk(data: bytes) -> dict[str, object]:
    out: dict[str, object] = {"urls": []}
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
                out["email"] = value
            elif field == 2:
                out["password"] = value
            elif field == 3:
                urls = list(out.get("urls") or [])
                urls.append(value)
                out["urls"] = urls
            elif field == 4:
                out["totp"] = value
            elif field == 6:
                out["username"] = value
        elif wire == 0:
            _, i = _read_varint(data, i)
        elif wire == 1:
            i += 8
        elif wire == 5:
            i += 4
        else:
            break
    return out


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
