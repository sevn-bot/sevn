"""Drive file block encryption (OpenPGP SEIPD v1) and session keys."""

from __future__ import annotations

import hashlib
import os
import struct
from dataclasses import dataclass

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from pgpy import PGPKey, PGPMessage
from pgpy.packet.fields import ECDHCipherText

from proton_cli.account.keys import use_unlocked_key

_AES256 = 9
_TAG_SEIPD = 0xD2  # old format tag 18
_TAG_LITERAL = 11
_MDC_HEADER = b"\xd3\x14"
_MDC_SIZE = 22


@dataclass
class SessionKey:
    algorithm: int
    key: bytes

    @property
    def block_size(self) -> int:
        return 16


def make_session_key() -> SessionKey:
    key = os.urandom(32)
    return SessionKey(algorithm=_AES256, key=key)


def session_key_payload(sk: SessionKey) -> bytes:
    checksum = sum(sk.key) % 65536
    return bytes([sk.algorithm]) + sk.key + checksum.to_bytes(2, "big")


def encrypt_session_key_packet(node_key: PGPKey, sk: SessionKey) -> bytes:
    payload = session_key_payload(sk)
    pub = node_key.pubkey
    with use_unlocked_key(node_key):
        enc = pub.encrypt(PGPMessage.new(payload))
    raw = bytes(enc)
    return _first_packet_bytes(raw)


def decrypt_session_key_packet(packet: bytes, node_key: PGPKey) -> SessionKey:
    pkesk = _parse_pkesk_body(_packet_body(packet))
    if pkesk["version"] != 3:
        raise ValueError(f"unsupported PKESK version {pkesk['version']}")
    ct = ECDHCipherText()
    ct.parse(bytearray(pkesk["encrypted_session_key"]))
    with use_unlocked_key(node_key):
        enc_key = _encryption_subkey(node_key)
        payload = bytes(ct.decrypt(enc_key._key))
    if len(payload) < 3:
        raise ValueError("session key payload too short")
    algo = payload[0]
    key = payload[1:-2]
    checksum = int.from_bytes(payload[-2:], "big")
    if sum(key) % 65536 != checksum:
        raise ValueError("session key checksum mismatch")
    return SessionKey(algorithm=algo, key=key)


def sign_session_key(node_key: PGPKey, sk: SessionKey) -> str:
    with use_unlocked_key(node_key):
        sig = node_key.sign(PGPMessage.new(sk.key))
    return str(sig)


def encrypt_block(
    data: bytes,
    sk: SessionKey,
    node_key: PGPKey | None,
    addr_key: PGPKey | None,
) -> tuple[bytes, str]:
    seipd = _build_seipd_packet(data, sk)
    enc_sig = ""
    if addr_key is not None:
        with use_unlocked_key(addr_key):
            sig = addr_key.sign(PGPMessage.new(data))
        sig_msg = PGPMessage.new(bytes(sig))
        with use_unlocked_key(node_key):
            wrapped = node_key.pubkey.encrypt(sig_msg)
        enc_sig = str(wrapped)
    return seipd, enc_sig


def decrypt_block(encrypted: bytes, sk: SessionKey) -> bytes:
    body = _packet_body(encrypted)
    if not body or body[0] != 1:
        raise ValueError("unsupported SEIPD version")
    plaintext = _decrypt_openpgp_cfb(body[1:], sk.key, sk.block_size)
    _verify_mdc(plaintext)
    prefix_size = sk.block_size + 2
    literal = plaintext[prefix_size:-_MDC_SIZE]
    return _parse_literal_data(literal)


def _build_seipd_packet(data: bytes, sk: SessionKey) -> bytes:
    block_size = sk.block_size
    prefix = os.urandom(block_size + 2)
    literal = _build_literal_packet(data)
    payload = prefix + literal
    # codeql[py/weak-sensitive-data-hashing] OpenPGP SEIPD MDC requires SHA-1
    mdc = _MDC_HEADER + hashlib.sha1(payload).digest()
    cfb_plain = payload + mdc
    ciphertext = _encrypt_openpgp_cfb(cfb_plain, sk.key, block_size)
    body = bytes([1]) + ciphertext
    return _wrap_packet(_TAG_SEIPD, body)


def _build_literal_packet(data: bytes) -> bytes:
    filename = b""
    header = bytes([0x62]) + bytes([len(filename)]) + filename + struct.pack(">I", 0)
    body = header + data
    return _wrap_packet(_TAG_LITERAL, body, new_format=False)


def _encrypt_openpgp_cfb(plaintext: bytes, key: bytes, block_size: int) -> bytes:
    # codeql[py/weak-cryptographic-algorithm] OpenPGP CFB uses AES-ECB for keystream
    ecb = Cipher(algorithms.AES(key), modes.ECB()).encryptor()
    feedback = bytes(block_size)
    out = bytearray()
    for i in range(0, len(plaintext), block_size):
        block = plaintext[i : i + block_size]
        # codeql[py/weak-cryptographic-algorithm]
        keystream = ecb.update(feedback)
        cipher_block = bytes(a ^ b for a, b in zip(block, keystream, strict=False))
        out.extend(cipher_block)
        feedback = (
            cipher_block
            if len(cipher_block) == block_size
            else cipher_block + bytes(block_size - len(cipher_block))
        )
    ecb.finalize()
    return bytes(out)


