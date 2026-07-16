---
name: media_generation
description: MiniMax media generation — image, video (text/i2v/templates), voice replication, music — via media_generator L2 specialist with prompt templates and trace metadata.
version: "2.0.0"
specialist: media_generator
requires_specialist: media_generator
see_also:
  - spawn_subagent
scripts:
  - path: scripts/_common.py
    description: Shared MiniMax client helpers for media_generation scripts.
    args_overview: "(library module — not invoked directly)"
  - path: scripts/generate_image.py
    description: Generate a JPEG image from a short text intent via media_generator.
    args_overview: "PROMPT [--template default|portrait|product|illustration] [--aspect-ratio 16:9]"
  - path: scripts/generate_video.py
    description: Generate an MP4 clip from text (optional first-frame image) via media_generator.
    args_overview: "PROMPT [--template default|commercial|nature] [--duration 6] [--resolution 720P] [--image PATH]"
  - path: scripts/generate_video_from_image.py
    description: Image-to-video — animate a source image with a short motion intent.
    args_overview: "PROMPT IMAGE [--template default|subtle|dynamic] [--duration 6] [--resolution 1080P]"
  - path: scripts/generate_video_template.py
    description: MiniMax Video Agent template generation (official template catalog).
    args_overview: "TEMPLATE_SLUG_OR_ID [--prompt TEXT] [--text TEXT] [--image PATH]"
  - path: scripts/list_video_templates.py
    description: List all MiniMax Video Agent templates (id, slug, inputs).
    args_overview: "(no args)"
  - path: scripts/replicate_voice.py
    description: Voice replication (clone from audio) or TTS with existing voice_id.
    args_overview: "clone PROMPT SOURCE_AUDIO | speak PROMPT VOICE_ID SPEECH_TEXT"
  - path: scripts/generate_music.py
    description: Generate an MP3 track from style intent (+ optional lyrics) via media_generator.
    args_overview: "PROMPT [--template default|lofi|cinematic|jingle] [--lyrics TEXT] [--instrumental]"
---

# media_generation skill

MiniMax-backed **level-2 `media_generator` specialist** (`subagents.specialists.media_generator`, spec 36 D8).
Requires the specialist block in `sevn.json` plus a MiniMax API key (`providers.minimax.api_key` or `SEVN_SECRET_MINIMAX`).

## Design: short user intent + templates

Operators write a **short request** — not a full provider prompt. The worker augments it with
per-kind **prompt templates** before calling MiniMax. Every successful run returns a **`trace`**
block with `user_request`, `template_key`, `augmented_prompt`, and `api_model` for observability.

### Prompt template slugs

| Kind | Template slugs | Example user request |
|------|----------------|----------------------|
| `image` | `default`, `portrait`, `product`, `illustration` | `a fox in autumn leaves` |
| `video` | `default`, `commercial`, `nature` | `sunset over calm ocean` |
| `video_i2v` | `default`, `subtle`, `dynamic` | `gentle breeze, leaves rustling` |
| `music` | `default`, `lofi`, `cinematic`, `jingle` | `rainy night café ambience` |
| `voice` | `default`, `narration`, `character` | `warm British narrator` |

Pass `"template": "<slug>"` in JSON tasks or `--template <slug>` in skill scripts.

## Functions (media kinds)

### 1. Image from text (`kind: image`)

```json
{"kind":"image","prompt":"a watercolor fox","template":"illustration","aspect_ratio":"16:9"}
```

Shorthand: `image:a watercolor fox`

### 2. Video from text (`kind: video`)

```json
{"kind":"video","prompt":"waves crashing on rocks","template":"nature","duration":6,"resolution":"1080P"}
```

Optional image-to-video in the same kind — add `first_frame_image`:

```json
{"kind":"video","prompt":"subject turns and smiles","first_frame_image":"channel_files/sess/photo.jpg"}
```

### 3. Video from image + text (`kind: video_i2v`)

Dedicated image-to-video with `first_frame_image` required:

```json
{"kind":"video_i2v","prompt":"slow zoom in, soft lighting","first_frame_image":"channel_files/sess/photo.jpg","template":"subtle"}
```

### 4. Video Agent templates (`kind: video_template`)

