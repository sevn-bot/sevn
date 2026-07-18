---
name: text-to-voice
description: Unified local text-to-speech engines (Kokoro ONNX + Supertonic) backing the voice TTS pipeline (text_to_voice backend). Not a model-facing research skill.
version: "1.0.0"
max_wall_seconds: 900
see_also:
  - tts
scripts:
  - path: scripts/generate.py
    description: Synthesize speech from text with kokoro or supertonic; auto-downloads model assets on first use.
    args_overview: "TEXT --engine kokoro|supertonic [--voice ID] [--lang CODE] [--speed N] [--output PATH] | --list-voices | --list-engines"
---

# text-to-voice skill

Local, offline text-to-speech via **Kokoro ONNX** or **Supertonic**. This skill is the engine
behind the voice **`tts`** tool's `text_to_voice` backend (`sevn.voice.backends.TextToVoiceBackend`);
the gateway invokes `scripts/generate.py` directly as a subprocess — it is **not** offered to the
model as a research/authoring skill (runtime-quarantined).

Configure the active engine in `sevn.json`:

```json
{
  "voice": {
    "tts_providers": ["text_to_voice", "edge_tts"],
    "local_tts_engine": "kokoro"
  }
}
```

Set `"local_tts_engine": "supertonic"` to switch engines without changing the provider chain.

## Usage

```
python scripts/generate.py "Hello world" --engine kokoro --voice af_heart --output out.wav
python scripts/generate.py "Hello world" --engine supertonic --voice M1 --lang en --output out.wav
python scripts/generate.py --list-voices --engine kokoro
python scripts/generate.py --list-engines
```

- Kokoro models/voices auto-download from HuggingFace / GitHub on first run (~230 MB).
- Supertonic model assets auto-download via the `supertonic` package on first run.
- Set `HF_TOKEN` for gated/private model repos.
- Env overrides: `SEVN_LOCAL_TTS_ENGINE`, `SEVN_KOKORO_VOICE` (default `af_heart`),
  `SEVN_SUPERTONIC_VOICE` (default `M1`), `SEVN_SUPERTONIC_LANG` (default `en`).

## Engines

| Engine | Default voice | Notes |
|--------|---------------|-------|
| `kokoro` | `af_heart` | Compact ONNX; English-focused presets + JA/ZH voices |
| `supertonic` | `M1` | 31-language multilingual; voices M1–M5, F1–F5 |

## Requirements

Engine-specific requirements are installed on-demand by the backend via
`uv run --with-requirements`:

- `requirements-kokoro.txt` — `kokoro-onnx`, `soundfile`, `numpy`, `huggingface-hub`
- `requirements-supertonic.txt` — `supertonic`
