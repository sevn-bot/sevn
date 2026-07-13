<!-- generated: do not edit by hand; run `sevn readme update voice` -->
# Voice — Gateway-level STT/TTS chains, trigger keywords, and voice trace events

[![Spec][spec-badge]][spec-link]
[![Source][source-badge]][source-link]
[![Index][index-badge]][index-link]

> **Summary.** Gateway-level STT/TTS chains, trigger keywords, and voice trace events.

## Level 1 — Overview (non-technical)

**Voice** is a core part of sevn.bot — the personal AI assistant you run on your own machine. Gateway-level STT/TTS chains, trigger keywords, and voice trace events.

In everyday use, voice helps Sevn do its job reliably: you interact through familiar channels (Telegram, browser, voice), and this layer keeps those interactions safe, consistent, and under your control.

Own the provider-chain facades for speech-to-text and text-to-speech so the gateway can:

## Level 2 — How it works (technical)

### Components and layout

Implementation lives under `src/sevn/voice/`. The package contains 10 Python module(s); primary entry points include `src/sevn/voice/__init__.py`, `src/sevn/voice/backends.py`, `src/sevn/voice/egress.py`, `src/sevn/voice/factory.py`, and 2 more.

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

### Spec context

From about-sevn.bot/specs/20-voice.md:
Own the provider-chain facades for speech-to-text and text-to-speech so the gateway can:

## Level 3 — Deep dive (low-level, technical)

Primary source tree: `src/sevn/voice/` (10 Python files). Normative design: `about-sevn.bot/specs/20-voice.md`.

### Module inventory

- `src/sevn/voice/__init__.py` — """Voice provider chains (scaffold).
- `src/sevn/voice/backends.py` — """STT/TTS backend registry ('about-sevn.bot/specs/20-voice.md' §2.4).
- `src/sevn/voice/egress.py` — """Egress base URL for voice HTTP clients ('about-sevn.bot/specs/20-voice.md' §4.2, §10.3).
- `src/sevn/voice/factory.py` — """Construct voice pipelines from workspace config ('about-sevn.bot/specs/20-voice.md' §5).
- `src/sevn/voice/host_deps.py` — """Voice-specific host-dependency provisioning: whisper.cpp binary + ffmpeg.
- `src/sevn/voice/keywords.py` — """Voice trigger keyword matching ('about-sevn.bot/specs/20-voice.md' §4.1, §11).
- `src/sevn/voice/stt.py` — """Speech-to-text pipeline ('about-sevn.bot/specs/20-voice.md' §2, §4, §6).
- `src/sevn/voice/trace_events.py` — """Trace helpers for voice spans ('about-sevn.bot/specs/20-voice.md' §7).
- `src/sevn/voice/tts.py` — """Text-to-speech pipeline ('about-sevn.bot/specs/20-voice.md' §2, §4, §6).
- `src/sevn/voice/whisper_model_provisioner.py` — """Local GGML whisper.cpp model provisioning (mirrors pyclaww's voice-transcription skill).

### Backends (`src/sevn/voice/backends.py`)

Public entry points:
- `validate_voice_backend_tags` — see `src/sevn/voice/backends.py`
- `SpeechToTextBackend.transcribe` — see `src/sevn/voice/backends.py`
- `SpeechToTextBackend.is_available` — see `src/sevn/voice/backends.py`
- `TextToSpeechBackend.synthesize` — see `src/sevn/voice/backends.py`
- `TextToSpeechBackend.is_available` — see `src/sevn/voice/backends.py`
- `whisper_cpp_missing_prereqs` — see `src/sevn/voice/backends.py`
- `WhisperCppBackend.is_available` — see `src/sevn/voice/backends.py`
- `WhisperCppBackend.transcribe` — see `src/sevn/voice/backends.py`

### Egress (`src/sevn/voice/egress.py`)

Public entry points:
- `voice_http_base_url` — see `src/sevn/voice/egress.py`

### Factory (`src/sevn/voice/factory.py`)

Public entry points:
- `voice_enabled` — see `src/sevn/voice/factory.py`
- `resolve_effective_tts_mode` — see `src/sevn/voice/factory.py`
- `voice_runtime_settings` — see `src/sevn/voice/factory.py`
- `build_stt_pipeline` — see `src/sevn/voice/factory.py`
- `build_tts_pipeline` — see `src/sevn/voice/factory.py`
- `prune_stale_tts_files` — see `src/sevn/voice/factory.py`
- `maybe_preload_local_tts` — see `src/sevn/voice/factory.py`
- `probe_voice_backends` — see `src/sevn/voice/factory.py`

### Host Deps (`src/sevn/voice/host_deps.py`)

Public entry points:
- `voice_host_dep_ids` — see `src/sevn/voice/host_deps.py`
- `maybe_resolve_whisper_model_env` — see `src/sevn/voice/host_deps.py`
- `provision_voice_deps` — see `src/sevn/voice/host_deps.py`

### Keywords (`src/sevn/voice/keywords.py`)

Public entry points:
- `user_text_matches_voice_trigger` — see `src/sevn/voice/keywords.py`
- `compile_voice_trigger_patterns` — see `src/sevn/voice/keywords.py`

### Stt (`src/sevn/voice/stt.py`)

Public entry points:
- `SpeechToTextBackend.transcribe` — see `src/sevn/voice/stt.py`
- `SpeechToTextBackend.is_available` — see `src/sevn/voice/stt.py`
- `SpeechToTextPipeline.transcribe_or_placeholder` — see `src/sevn/voice/stt.py`
- `transcribe_placeholder` — see `src/sevn/voice/stt.py`

### Trace Events (`src/sevn/voice/trace_events.py`)

Public entry points:
- `emit_voice_event` — see `src/sevn/voice/trace_events.py`

### Tts (`src/sevn/voice/tts.py`)

Public entry points:
- `TextToSpeechBackend.synthesize` — see `src/sevn/voice/tts.py`
- `TextToSpeechBackend.is_available` — see `src/sevn/voice/tts.py`
- `TextToSpeechPipeline.should_synthesize` — see `src/sevn/voice/tts.py`
- `TextToSpeechPipeline.synthesize_or_skip` — see `src/sevn/voice/tts.py`
- `speak_placeholder` — see `src/sevn/voice/tts.py`

### Whisper Model Provisioner (`src/sevn/voice/whisper_model_provisioner.py`)

Public entry points:
- `default_whisper_model_cache_dir` — see `src/sevn/voice/whisper_model_provisioner.py`
- `model_path_for` — see `src/sevn/voice/whisper_model_provisioner.py`
- `is_whisper_model_cached` — see `src/sevn/voice/whisper_model_provisioner.py`
- `ensure_whisper_model` — see `src/sevn/voice/whisper_model_provisioner.py`

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