Uses official MiniMax Video Agent templates ([template list](https://platform.minimax.io/docs/faq/video-agent-templates)).
Resolve by numeric id or slug (`run_for_life`, `diving`, `pet_pilot`, …).

```json
{
  "kind": "video_template",
  "template_id": "run_for_life",
  "prompt": "Lion",
  "media_inputs": ["channel_files/sess/pet.jpg"]
}
```

List templates: `run_skill_script(skill="media_generation", script="scripts/list_video_templates.py", argv=[])`

| Slug | Name | Media | Text |
|------|------|-------|------|
| `diving` | Diving | required | — |
| `run_for_life` | Run for Life | required | required |
| `transformers` | Transformers | required | — |
| `anime_life_sim` | Anime Life Sim | — | required |
| `pet_pilot` | Pet Pilot | required | — |
| `male_tryon_ad` | Male Model Try-On Ad | required | — |
| `ecommerce_display_ad` | E-commerce Display Ad | — | required |
| `3d_character_product` | 3D character product presentation | required | required |

(Full catalog: 16 templates — use `list_video_templates.py`.)

### 5. Voice replication (`kind: voice`)

**Clone** from a source audio sample (10s–5min, mp3/m4a/wav):

```json
{
  "kind": "voice",
  "prompt": "friendly podcast host",
  "template": "narration",
  "source_audio": "channel_files/sess/sample.mp3",
  "preview_text": "Welcome to today's episode."
}
```

Returns `voice_id` (reuse within 7 days) and preview MP3 artifact.

**Synthesize** with an existing `voice_id` (cloned or system):

```json
{
  "kind": "voice",
  "prompt": "calm delivery",
  "voice_id": "English_expressive_narrator",
  "speech_text": "The quick brown fox jumps over the lazy dog."
}
```

Optional `prompt_audio` + `prompt_text` (<8s sample) improve clone quality.

### 6. Music generation (`kind: music`)

```json
{"kind":"music","prompt":"upbeat indie pop","template":"jingle","lyrics":"[Verse] Hello world"}
```

Instrumental: `"is_instrumental": true` or `--instrumental`.

## Preferred tier-B path (spawn + wait)

```python
spawn_subagent(
  specialist="media_generator",
  wait=true,
  task='{"kind":"image","prompt":"a watercolor fox","template":"illustration"}'
)
```

On success the tool returns JSON with `artifact_path` under `channel_files/<session_id>/…`
and a `trace` object. Use `send_file` / channel delivery for the artifact.

## Skill scripts (`run_skill_script`)

```python
run_skill_script(skill="media_generation", script="scripts/generate_image.py", argv=["sunset mountains", "--template", "default"])
run_skill_script(skill="media_generation", script="scripts/generate_video.py", argv=["cat in rain", "--duration", "6"])
run_skill_script(skill="media_generation", script="scripts/generate_video_from_image.py", argv=["gentle wind", "channel_files/sess/photo.jpg"])
run_skill_script(skill="media_generation", script="scripts/generate_video_template.py", argv=["pet_pilot", "--image", "channel_files/sess/pet.jpg"])
run_skill_script(skill="media_generation", script="scripts/replicate_voice.py", argv=["clone", "warm narrator", "samples/voice.mp3", "--preview-text", "Hello there."])
run_skill_script(skill="media_generation", script="scripts/generate_music.py", argv=["lo-fi study beat", "--template", "lofi", "--instrumental"])
run_skill_script(skill="media_generation", script="scripts/list_video_templates.py", argv=[])
```

## Trace output example

```json
{
  "artifact_path": "channel_files/sess-media/media-image-fox.jpg",
  "kind": "image",
  "bytes": 245760,
  "trace": {
    "user_request": "a fox in autumn",
    "template_key": "illustration",
    "augmented_prompt": "Digital illustration: a fox in autumn. Consistent art style, vivid colors, polished finish.",
    "api_model": "image-01"
  }
}
```

## Configuration example (not shipped as default)

```json
"subagents": {
  "specialists": {
    "media_generator": {
      "model": "minimax-3",
      "provider": "minimax",
      "assigned_to": ["tier_b"],
      "requestable_by": ["triager", "tier_b"],
      "max_concurrent": 2,
      "skill": "media_generation"
    }
  }
}
```

When triage selects the `media_generation` skill, the gateway auto-grants the
`media_generator` specialist for that tier-B dispatch (W8.3).

## Errors

When the specialist is missing: `configure subagents.specialists.media_generator`.
When MiniMax key is missing: set `providers.minimax.api_key` or `MINIMAX_API_KEY`.
