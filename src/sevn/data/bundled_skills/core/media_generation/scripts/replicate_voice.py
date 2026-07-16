#!/usr/bin/env python3
"""Bundled ``media_generation`` skill — voice replication via ``media_generator``.

Module: sevn.data.bundled_skills.core.media_generation.scripts.replicate_voice
Depends: argparse, sevn.data.bundled_skills.core.media_generation.scripts._common

Exports:
    main — CLI entry; JSON envelope on stdout.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from _common import run_media_generation  # noqa: E402


def main() -> int:
    """Run voice clone / TTS CLI.

    Returns:
        int: ``0`` on success; ``1`` on failure.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(main)
        True
    """
    parser = argparse.ArgumentParser(description="Clone or synthesize voice via media_generator")
    sub = parser.add_subparsers(dest="mode", required=True)

    clone = sub.add_parser("clone", help="Clone voice from source audio sample")
    clone.add_argument("prompt", help="Short voice character intent (augmented with templates)")
    clone.add_argument("source_audio", help="Source audio path (mp3/m4a/wav, 10s-5min)")
    clone.add_argument("--voice-id", default=None, dest="voice_id")
    clone.add_argument("--preview-text", default=None, dest="preview_text")
    clone.add_argument("--speech-text", default=None, dest="speech_text")
    clone.add_argument("--template", default=None)
    clone.add_argument("--prompt-audio", default=None, dest="prompt_audio")
    clone.add_argument("--prompt-text", default=None, dest="prompt_text")

    speak = sub.add_parser("speak", help="Synthesize speech with existing voice_id")
    speak.add_argument("prompt", help="Short delivery intent (augmented with templates)")
    speak.add_argument("voice_id", help="MiniMax voice id (cloned or system)")
    speak.add_argument("speech_text", help="Text to speak")
    speak.add_argument("--template", default=None)

    args = parser.parse_args()
    if args.mode == "clone":
        extra: dict[str, object] = {
            "source_audio": args.source_audio,
        }
        if args.voice_id:
            extra["voice_id"] = args.voice_id
        if args.preview_text:
            extra["preview_text"] = args.preview_text
        if args.speech_text:
            extra["speech_text"] = args.speech_text
        if args.template:
            extra["template"] = args.template
        if args.prompt_audio:
            extra["prompt_audio"] = args.prompt_audio
        if args.prompt_text:
            extra["prompt_text"] = args.prompt_text
        exit_code: int = run_media_generation("voice", args.prompt, extra=extra)
    else:
        extra = {
            "voice_id": args.voice_id,
            "speech_text": args.speech_text,
        }
        if args.template:
            extra["template"] = args.template
        exit_code = run_media_generation("voice", args.prompt, extra=extra)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
