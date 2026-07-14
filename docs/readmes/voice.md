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

Voice sits in the sevn.bot turn spine: a channel delivers a message, the gateway normalises it, triage routes work to the right executor, and the reply returns through the same channel adapter. This subsystem owns the responsibilities described in the manifest summary. Provider API calls are brokered by the egress proxy.

### Configuration

Operator settings come from `sevn.json` in the workspace. Related normative specs: `about-sevn.bot/specs/20-voice.md`. Run `sevn config validate` after edits; use `sevn doctor` to confirm the install sees the expected layout.

### Key modules

- `src/sevn/voice/backends.py` — `validate_voice_backend_tags`, `SpeechToTextBackend.transcribe`, `SpeechToTextBackend.is_available`, `TextToSpeechBackend.synthesize`
- `src/sevn/voice/egress.py` — `voice_http_base_url`
- `src/sevn/voice/factory.py` — `voice_enabled`, `resolve_effective_tts_mode`, `voice_runtime_settings`, `build_stt_pipeline`
- `src/sevn/voice/host_deps.py` — `voice_host_dep_ids`, `maybe_resolve_whisper_model_env`, `provision_voice_deps`
- `src/sevn/voice/keywords.py` — `user_text_matches_voice_trigger`, `compile_voice_trigger_patterns`

## Level 3 — Deep dive (low-level, technical)

Primary source tree: [`src/sevn/voice`](../../src/sevn/voice/) (10 Python files). Normative design: `about-sevn.bot/specs/20-voice.md`.

### Module inventory

Voice provider chains (scaffold).

Working with [`__init__.py`](../../src/sevn/voice/__init__.py): inspect the public entry points below.

STT/TTS backend registry (about-sevn.bot/specs/20-voice.md §2.4).

Working with [`backends.py`](../../src/sevn/voice/backends.py): inspect the public entry points below.
Start with [`validate_voice_backend_tags`](../../src/sevn/voice/backends.py#L58), then [`SpeechToTextBackend.transcribe`](../../src/sevn/voice/backends.py#L108), [`SpeechToTextBackend.is_available`](../../src/sevn/voice/backends.py#L143), [`TextToSpeechBackend.synthesize`](../../src/sevn/voice/backends.py#L179).

Egress base URL for voice HTTP clients (about-sevn.bot/specs/20-voice.md §4.2, §10.3).

Working with [`egress.py`](../../src/sevn/voice/egress.py): inspect the public entry points below.
Start with [`voice_http_base_url`](../../src/sevn/voice/egress.py#L11).

Construct voice pipelines from workspace config (about-sevn.bot/specs/20-voice.md §5).

Working with [`factory.py`](../../src/sevn/voice/factory.py): inspect the public entry points below.
Start with [`voice_enabled`](../../src/sevn/voice/factory.py#L63), then [`resolve_effective_tts_mode`](../../src/sevn/voice/factory.py#L85), [`voice_runtime_settings`](../../src/sevn/voice/factory.py#L113), [`build_stt_pipeline`](../../src/sevn/voice/factory.py#L189).

Voice-specific host-dependency provisioning: whisper.cpp binary + ffmpeg.

Working with [`host_deps.py`](../../src/sevn/voice/host_deps.py): inspect the public entry points below.
Start with [`voice_host_dep_ids`](../../src/sevn/voice/host_deps.py#L100), then [`maybe_resolve_whisper_model_env`](../../src/sevn/voice/host_deps.py#L113), [`provision_voice_deps`](../../src/sevn/voice/host_deps.py#L162).

Voice trigger keyword matching (about-sevn.bot/specs/20-voice.md §4.1, §11).

Working with [`keywords.py`](../../src/sevn/voice/keywords.py): inspect the public entry points below.
Start with [`user_text_matches_voice_trigger`](../../src/sevn/voice/keywords.py#L37), then [`compile_voice_trigger_patterns`](../../src/sevn/voice/keywords.py#L81).

Speech-to-text pipeline (about-sevn.bot/specs/20-voice.md §2, §4, §6).

Working with [`stt.py`](../../src/sevn/voice/stt.py): inspect the public entry points below.
Start with [`SpeechToTextBackend.transcribe`](../../src/sevn/voice/stt.py#L37), then [`SpeechToTextBackend.is_available`](../../src/sevn/voice/stt.py#L69), [`SpeechToTextPipeline.transcribe_or_placeholder`](../../src/sevn/voice/stt.py#L118), [`transcribe_placeholder`](../../src/sevn/voice/stt.py#L261).

Trace helpers for voice spans (about-sevn.bot/specs/20-voice.md §7).

Working with [`trace_events.py`](../../src/sevn/voice/trace_events.py): inspect the public entry points below.
Start with [`emit_voice_event`](../../src/sevn/voice/trace_events.py#L20).

Text-to-speech pipeline (about-sevn.bot/specs/20-voice.md §2, §4, §6).

Working with [`tts.py`](../../src/sevn/voice/tts.py): inspect the public entry points below.
Start with [`TextToSpeechBackend.synthesize`](../../src/sevn/voice/tts.py#L101), then [`TextToSpeechBackend.is_available`](../../src/sevn/voice/tts.py#L128), [`TextToSpeechPipeline.should_synthesize`](../../src/sevn/voice/tts.py#L187), [`TextToSpeechPipeline.synthesize_or_skip`](../../src/sevn/voice/tts.py#L226).

Local GGML whisper.cpp model provisioning (mirrors pyclaww's voice-transcription skill).

Working with [`whisper_model_provisioner.py`](../../src/sevn/voice/whisper_model_provisioner.py): inspect the public entry points below.
Start with [`default_whisper_model_cache_dir`](../../src/sevn/voice/whisper_model_provisioner.py#L87), then [`model_path_for`](../../src/sevn/voice/whisper_model_provisioner.py#L103), [`is_whisper_model_cached`](../../src/sevn/voice/whisper_model_provisioner.py#L128), [`ensure_whisper_model`](../../src/sevn/voice/whisper_model_provisioner.py#L179).

### Extension and invariants

Follow [`20-voice.md`](../../about-sevn.bot/specs/20-voice.md) for merge gates, error semantics, and compatibility constraints. After code changes under [`src/sevn/voice`](../../src/sevn/voice/), run `sevn readme update voice` and `make readme-check`.

## References

- [../../about-sevn.bot/specs/20-voice.md](../../about-sevn.bot/specs/20-voice.md)

[spec-badge]: https://img.shields.io/badge/Spec-2a7fc6?style=for-the-badge&logo=readthedocs&logoColor=white
[spec-link]: ../../about-sevn.bot/specs/20-voice.md
[source-badge]: https://img.shields.io/badge/Source-0c0a09?style=for-the-badge&logo=github&logoColor=white
[source-link]: ../../src/sevn/voice/
[index-badge]: https://img.shields.io/badge/All_READMEs-5fb1f7?style=for-the-badge&logo=markdown&logoColor=white
[index-link]: INDEX.md
