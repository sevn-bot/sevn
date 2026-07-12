"""Unit tests for :mod:`sevn.voice.tts` (`specs/20-voice.md` §9)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from sevn.agent.tracing.sink import NullTraceSink
from sevn.voice.tts import TextToSpeechPipeline


def _pipe(keywords: tuple[str, ...]) -> TextToSpeechPipeline:
    return TextToSpeechPipeline(
        (),
        voice_trigger_keywords=keywords,
        trace=NullTraceSink(),
        tts_output_dir=Path("."),
    )


def test_should_synthesize_off() -> None:
    p = _pipe(("speak",))
    assert not p.should_synthesize(session_tts_mode="off", user_text_last_turn="speak")


def test_should_synthesize_all() -> None:
    p = _pipe(())
    assert p.should_synthesize(session_tts_mode="all", user_text_last_turn="")


def test_when_asked_word_boundary_casefold() -> None:
    p = _pipe(("speak",))
    assert p.should_synthesize(session_tts_mode="when_asked", user_text_last_turn="SPEAK now")
    assert not p.should_synthesize(session_tts_mode="when_asked", user_text_last_turn="nothing")
    assert not p.should_synthesize(
        session_tts_mode="when_asked",
        user_text_last_turn="speakers only",
    )


def test_when_asked_multi_word_phrase() -> None:
    p = _pipe(("read aloud",))
    assert p.should_synthesize(
        session_tts_mode="when_asked",
        user_text_last_turn="please read aloud thanks",
    )
    assert not p.should_synthesize(
        session_tts_mode="when_asked",
        user_text_last_turn="reread aloudly",
    )


def test_when_asked_voice_note_without_keyword() -> None:
    p = _pipe(())
    assert p.should_synthesize(
        session_tts_mode="when_asked",
        user_text_last_turn="plain text",
        inbound_voice_attachment=True,
    )


@pytest.mark.asyncio
async def test_synthesize_or_skip_empty_text(tmp_path: Path) -> None:
    p = TextToSpeechPipeline(
        (),
        voice_trigger_keywords=(),
        trace=NullTraceSink(),
        tts_output_dir=tmp_path / "tts",
    )
    assert (
        await p.synthesize_or_skip(
            cleaned_assistant_text="   ",
            voice_id=None,
            session_id="s",
            turn_id="t",
        )
    ).result is None


def test_speak_placeholder_returns_none() -> None:
    from sevn.voice.tts import speak_placeholder

    assert asyncio.run(speak_placeholder(text="hi", session_channel="telegram")) is None
