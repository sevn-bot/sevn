---
id: spec-20-voice
kind: spec
title: Voice (STT / TTS) — Spec
status: scaffold
owner: Alex
summary: 'Own the provider-chain facades for speech-to-text and text-to-speech so
  the gateway can:'
last_updated: '2026-07-21'
fingerprint: sha256:465a1380c5aaa0f2edc54b6811c494148cceec21d28164f20a432f026096487a
related: []
sources:
- src/sevn/voice/**
parent_prd: prd-01-conversational-experience
depends_on:
- spec-02-config-and-workspace
- spec-05-llm-transports
- spec-06-secrets
- spec-07-egress-proxy
- spec-09-security-scanner
- spec-17-gateway
build_phase: null
interfaces:
- name: EdgeTtsBackend
  file: src/sevn/voice/backends.py
  symbol: EdgeTtsBackend
- name: KokoroBackend
  file: src/sevn/voice/backends.py
  symbol: KokoroBackend
- name: SpeechToTextBackend
  file: src/sevn/voice/backends.py
  symbol: SpeechToTextBackend
- name: SynthesisResult
  file: src/sevn/voice/backends.py
  symbol: SynthesisResult
- name: TextToSpeechBackend
  file: src/sevn/voice/backends.py
  symbol: TextToSpeechBackend
- name: TextToVoiceBackend
  file: src/sevn/voice/backends.py
  symbol: TextToVoiceBackend
- name: TranscriptionResult
  file: src/sevn/voice/backends.py
  symbol: TranscriptionResult
- name: WhisperCppBackend
  file: src/sevn/voice/backends.py
  symbol: WhisperCppBackend
- name: build_stt_backend
  file: src/sevn/voice/backends.py
  symbol: build_stt_backend
- name: build_tts_backend
  file: src/sevn/voice/backends.py
  symbol: build_tts_backend
- name: validate_voice_backend_tags
  file: src/sevn/voice/backends.py
  symbol: validate_voice_backend_tags
- name: whisper_cpp_missing_prereqs
  file: src/sevn/voice/backends.py
  symbol: whisper_cpp_missing_prereqs
- name: voice_http_base_url
  file: src/sevn/voice/egress.py
  symbol: voice_http_base_url
- name: VoiceRuntimeSettings
  file: src/sevn/voice/factory.py
  symbol: VoiceRuntimeSettings
- name: build_stt_pipeline
  file: src/sevn/voice/factory.py
  symbol: build_stt_pipeline
- name: build_tts_pipeline
  file: src/sevn/voice/factory.py
  symbol: build_tts_pipeline
- name: maybe_preload_local_tts
  file: src/sevn/voice/factory.py
  symbol: maybe_preload_local_tts
- name: probe_voice_backends
  file: src/sevn/voice/factory.py
  symbol: probe_voice_backends
- name: prune_stale_tts_files
  file: src/sevn/voice/factory.py
  symbol: prune_stale_tts_files
- name: resolve_effective_tts_mode
  file: src/sevn/voice/factory.py
  symbol: resolve_effective_tts_mode
- name: voice_enabled
  file: src/sevn/voice/factory.py
  symbol: voice_enabled
- name: voice_runtime_settings
  file: src/sevn/voice/factory.py
  symbol: voice_runtime_settings
- name: maybe_resolve_whisper_model_env
  file: src/sevn/voice/host_deps.py
  symbol: maybe_resolve_whisper_model_env
- name: provision_voice_deps
  file: src/sevn/voice/host_deps.py
  symbol: provision_voice_deps
- name: voice_host_dep_ids
  file: src/sevn/voice/host_deps.py
  symbol: voice_host_dep_ids
- name: compile_voice_trigger_patterns
  file: src/sevn/voice/keywords.py
  symbol: compile_voice_trigger_patterns
- name: user_text_matches_voice_trigger
  file: src/sevn/voice/keywords.py
  symbol: user_text_matches_voice_trigger
- name: SpeechToTextBackend
  file: src/sevn/voice/stt.py
  symbol: SpeechToTextBackend
- name: SpeechToTextPipeline
  file: src/sevn/voice/stt.py
  symbol: SpeechToTextPipeline
- name: transcribe_placeholder
  file: src/sevn/voice/stt.py
  symbol: transcribe_placeholder
- name: emit_voice_event
  file: src/sevn/voice/trace_events.py
  symbol: emit_voice_event
- name: TextToSpeechBackend
  file: src/sevn/voice/tts.py
  symbol: TextToSpeechBackend
- name: TextToSpeechPipeline
  file: src/sevn/voice/tts.py
  symbol: TextToSpeechPipeline
- name: TtsSynthOutcome
  file: src/sevn/voice/tts.py
  symbol: TtsSynthOutcome
- name: speak_placeholder
  file: src/sevn/voice/tts.py
  symbol: speak_placeholder
- name: WhisperModelSpec
  file: src/sevn/voice/whisper_model_provisioner.py
  symbol: WhisperModelSpec
- name: default_whisper_model_cache_dir
  file: src/sevn/voice/whisper_model_provisioner.py
  symbol: default_whisper_model_cache_dir
- name: ensure_whisper_model
  file: src/sevn/voice/whisper_model_provisioner.py
  symbol: ensure_whisper_model
- name: is_whisper_model_cached
  file: src/sevn/voice/whisper_model_provisioner.py
  symbol: is_whisper_model_cached
- name: model_path_for
  file: src/sevn/voice/whisper_model_provisioner.py
  symbol: model_path_for
---

## Purpose

Own the provider-chain facades for speech-to-text and text-to-speech so the gateway can:

Primary code trees: [`src/sevn/voice`](src/sevn/voice/__init__.py).

Initial draft for **Purpose** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Purpose — acceptance criteria and edge cases. -->
## Public Interface

Initial draft for **Public Interface** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Public Interface — acceptance criteria and edge cases. -->

- [`EdgeTtsBackend`](src/sevn/voice/backends.py) — `src/sevn/voice/backends.py`
- [`KokoroBackend`](src/sevn/voice/backends.py) — `src/sevn/voice/backends.py`
- [`SpeechToTextBackend`](src/sevn/voice/backends.py) — `src/sevn/voice/backends.py`
- [`SynthesisResult`](src/sevn/voice/backends.py) — `src/sevn/voice/backends.py`
- [`TextToSpeechBackend`](src/sevn/voice/backends.py) — `src/sevn/voice/backends.py`
- [`TranscriptionResult`](src/sevn/voice/backends.py) — `src/sevn/voice/backends.py`
- [`WhisperCppBackend`](src/sevn/voice/backends.py) — `src/sevn/voice/backends.py`
- [`build_stt_backend`](src/sevn/voice/backends.py) — `src/sevn/voice/backends.py`
- [`build_tts_backend`](src/sevn/voice/backends.py) — `src/sevn/voice/backends.py`
- [`validate_voice_backend_tags`](src/sevn/voice/backends.py) — `src/sevn/voice/backends.py`
- [`whisper_cpp_missing_prereqs`](src/sevn/voice/backends.py) — `src/sevn/voice/backends.py`
- [`voice_http_base_url`](src/sevn/voice/egress.py) — `src/sevn/voice/egress.py`
- _…and 27 more in frontmatter `interfaces:`._
## Data Model

Initial draft for **Data Model** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Data Model — acceptance criteria and edge cases. -->

- [`EdgeTtsBackend`](src/sevn/voice/backends.py) — `src/sevn/voice/backends.py`
- [`KokoroBackend`](src/sevn/voice/backends.py) — `src/sevn/voice/backends.py`
- [`SpeechToTextBackend`](src/sevn/voice/backends.py) — `src/sevn/voice/backends.py`
- [`SynthesisResult`](src/sevn/voice/backends.py) — `src/sevn/voice/backends.py`
- [`TextToSpeechBackend`](src/sevn/voice/backends.py) — `src/sevn/voice/backends.py`
- [`TranscriptionResult`](src/sevn/voice/backends.py) — `src/sevn/voice/backends.py`
- [`WhisperCppBackend`](src/sevn/voice/backends.py) — `src/sevn/voice/backends.py`
- [`build_stt_backend`](src/sevn/voice/backends.py) — `src/sevn/voice/backends.py`
- [`build_tts_backend`](src/sevn/voice/backends.py) — `src/sevn/voice/backends.py`
- [`validate_voice_backend_tags`](src/sevn/voice/backends.py) — `src/sevn/voice/backends.py`
- [`whisper_cpp_missing_prereqs`](src/sevn/voice/backends.py) — `src/sevn/voice/backends.py`
- [`voice_http_base_url`](src/sevn/voice/egress.py) — `src/sevn/voice/egress.py`
- _…and 27 more in frontmatter `interfaces:`._
## Internal Architecture

See **Implemented by** and [`src/sevn/voice`](src/sevn/voice/__init__.py).
## Behavior

`build_tts_pipeline` reads `VoiceRuntimeSettings.local_tts_engine` (from
`voice.local_tts_engine`) and passes it into `build_tts_backend` so the
`text_to_voice` backend's `.engine` matches config (`kokoro` / `supertonic`). Telegram
`/config` → Voice engine cycle and `/voice <code>` both reload the workspace so the
live pipeline picks up the selection without restart.
Supertonic codes are persisted uppercase so synthesis does not silently fall back to `M1`.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Behavior — acceptance criteria and edge cases. -->

Trace control flow starting from the load-bearing symbols in **Implemented by** (below) and cross-check against [`src/sevn/voice`](src/sevn/voice/__init__.py).
## Failure Modes

Unknown `/voice` tokens that look like voice codes are rejected with an operator-visible
message (no persist). Legacy workspace `kokoro-tts` scripts without `--engine` omit that
flag during synthesize so `rc=2` does not break replies.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Failure Modes — acceptance criteria and edge cases. -->

Document observable failure surfaces from the implementing modules (exceptions, logged errors, degraded modes) — cite code paths.
## Test Strategy

`/voice` code normalisation + persist: `tests/gateway/test_voice.py`,
`tests/voice/test_text_to_voice_backend_w1_red.py`. Pipeline engine wiring + legacy
`--engine` omit: `tests/voice/test_text_to_voice_backend.py` /
`test_text_to_voice_backend_w1_red.py`. Menu→reload→pipeline `.engine` via
`VoiceRuntimeSettings.local_tts_engine`: `tests/gateway/test_voice_menu_pipeline_w1_red.py`.
Live Telegram `/config → Voice` spoken-reply E2E remains deferred (no creds /
`make telegram-e2e` not runnable here).

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Test Strategy — acceptance criteria and edge cases. -->

Map to existing tests under `tests/` that cover this subsystem; add Makefile-only gates where applicable.

## Human-input needed

Prose body not yet authored (W9 scope). Normative contract requires operator or
follow-up wave authoring against verified code (`sevn about-docs extract` + graphify).
Do not mark `status: done` until `make -C spec-kit-wave spec-check` scores ≥ 80.