def _decrypt_openpgp_cfb(ciphertext: bytes, key: bytes, block_size: int) -> bytes:
    # codeql[py/weak-cryptographic-algorithm] OpenPGP CFB uses AES-ECB for keystream
    ecb = Cipher(algorithms.AES(key), modes.ECB()).encryptor()
    feedback = bytes(block_size)
    out = bytearray()
    for i in range(0, len(ciphertext), block_size):
        block = ciphertext[i : i + block_size]
        # codeql[py/weak-cryptographic-algorithm]
        keystream = ecb.update(feedback)
        out.extend(a ^ b for a, b in zip(block, keystream, strict=False))
        feedback = block if len(block) == block_size else block + bytes(block_size - len(block))
    ecb.finalize()
    return bytes(out)


def _verify_mdc(plaintext: bytes) -> None:
    if len(plaintext) < _MDC_SIZE:
        raise ValueError("data too short for MDC")
    mdc = plaintext[-_MDC_SIZE:]
    if mdc[:2] != _MDC_HEADER:
        raise ValueError("invalid MDC header")
    # codeql[py/weak-sensitive-data-hashing] OpenPGP SEIPD MDC requires SHA-1
    expected = hashlib.sha1(plaintext[:-_MDC_SIZE]).digest()
    if mdc[2:] != expected:
        raise ValueError("MDC verification failed")


def _parse_literal_data(data: bytes) -> bytes:
    if len(data) < 2:
        return data
    first = data[0]
    if (first & 0x80) == 0x80:
        tag = (first & 0x3C) >> 2
        offset = 1 + _old_length_size(first, data)
    elif (first & 0xC0) == 0xC0:
        tag = first & 0x3F
        offset = 1 + _new_length_size(data[1:])
    else:
        return data
    if tag != _TAG_LITERAL or offset >= len(data):
        return data
    offset += 1
    if offset >= len(data):
        return b""
    name_len = data[offset]
    offset += 1 + name_len + 4
    return data[offset:] if offset < len(data) else b""


def _wrap_packet(tag: int, body: bytes, *, new_format: bool = True) -> bytes:
    if new_format:
        header = bytes([0xC0 | tag])
        return header + _encode_new_length(len(body)) + body
    first = 0x80 | (tag << 2)
    length_bytes = _encode_old_length(len(body))
    return bytes([first | length_bytes[0]]) + length_bytes[1:] + body


def _encode_new_length(n: int) -> bytes:
    if n < 192:
        return bytes([n])
    if n < 8384:
        n -= 192
        return bytes([((n >> 8) & 0xFF) + 192, n & 0xFF])
    return bytes([255]) + n.to_bytes(4, "big")


def _encode_old_length(n: int) -> bytes:
    if n < 256:
        return bytes([0, n])
    if n < 65536:
        return bytes([1]) + n.to_bytes(2, "big")
    return bytes([2]) + n.to_bytes(4, "big")


def _old_length_size(first: int, data: bytes) -> int:
    length_type = first & 0x03
    if length_type == 0:
        return 1
    if length_type == 1:
        return 2
    if length_type == 2:
        return 4
    return 0


def _new_length_size(data: bytes) -> int:
    if not data:
        return 0
    b0 = data[0]
    if b0 < 192:
        return 1
    if b0 < 224:
        return 2
    if b0 == 255:
        return 5
    return 1


def _packet_body(packet: bytes) -> bytes:
    if not packet:
        return b""
    first = packet[0]
    if (first & 0xC0) == 0xC0:
        offset = 1 + _new_length_size(packet[1:])
    elif (first & 0x80) == 0x80:
        offset = 1 + _old_length_size(first, packet)
    else:
        return packet
    length, _ = _parse_packet_length(packet, 0)
    start = offset
    return packet[start : start + length]


def _parse_packet_length(packet: bytes, pos: int) -> tuple[int, int]:
    first = packet[pos]
    if (first & 0xC0) == 0xC0:
        return _parse_new_length(packet[pos + 1 :])
    if (first & 0x80) == 0x80:
        return _parse_old_length(packet[pos + 1 :], first & 0x03)
    raise ValueError("invalid packet header")


def _parse_new_length(data: bytes) -> tuple[int, int]:
    if not data:
        raise ValueError("missing length")
    b0 = data[0]
    if b0 < 192:
        return b0, 1
    if b0 < 224:
        return ((b0 - 192) << 8) + data[1] + 192, 2
    if b0 == 255:
        return int.from_bytes(data[1:5], "big"), 5
    raise ValueError("partial body length not supported")


def _parse_old_length(data: bytes, length_type: int) -> tuple[int, int]:
    if length_type == 0:
        return data[0], 1
    if length_type == 1:
        return int.from_bytes(data[:2], "big"), 2
    if length_type == 2:
        return int.from_bytes(data[:4], "big"), 4
    raise ValueError("indeterminate length not supported")


def _first_packet_bytes(message: bytes) -> bytes:
    length, hdr = _parse_packet_length(message, 0)
    start = 1 + hdr
    return message[: start + length]


def _parse_pkesk_body(body: bytes) -> dict[str, object]:
    version = body[0]
    if version != 3:
        return {"version": version, "encrypted_session_key": b""}
    return {
        "version": 3,
        "encrypted_session_key": body[10:],
    }


def _encryption_subkey(key: PGPKey) -> PGPKey:
    for sub in key.subkeys.values():
        if not sub.is_public:
            return sub
    return key
