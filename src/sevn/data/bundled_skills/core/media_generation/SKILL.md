---
name: media_generation
description: MiniMax media generation — image, video (t2v/i2v/s2v/fl2v/templates), voice clone/TTS, music — via media_generator L2 specialist with lean prompt templates and trace metadata.
version: "2.2.0"
specialist: media_generator
requires_specialist: media_generator
see_also:
  - spawn_subagent
scripts:
  - path: scripts/_common.py
    description: Shared helpers (prompt-var flags, JSON envelope).
    args_overview: "(library module — not invoked directly)"
  - path: scripts/generate_image.py
    description: Text-to-image with optional scene/style variables.
    args_overview: "PROMPT [--template SLUG] [--scene TEXT] [--style TEXT] [--mood TEXT] [--aspect-ratio 16:9]"
  - path: scripts/generate_image_from_reference.py
    description: Image-to-image from reference portrait.
    args_overview: "PROMPT REFERENCE [--template SLUG] [--scene] [--style] [--mood]"
  - path: scripts/generate_video.py
    description: Text-to-video (optional --image for i2v). Prefer wait=false when spawning.
    args_overview: "PROMPT [--template SLUG] [--scene] [--camera] [--duration 6] [--image PATH]"
  - path: scripts/generate_video_from_image.py
    description: Image-to-video with motion templates.
    args_overview: "PROMPT IMAGE [--template SLUG] [--scene] [--duration 6]"
  - path: scripts/generate_video_subject.py
    description: Face-consistent subject-reference video (S2V). Prefer wait=false.
    args_overview: "PROMPT SUBJECT_IMAGE [--template SLUG] [--scene] [--delivery]"
  - path: scripts/generate_video_first_last.py
    description: Morph between first and last frame images (FL2V). Prefer wait=false.
    args_overview: "PROMPT FIRST LAST [--template SLUG] [--duration 6]"
  - path: scripts/generate_video_template.py
    description: MiniMax Video Agent template (16 official templates). Prefer wait=false.
    args_overview: "TEMPLATE_SLUG_OR_ID [--prompt TEXT] [--text TEXT] [--image PATH]"
  - path: scripts/generate_music.py
    description: Music generation with genre/tempo/mood variables.
    args_overview: "PROMPT [--template SLUG] [--genre] [--tempo] [--lyrics TEXT] [--instrumental]"
  - path: scripts/replicate_voice.py
    description: Voice clone or TTS — speech_text/preview_text are spoken verbatim.
    args_overview: "clone PROMPT SOURCE_AUDIO --preview-text TEXT | speak PROMPT VOICE_ID SPEECH_TEXT"
  - path: scripts/list_prompt_templates.py
    description: List augmentation templates with variable slots.
    args_overview: "[--kind image|video|music|voice|…]"
  - path: scripts/list_video_templates.py
    description: List MiniMax Video Agent templates.
    args_overview: "(no args)"
---

# media_generation skill

> Full reference: [`README.md`](README.md). Samples: [`examples.json`](examples.json).

MiniMax-backed **level-2 `media_generator`**. Pass a short `prompt` plus optional
structured variables (`scene`, `style`, `mood`, …). Unknown template slugs **error**
(no silent fallback). Unset variables are omitted from the augmented prompt.

## Wait policy (spawn)

| Kind | Recommended `wait` |
|------|-------------------|
| `image`, `image_i2i`, `music`, `voice` | `wait=true` |
| `video`, `video_i2v`, `video_s2v`, `video_fl2v`, `video_template` | `wait=false` (announce-back) |

Video polls can take minutes; cascade `wait=true` may kill the run.

## Voice: literal spoken text

`speech_text` / `preview_text` are sent **verbatim** to MiniMax TTS/clone preview.
Delivery/mood templates appear only in `trace`, never as the utterance.
Voice tasks require JSON (shorthand `voice:…` is rejected).

## Kinds

| Kind | Required |
|------|----------|
| `image` | `prompt` |
| `image_i2i` | `prompt`, `reference_image` |
| `video` | `prompt` (optional `first_frame_image`) |
| `video_i2v` | `prompt`, `first_frame_image` |
| `video_s2v` | `prompt`, `subject_reference` |
| `video_fl2v` | `prompt`, `first_frame_image`, `last_frame_image` |
| `video_template` | `template_id` (+ slots) |
| `music` | `prompt` |
| `voice` | `source_audio`+`preview_text\|speech_text` **or** `voice_id`+`speech_text` |

## Spawn examples

```python
# Image (wait OK)
spawn_subagent(specialist="media_generator", wait=true,
  task='{"kind":"image","prompt":"fox in autumn","scene":"forest","style":"watercolor","template":"illustration"}')

# Video (fire-and-forget)
spawn_subagent(specialist="media_generator", wait=false,
  task='{"kind":"video","prompt":"waves on rocks","template":"nature","scene":"coast at dawn"}')

# Voice TTS (literal text)
spawn_subagent(specialist="media_generator", wait=true,
  task='{"kind":"voice","prompt":"warm narrator","voice_id":"English_expressive_narrator","speech_text":"Welcome back to the show."}')
```

## Configuration

Requires `subagents.specialists.media_generator` + MiniMax API key.
See README.md for API matrix, templates, and ops notes.
