# media_generation — MiniMax L2 specialist reference

Level-2 **`media_generator`** specialist backed by MiniMax REST APIs.
Operators pass **short intents**; the worker augments them with **templates** and
**structured variables** (`scene`, `style`, `mood`, …) before calling MiniMax.

## Quick start

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

API key: `providers.minimax.api_key` or `MINIMAX_API_KEY` / `SEVN_SECRET_MINIMAX`.

```python
spawn_subagent(
  specialist="media_generator",
  wait=true,
  task='{"kind":"image","prompt":"fox in autumn","scene":"forest","style":"watercolor","template":"illustration"}'
)
```

---

## API coverage matrix

Every row is a **separate MiniMax API call path** implemented in `media_minimax.py`.

| Kind | MiniMax API | Model | Required inputs | Optional variables |
|------|-------------|-------|---------------|-------------------|
| `image` | `/v1/image_generation` (T2I) | `image-01` | `prompt` | `scene`, `style`, `mood`, `lighting`, `aspect_ratio` |
| `image_i2i` | `/v1/image_generation` (I2I) | `image-01` | `prompt`, `reference_image` | `scene`, `style`, `mood`, `template` |
| `video` | `/v1/video_generation` (T2V) | `MiniMax-Hailuo-2.3` | `prompt` | `scene`, `style`, `camera`, `first_frame_image`*, `duration`, `resolution` |
| `video_i2v` | `/v1/video_generation` (I2V) | `MiniMax-Hailuo-2.3` | `prompt`, `first_frame_image` | `scene`, `style`, `camera`, `mood` |
| `video_s2v` | `/v1/video_generation` (S2V) | `S2V-01` | `prompt`, `subject_reference` | `subject`, `scene`, `delivery` |
| `video_fl2v` | `/v1/video_generation` (FL2V) | `MiniMax-Hailuo-02` | `prompt`, `first_frame_image`, `last_frame_image` | `scene`, `mood`, `duration`, `resolution` |
| `video_template` | `/v1/video_template_generation` | Video Agent | `template_id` | `media_inputs`, `text_inputs`, `prompt` |
| `music` | `/v1/music_generation` | `music-2.6` | `prompt` | `genre`, `mood`, `tempo`, `instrumentation`, `lyrics` |
| `voice` (clone) | `/v1/files/upload` + `/v1/voice_clone` | `speech-2.8-hd` | `prompt`, `source_audio` | `delivery`, `preview_text`, `prompt_audio` |
| `voice` (TTS) | `/v1/t2a_v2` | `speech-2.8-hd` | `prompt`, `voice_id`, `speech_text` | `delivery`, `mood` |

\* `video` with `first_frame_image` uses I2V augmentation templates automatically.

### Async polling (video kinds)

Text/I2V/S2V/FL2V video: create task → poll `/v1/query/video_generation` → download via `/v1/files/retrieve`.
Video Agent: create task → poll `/v1/query/video_template_generation` → download `video_url`.

---

## Structured variables

Pass any subset in the JSON task. Omitted fields get sensible defaults.

| Variable | Used for | Example |
|----------|----------|---------|
| `scene` | image, video, music | `"rainy Tokyo alley at night"` |
| `style` | image, video | `"watercolor illustration"` |
| `subject` | image, video, voice | `"young woman with red scarf"` |
| `mood` | all kinds | `"melancholic but hopeful"` |
| `lighting` | image, video | `"neon rim light, high contrast"` |
| `camera` | video | `"[Push in] then [Pan left]"` |
| `genre` | music | `"synthwave"` |
| `tempo` | music | `"120 BPM, four-on-the-floor"` |
| `instrumentation` | music | `"strings, piano, subtle percussion"` |
| `delivery` | voice | `"warm, conversational podcast host"` |

The worker always includes `prompt` (short user intent). Templates combine all slots into the
final `augmented_prompt` returned in `trace`.

---

## Augmentation templates (by kind)

Discover at runtime:

