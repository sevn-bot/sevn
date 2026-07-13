<!-- generated: do not edit by hand; run `sevn readme update voice` -->
# Voice — Gateway-level STT/TTS chains, trigger keywords, and voice trace events

[![Spec][spec-badge]][spec-link]
[![Source][source-badge]][source-link]
[![Index][index-badge]][index-link]

> **Summary.** Gateway-level STT/TTS chains, trigger keywords, and voice trace events.

## Level 1 — Overview (non-technical)

**Voice** is a core part of sevn.bot — the personal AI assistant you run on your own machine. Gateway-level STT/TTS chains, trigger keywords, and voice trace events.

In everyday use, voice helps Sevn do its job reliably: you interact through familiar channels (Telegram, browser, voice), and this layer keeps those interactions safe, consistent, and under your control.

## Level 2 — How it works (technical)

### Components and layout

Implementation lives under `src/sevn/voice/`. The package contains 10 Python module(s); primary entry points include `src/sevn/voice/__init__.py`, `src/sevn/voice/backends.py`, `src/sevn/voice/egress.py`, `src/sevn/voice/factory.py`, `src/sevn/voice/host_deps.py`, `src/sevn/voice/keywords.py`, and 4 more.

### Data and control flow

Voice sits in the sevn.bot turn spine: a channel delivers a message, the gateway normalises it, triage routes work to the right executor, and the reply returns through the same channel adapter. This subsystem owns the responsibilities described in the manifest summary and defers provider API calls to the paired egress proxy (keys never load in the gateway process).

### Configuration

Operator settings come from `sevn.json` in the workspace. Related normative specs: `about-sevn.bot/specs/20-voice.md`. Run `sevn config validate` after edits; use `sevn doctor` to confirm the install sees the expected layout.

### Key modules

- `src/sevn/voice/backends.py` — `validate_voice_backend_tags`, `SpeechToTextBackend.transcribe`, `SpeechToTextBackend.is_available`, `TextToSpeechBackend.synthesize`
- `src/sevn/voice/egress.py` — `voice_http_base_url`
- `src/sevn/voice/factory.py` — `voice_enabled`, `resolve_effective_tts_mode`, `voice_runtime_settings`, `build_stt_pipeline`
- `src/sevn/voice/host_deps.py` — `voice_host_dep_ids`, `maybe_resolve_whisper_model_env`, `provision_voice_deps`
- `src/sevn/voice/keywords.py` — `user_text_matches_voice_trigger`, `compile_voice_trigger_patterns`

## Level 3 — Deep dive (low-level, technical)

Primary source tree: `src/sevn/voice/` (10 Python files). Normative design: `about-sevn.bot/specs/20-voice.md`.

### Module inventory

- `src/sevn/voice/__init__.py` — Voice provider chains (scaffold).
- `src/sevn/voice/backends.py` — STT/TTS backend registry ('about-sevn.bot/specs/20-voice.md' §2.4).
- `src/sevn/voice/egress.py` — Egress base URL for voice HTTP clients ('about-sevn.bot/specs/20-voice.md' §4.2, §10.3).
- `src/sevn/voice/factory.py` — Construct voice pipelines from workspace config ('about-sevn.bot/specs/20-voice.md' §5).
- `src/sevn/voice/host_deps.py` — Voice-specific host-dependency provisioning: whisper.cpp binary + ffmpeg.
- `src/sevn/voice/keywords.py` — Voice trigger keyword matching ('about-sevn.bot/specs/20-voice.md' §4.1, §11).
- `src/sevn/voice/stt.py` — Speech-to-text pipeline ('about-sevn.bot/specs/20-voice.md' §2, §4, §6).
- `src/sevn/voice/trace_events.py` — Trace helpers for voice spans ('about-sevn.bot/specs/20-voice.md' §7).
- `src/sevn/voice/tts.py` — Text-to-speech pipeline ('about-sevn.bot/specs/20-voice.md' §2, §4, §6).
- `src/sevn/voice/whisper_model_provisioner.py` — Local GGML whisper.cpp model provisioning (mirrors pyclaww's voice-transcription skill).

### Package init (`src/sevn/voice/__init__.py`)

See `src/sevn/voice/__init__.py` for implementation details.

### Backends (`src/sevn/voice/backends.py`)

Public entry points:
- `validate_voice_backend_tags`
- `SpeechToTextBackend.transcribe`
- `SpeechToTextBackend.is_available`
- `TextToSpeechBackend.synthesize`
- `TextToSpeechBackend.is_available`
- `whisper_cpp_missing_prereqs`
- `WhisperCppBackend.is_available`
- `WhisperCppBackend.transcribe`

### Egress (`src/sevn/voice/egress.py`)

Public entry points:
- `voice_http_base_url`

### Factory (`src/sevn/voice/factory.py`)

Public entry points:
- `voice_enabled`
- `resolve_effective_tts_mode`
- `voice_runtime_settings`
- `build_stt_pipeline`
- `build_tts_pipeline`
- `prune_stale_tts_files`
- `maybe_preload_local_tts`
- `probe_voice_backends`

### Host Deps (`src/sevn/voice/host_deps.py`)

Public entry points:
- `voice_host_dep_ids`
- `maybe_resolve_whisper_model_env`
- `provision_voice_deps`

### Keywords (`src/sevn/voice/keywords.py`)

Public entry points:
- `user_text_matches_voice_trigger`
- `compile_voice_trigger_patterns`

### Stt (`src/sevn/voice/stt.py`)

Public entry points:
- `SpeechToTextBackend.transcribe`
- `SpeechToTextBackend.is_available`
- `SpeechToTextPipeline.transcribe_or_placeholder`
- `transcribe_placeholder`

### Trace Events (`src/sevn/voice/trace_events.py`)

Public entry points:
- `emit_voice_event`

### Tts (`src/sevn/voice/tts.py`)

Public entry points:
- `TextToSpeechBackend.synthesize`
- `TextToSpeechBackend.is_available`
- `TextToSpeechPipeline.should_synthesize`
- `TextToSpeechPipeline.synthesize_or_skip`
- `speak_placeholder`

### Whisper Model Provisioner (`src/sevn/voice/whisper_model_provisioner.py`)

Public entry points:
- `default_whisper_model_cache_dir`
- `model_path_for`
- `is_whisper_model_cached`
- `ensure_whisper_model`

### Extension and invariants

Follow `about-sevn.bot/specs/20-voice.md` for merge gates, error semantics, and compatibility constraints. After code changes under `src/sevn/voice/`, run `sevn readme update voice` and `make readme-check`.

## References

- [../../about-sevn.bot/specs/20-voice.md](../../about-sevn.bot/specs/20-voice.md)

[spec-badge]: https://img.shields.io/badge/Spec-2a7fc6?style=for-the-badge&logo=readthedocs&logoColor=white
[spec-link]: ../../about-sevn.bot/specs/20-voice.md
[source-badge]: https://img.shields.io/badge/Source-0c0a09?style=for-the-badge&logo=github&logoColor=white
[source-link]: ../../src/sevn/voice/
[index-badge]: https://img.shields.io/badge/All_READMEs-5fb1f7?style=for-the-badge&logo=markdown&logoColor=white
[index-link]: INDEX.md
