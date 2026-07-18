#!/usr/bin/env python3
"""Unified local TTS CLI — routes to kokoro or supertonic engines.

Usage:
  python generate.py "Hello world" --engine kokoro [--voice af_heart] [--output path.wav]
  python generate.py "Hello world" --engine supertonic [--voice M1] [--lang en] [--output path.wav]
  python generate.py --list-voices --engine kokoro
  python generate.py --list-engines
"""

from __future__ import annotations

import argparse
import json
import os
import sys

KNOWN_ENGINES = ("kokoro", "supertonic")


def _default_engine() -> str:
    raw = os.environ.get("SEVN_LOCAL_TTS_ENGINE", "").strip().casefold()
    if raw in KNOWN_ENGINES:
        return raw
    return "kokoro"


def _default_voice(engine: str) -> str:
    if engine == "supertonic":
        return os.environ.get("SEVN_SUPERTONIC_VOICE", "M1").strip() or "M1"
    return os.environ.get("SEVN_KOKORO_VOICE", "af_heart").strip() or "af_heart"


def main() -> None:
    parser = argparse.ArgumentParser(description="text-to-voice (kokoro | supertonic)")
    parser.add_argument("text", nargs="?", help="Text to synthesize")
    parser.add_argument(
        "--engine",
        "-e",
        default=None,
        choices=KNOWN_ENGINES,
        help="Local TTS engine (default: SEVN_LOCAL_TTS_ENGINE or kokoro)",
    )
    parser.add_argument("--voice", "-v", default=None, help="Engine-specific voice id")
    parser.add_argument("--lang", "-l", default=None, help="Language code (supertonic; e.g. en, na)")
    parser.add_argument("--speed", "-s", type=float, default=None, help="Speech speed")
    parser.add_argument("--output", "-o", default=None, help="Output WAV path")
    parser.add_argument("--list-voices", action="store_true", help="List voices for --engine")
    parser.add_argument("--list-engines", action="store_true", help="List available engines")

    args = parser.parse_args()
    if args.list_engines:
        print(json.dumps(list(KNOWN_ENGINES)))
        return

    engine = (args.engine or _default_engine()).strip().casefold()
    if engine not in KNOWN_ENGINES:
        print(f"ERROR: unknown engine {engine!r}; known: {KNOWN_ENGINES}", file=sys.stderr)
        sys.exit(2)

    if engine == "kokoro":
        from engines import kokoro as eng
    else:
        from engines import supertonic as eng

    if args.list_voices:
        eng.list_voices()
        return

    if not args.text:
        parser.print_help()
        sys.exit(1)

    voice = args.voice if args.voice is not None else _default_voice(engine)
    speed = args.speed
    if speed is None:
        speed = 1.05 if engine == "supertonic" else 1.0

    eng.generate(
        args.text,
        voice=voice,
        speed=speed,
        output_path=args.output,
        lang=args.lang,
    )


if __name__ == "__main__":
    main()
