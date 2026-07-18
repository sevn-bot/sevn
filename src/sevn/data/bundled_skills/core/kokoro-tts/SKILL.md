---
name: kokoro-tts
description: Local Kokoro ONNX text-to-speech engine backing the voice TTS pipeline (kokoro backend). Not a model-facing research skill.
version: "1.0.0"
max_wall_seconds: 900
see_also:
  - tts
scripts:
  - path: scripts/generate.py
    description: Synthesize speech from text with Kokoro ONNX; auto-downloads model/voices on first use.
    args_overview: "TEXT [--voice af_heart] [--speed 1.0] [--output PATH] | --list-voices"
---

# kokoro-tts skill

Local, offline text-to-speech via **Kokoro ONNX** (`kokoro-onnx`). This skill is the engine
behind the voice **`tts`** tool's `kokoro` backend (`sevn.voice.backends.KokoroBackend`); the
gateway invokes `scripts/generate.py` directly as a subprocess — it is **not** offered to the
model as a research/authoring skill (runtime-quarantined).

## Usage

```
python scripts/generate.py "Hello world" --voice af_heart --output out.ogg
python scripts/generate.py --list-voices
```

- Models and voices auto-download from HuggingFace / GitHub releases on first run
  (~230 MB total) into this skill's `models/` and `voices.bin` under the workspace copy.
- Set `HF_TOKEN` for gated/private model repos.
- Override the voice with `SEVN_KOKORO_VOICE` (default `af_heart`).

## Available voices

`af_heart` (American F, warm, default), `af_bella`, `af_nicole`, `af_sarah`, `af_sky`,
`am_adam`, `am_michael`, `bf_emma`, `bf_isabella`, `bm_george`, `bm_lewis`, `jf_ai`,
`zf_xiaojiao`.

## Requirements

`requirements.txt` (`kokoro-onnx`, `soundfile`, `numpy`, `huggingface-hub`) is installed
on-demand by the backend via `uv run --with-requirements`; no global install needed.
