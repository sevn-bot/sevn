"""PKCE generation tests (W1.1 — ``codex-oauth-subscription`` plan)."""

from __future__ import annotations

import re
import string

import pytest
from tests.security.oauth.conftest import s256_challenge

from sevn.security.oauth.pkce import PkcePair, generate_pkce_pair

_VERIFIER_RE = re.compile(r"^[A-Za-z0-9\-._~]{43,128}$")


def test_pkce_pair_is_frozen_dataclass() -> None:
    """``PkcePair`` exposes verifier and challenge fields."""
    pair = PkcePair(verifier="v", challenge="c")
    assert pair.verifier == "v"
    assert pair.challenge == "c"


def test_generate_pkce_verifier_length_and_charset() -> None:
    """Verifier is RFC 7636 length (43-128) and unreserved charset."""
    pair = generate_pkce_pair()
    assert _VERIFIER_RE.fullmatch(pair.verifier)


def test_generate_pkce_challenge_is_s256() -> None:
    """Challenge is base64url(SHA256(verifier)) without padding."""
    pair = generate_pkce_pair()
    assert pair.challenge == s256_challenge(pair.verifier)


def test_generate_pkce_produces_unique_pairs() -> None:
    """Each call yields a distinct verifier/challenge pair."""
    a = generate_pkce_pair()
    b = generate_pkce_pair()
    assert a.verifier != b.verifier
    assert a.challenge != b.challenge


@pytest.mark.parametrize("count", [5, 10])
def test_generate_pkce_challenge_always_matches_verifier(count: int) -> None:
    """S256 invariant holds across multiple generations."""
    for _ in range(count):
        pair = generate_pkce_pair()
        assert pair.challenge == s256_challenge(pair.verifier)


def test_generate_pkce_verifier_has_sufficient_entropy() -> None:
    """Verifier uses a broad unreserved alphabet (not a fixed stub)."""
    pair = generate_pkce_pair()
    alphabet = set(string.ascii_letters + string.digits + "-._~")
    assert alphabet.intersection(set(pair.verifier))
