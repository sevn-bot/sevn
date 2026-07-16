"""Generate Curve25519 node keys compatible with Proton Drive."""

from __future__ import annotations

import base64
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from pgpy import PGPKey
from pgpy.constants import EllipticCurveOID, HashAlgorithm, PubKeyAlgorithm, SymmetricKeyAlgorithm

_GO_SOURCE = """package main

import (
    "fmt"
    "io"
    "os"
    pgp "github.com/ProtonMail/gopenpgp/v2/crypto"
)

func main() {
    k, err := pgp.GenerateKey("Drive key", "", "x25519", 0)
    if err != nil {
        panic(err)
    }
    phrase := make([]byte, 32)
    if _, err := io.ReadFull(os.Stdin, phrase); err != nil {
        panic(err)
    }
    locked, err := k.Lock(phrase)
    if err != nil {
        panic(err)
    }
    arm, err := locked.Armor()
    if err != nil {
        panic(err)
    }
    fmt.Print(arm)
}
"""


def generate_node_key() -> tuple[PGPKey, str, bytes]:
    """Return ``(locked_key, armored_locked_key, lock_passphrase)``."""
    phrase_text = base64.b64encode(os.urandom(32)).decode()
    lock_pass = phrase_text.encode()
    armored = generate_armored_locked_key(lock_pass)
    key, _ = PGPKey.from_blob(armored)
    return key, armored, lock_pass


def generate_armored_locked_key(passphrase: bytes) -> str:
    try:
        return _generate_armored_locked_key_python(passphrase)
    except Exception:
        return _generate_armored_locked_key_go(passphrase)


def _generate_armored_locked_key_python(passphrase: bytes) -> str:
    key = PGPKey.new(PubKeyAlgorithm.ECDH, EllipticCurveOID.Curve25519)
    key.protect(passphrase, SymmetricKeyAlgorithm.AES256, HashAlgorithm.SHA256)
    armored = str(key)
    if "-----END PGP PRIVATE KEY BLOCK-----" not in armored:
        raise RuntimeError("pgpy keygen returned invalid armored key")
    return armored


def _generate_armored_locked_key_go(passphrase: bytes) -> str:
    go = shutil.which("go")
    if not go:
        msg = (
            "unable to generate Drive node keys (pgpy keygen failed and Go is not installed)"
        )
        raise RuntimeError(msg)
    with tempfile.TemporaryDirectory(prefix="proton-cli-keygen-") as tmp:
        mod_dir = Path(tmp)
        (mod_dir / "go.mod").write_text("module protonclikeygen\n\ngo 1.22\n", encoding="utf-8")
        (mod_dir / "main.go").write_text(_GO_SOURCE, encoding="utf-8")
        proc = subprocess.run(
            [go, "mod", "tidy"],
            cwd=mod_dir,
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"go mod tidy failed: {proc.stderr.strip()}")
        proc = subprocess.run(
            [go, "run", "."],
            cwd=mod_dir,
            input=passphrase,
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"go keygen failed: {proc.stderr.decode().strip()}")
        out = proc.stdout.decode()
        if "-----END PGP PRIVATE KEY BLOCK-----" not in out:
            raise RuntimeError("go keygen returned invalid armored key")
        return out.split("-----END PGP PRIVATE KEY BLOCK-----")[0] + "-----END PGP PRIVATE KEY BLOCK-----\n"
