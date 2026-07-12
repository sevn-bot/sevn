"""Tests for :mod:`sevn.voice.keywords` (`specs/20-voice.md` §11)."""

from __future__ import annotations

from sevn.voice.keywords import user_text_matches_voice_trigger


def test_word_boundary_rejects_substring_inside_token() -> None:
    assert not user_text_matches_voice_trigger(user_text="speakers", keywords=("speak",))


def test_cjk_surrounding_latin_keyword() -> None:
    assert user_text_matches_voice_trigger(user_text="请 speak 一下", keywords=("speak",))