```python
run_skill_script(skill="media_generation", script="scripts/list_prompt_templates.py", argv=[])
```

### Image (8 templates)

| Slug | Best for |
|------|----------|
| `default` | General purpose |
| `portrait` | Headshots, people |
| `product` | E-commerce |
| `illustration` | Stylized art |
| `cinematic` | Film stills |
| `anime` | Anime/manga |
| `landscape` | Environments |
| `architectural` | Buildings/interiors |

### Image I2I (4 templates)

`default`, `style_transfer`, `wardrobe`, `background`

### Video T2V (6 templates)

`default`, `commercial`, `nature`, `action`, `timelapse`, `dialogue`

### Video I2V (4 templates)

`default`, `subtle`, `dynamic`, `portrait_live`

### Video S2V (3 templates)

`default`, `talking_head`, `reaction`

### Video FL2V (3 templates)

`default`, `growth`, `morph`

### Music (7 templates)

`default`, `lofi`, `cinematic`, `jingle`, `ambient`, `electronic`, `acoustic`

### Voice (5 templates)

`default`, `narration`, `character`, `commercial`, `audiobook`

---

## Video Agent templates (16 official)

Source: [MiniMax Video Agent Template List](https://platform.minimax.io/docs/faq/video-agent-templates)

```python
run_skill_script(skill="media_generation", script="scripts/list_video_templates.py", argv=[])
```

| Slug | Name | Media | Text | Example |
|------|------|-------|------|---------|
| `diving` | Diving | ✓ | — | portrait photo |
| `run_for_life` | Run for Life | ✓ | ✓ | `"Lion"` + pet photo |
| `transformers` | Transformers | ✓ | — | car photo |
| `still_rings` | Still rings routine | ✓ | — | athlete photo |
| `weightlifting` | Weightlifting | ✓ | — | pet photo |
| `climbing` | Climbing | ✓ | — | climber photo |
| `anime_life_sim` | Anime Life Sim | — | ✓ | scene description |
| `mcdonalds_delivery_pet` | McDonald's Delivery Pet | ✓ | — | pet photo |
| `pet_pilot` | Pet Pilot | ✓ | — | pet photo |
| `miniature_set_ad` | Miniature Set Ad | ✓ | — | product photo |
| `male_tryon_ad` | Male Model Try-On Ad | ✓ | — | clothing image |
| `female_tryon_ad` | Female Model Try-On Ad | ✓ | — | clothing image |
| `art_fonts` | Art Fonts | — | ✓ | word + element |
| `drinkfall` | Drinkfall | ✓ | — | beverage product |
| `ecommerce_display_ad` | E-commerce Display Ad | — | ✓ | product description |
| `3d_character_product` | 3D character product presentation | ✓ | ✓ | product + description |

---

## Skill scripts

| Script | Purpose |
|--------|---------|
| `generate_image.py` | Text → image |
| `generate_image_from_reference.py` | Reference portrait → styled image |
| `generate_video.py` | Text → video (optional `--image`) |
| `generate_video_from_image.py` | Image + text → video |
| `generate_video_template.py` | Video Agent template |
| `generate_music.py` | Text → music |
| `replicate_voice.py` | `clone` or `speak` |
| `list_prompt_templates.py` | Augmentation template catalog |
| `list_video_templates.py` | Video Agent template catalog |

---

## Sample tasks

Full copy-paste library: **`examples.json`** (17 samples covering every kind).

### Image with scene + style

```json
{
  "kind": "image",
  "prompt": "woman reading by window",
  "template": "portrait",
  "scene": "cozy library",
  "style": "film photography",
  "mood": "contemplative",
  "lighting": "golden hour window light",
  "aspect_ratio": "3:4"
}
```

### Image-to-image style transfer

```json
{
  "kind": "image_i2i",
  "prompt": "render as oil painting",
  "template": "style_transfer",
  "reference_image": "channel_files/sess/portrait.jpg",
  "style": "impressionist brush strokes"
}
```

### Video with camera commands

```json
{
  "kind": "video",
  "prompt": "product reveal",
  "template": "commercial",
  "camera": "[Push in] hero shot",
  "scene": "dark studio",
  "duration": 6,
  "resolution": "1080P"
}
```

### Subject-reference video (face consistent)

```json
{
  "kind": "video_s2v",
  "prompt": "waves and smiles at camera",
  "subject_reference": "channel_files/sess/face.jpg",
  "template": "talking_head",
  "delivery": "friendly professional"
}
```

### First ↔ last frame morph

```json
{
  "kind": "video_fl2v",
  "prompt": "years pass, child becomes adult",
  "first_frame_image": "channel_files/sess/child.jpg",
  "last_frame_image": "channel_files/sess/adult.jpg",
  "template": "growth",
  "resolution": "1080P"
}
```

### Music with genre + tempo

```json
{
  "kind": "music",
  "prompt": "late night drive",
  "template": "electronic",
  "genre": "synthwave",
  "tempo": "110 BPM",
  "mood": "nostalgic",
  "is_instrumental": true
}
```

### Voice clone + preview

```json
{
  "kind": "voice",
  "prompt": "podcast host",
  "template": "narration",
  "delivery": "warm conversational",
  "source_audio": "channel_files/sess/sample.mp3",
  "preview_text": "Welcome back to the show."
}
```

---

## Trace output (observability)

Every success returns:

```json
{
  "artifact_path": "channel_files/sess/media-image-fox.jpg",
  "kind": "image",
  "bytes": 245760,
  "trace": {
    "user_request": "fox in autumn",
    "template_key": "illustration",
    "augmented_prompt": "Digital illustration. Scene: forest. Subject: fox in autumn. …",
    "variables": {
      "scene": "forest",
      "style": "watercolor",
      "user_request": "fox in autumn",
      "subject": "fox in autumn"
    },
    "api_model": "image-01"
  }
}
```

Use `trace.augmented_prompt` to debug provider behavior without re-running jobs.

---

## Task JSON schema (all fields)

```jsonc
{
  "kind": "image|image_i2i|video|video_i2v|video_s2v|video_fl2v|video_template|music|voice",
  "prompt": "short user intent (required except video_template)",
  "template": "augmentation template slug",
  // structured variables (all optional):
  "scene": "", "style": "", "subject": "", "mood": "",
  "lighting": "", "camera": "", "genre": "", "tempo": "",
  "instrumentation": "", "delivery": "",
  // image:
  "aspect_ratio": "16:9",
  "reference_image": "path or URL",
  // video:
  "duration": 6, "resolution": "1080P",
  "first_frame_image": "", "last_frame_image": "",
  "subject_reference": "",
  // video agent:
  "template_id": "pet_pilot",
  "media_inputs": ["path.jpg"],
  "text_inputs": ["Lion"],
  // music:
  "lyrics": "", "is_instrumental": false,
  // voice:
  "source_audio": "", "voice_id": "", "speech_text": "",
  "preview_text": "", "prompt_audio": "", "prompt_text": ""
}
```

Shorthand: `image:prompt text`, `music:lofi beat`, `voice:calm narrator` (JSON preferred for variables).

---

## Not yet covered (MiniMax APIs)

These exist in MiniMax docs but are **not** wired in this specialist:

- Voice Design (`/v1/voice_design`) — design voice from text description without sample
- Lyrics-only generation (`/v1/lyrics_generation`)
- Music cover (`music-cover` pipeline)
- Async long-form TTS (>10k chars)
- Image `n` > 1 (multi-image per request)

Open an issue or extend `media_minimax.py` if you need these.

---

## Errors

| Message | Fix |
|---------|-----|
| `configure subagents.specialists.media_generator` | Add specialist block to `sevn.json` |
| `MiniMax API key missing` | Set `providers.minimax.api_key` |
| `requires first_frame_image` | Provide image path/URL for i2v/fl2v |
| `requires subject_reference` | Provide face photo for s2v |
| `unknown video agent template` | Run `list_video_templates.py` |
