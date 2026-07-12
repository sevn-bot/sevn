"""Voice provider chains (scaffold).

Module: sevn.voice
Depends: sevn.voice.stt, sevn.voice.tts

Exports:
    transcribe_placeholder — STT stub (`specs/20-voice.md`).
    speak_placeholder — TTS stub (`specs/20-voice.md`).
"""

from __future__ import annotations

from sevn.voice.stt import transcribe_placeholder
from sevn.voice.tts import speak_placeholder

__all__ = ["speak_placeholder", "transcribe_placeholder"]
