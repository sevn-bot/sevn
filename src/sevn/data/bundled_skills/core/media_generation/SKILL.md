---
name: media_generation
description: MiniMax media generation — 9 API paths, scene/style variables, 40+ prompt templates, 16 video agent templates, voice, music — via media_generator L2 specialist.
version: "2.1.0"
specialist: media_generator
requires_specialist: media_generator
see_also:
  - spawn_subagent
scripts:
  - path: scripts/_common.py
    description: Shared MiniMax client helpers for media_generation scripts.
    args_overview: "(library module — not invoked directly)"
  - path: scripts/generate_image.py
    description: Text-to-image with scene/style variables and template augmentation.
    args_overview: "PROMPT [--template SLUG] [--scene TEXT] [--style TEXT] [--aspect-ratio 16:9]"
  - path: scripts/generate_image_from_reference.py
    description: Image-to-image from reference portrait (style transfer, wardrobe, background).
    args_overview: "PROMPT REFERENCE [--template SLUG] [--scene] [--style] [--mood]"
  - path: scripts/generate_video.py
    description: Text-to-video (optional first-frame image) with camera/scene variables.
    args_overview: "PROMPT [--template SLUG] [--scene] [--camera] [--duration 6] [--image PATH]"
  - path: scripts/generate_video_from_image.py
    description: Image-to-video with motion/scene templates.
    args_overview: "PROMPT IMAGE [--template SLUG] [--scene] [--duration 6]"
  - path: scripts/generate_video_template.py
    description: MiniMax Video Agent template (16 official templates).
    args_overview: "TEMPLATE_SLUG_OR_ID [--prompt TEXT] [--text TEXT] [--image PATH]"
  - path: scripts/generate_music.py
    description: Music generation with genre/tempo/mood variables.
    args_overview: "PROMPT [--template SLUG] [--genre] [--tempo] [--lyrics TEXT] [--instrumental]"
  - path: scripts/replicate_voice.py
    description: Voice clone from audio sample or TTS with voice_id.
    args_overview: "clone PROMPT SOURCE_AUDIO | speak PROMPT VOICE_ID SPEECH_TEXT"
  - path: scripts/list_prompt_templates.py
    description: List all augmentation templates (40+) with variable slots.
    args_overview: "[--kind image|video|music|voice|…]"
  - path: scripts/list_video_templates.py
    description: List MiniMax Video Agent templates (id, slug, required inputs).
    args_overview: "(no args)"
---

# media_generation skill

> **Full reference:** see [`README.md`](README.md) in this skill folder.
> **Copy-paste samples:** see [`examples.json`](examples.json) (17 tasks, every kind).

MiniMax-backed **level-2 `media_generator` specialist**. Operators pass a **short `prompt`**
plus optional **structured variables** (`scene`, `style`, `mood`, `camera`, `genre`, …).
The worker augments with **templates** and returns **`trace`** metadata.

## 9 media kinds (= 9 MiniMax API paths)

| Kind | What it does |
|------|--------------|
| `image` | Text → image |
| `image_i2i` | Reference portrait → styled/transformed image |
| `video` | Text → video (add `first_frame_image` for i2v) |
| `video_i2v` | Image + text → video |
| `video_s2v` | Face-consistent character video (`subject_reference`) |
| `video_fl2v` | Morph between first + last frame images |
| `video_template` | MiniMax Video Agent (16 templates) |
| `music` | Text (+ optional lyrics) → MP3 |
| `voice` | Clone from audio or TTS with `voice_id` |

## Variables (all optional)

`scene`, `style`, `subject`, `mood`, `lighting`, `camera`, `genre`, `tempo`, `instrumentation`, `delivery`

```json
{
  "kind": "image",
  "prompt": "fox in autumn leaves",
  "template": "cinematic",
  "scene": "misty forest",
  "style": "film still, 35mm grain",
  "mood": "wonder",
  "lighting": "dappled morning light"
}
```

## Templates

- **Augmentation templates:** 40+ across kinds — `run_skill_script(..., "scripts/list_prompt_templates.py", [])`
- **Video Agent templates:** 16 official — `run_skill_script(..., "scripts/list_video_templates.py", [])`

## Spawn (preferred)

```python
spawn_subagent(specialist="media_generator", wait=true, task='{"kind":"music","prompt":"rainy café","template":"lofi","scene":"late night","is_instrumental":true}')
```

Returns `artifact_path` + `trace` (with `augmented_prompt` and `variables`).

## Configuration

Requires `subagents.specialists.media_generator` + MiniMax API key. See README.md.
