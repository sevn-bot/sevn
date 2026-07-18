"""Supertonic ONNX engine for the text-to-voice skill.

Uses the ``supertonic`` PyPI package. First run auto-downloads model assets from Hugging Face.
"""

from __future__ import annotations

import json
import os
import sys

_ENGINE_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(os.path.dirname(_ENGINE_DIR))

DEFAULT_VOICE = "M1"
DEFAULT_LANG = "en"
_KNOWN_VOICES = frozenset({"M1", "M2", "M3", "M4", "M5", "F1", "F2", "F3", "F4", "F5"})


def generate(
    text: str,
    voice: str = DEFAULT_VOICE,
    speed: float = 1.05,
    output_path: str | None = None,
    lang: str | None = None,
) -> str:
    """Generate audio file from text via Supertonic."""
    from supertonic import TTS

    voice_name = (voice or DEFAULT_VOICE).strip() or DEFAULT_VOICE
    if voice_name not in _KNOWN_VOICES:
        print(
            f"WARNING: Voice '{voice_name}' not found for supertonic, falling back to {DEFAULT_VOICE}.",
            file=sys.stderr,
        )
        voice_name = DEFAULT_VOICE

    lang_code = (
        lang or os.environ.get("SEVN_SUPERTONIC_LANG") or DEFAULT_LANG
    ).strip() or DEFAULT_LANG
    speed = max(0.7, min(2.0, float(speed)))

    tts = TTS(auto_download=True)
    style = tts.get_voice_style(voice_name=voice_name)
    wav, _duration = tts.synthesize(
        text=text,
        lang=lang_code,
        voice_style=style,
        total_steps=8,
        speed=speed,
    )

    if output_path is None:
        output_path = os.path.join(SKILL_DIR, "output.wav")

    tts.save_audio(wav, output_path)
    print(output_path)
    return output_path


def list_voices() -> None:
    """Print available Supertonic voices as JSON (static catalog)."""
    voices = [
        {"code": "M1", "label": "Male, lively/upbeat"},
        {"code": "M2", "label": "Male, deep/calm"},
        {"code": "M3", "label": "Male, polished/authoritative"},
        {"code": "M4", "label": "Male, soft/neutral"},
        {"code": "M5", "label": "Male, warm/storytelling"},
        {"code": "F1", "label": "Female, calm/low"},
        {"code": "F2", "label": "Female, bright/cheerful"},
        {"code": "F3", "label": "Female, professional announcer"},
        {"code": "F4", "label": "Female, crisp/confident"},
        {"code": "F5", "label": "Female, kind/gentle"},
    ]
    print(json.dumps(voices))
