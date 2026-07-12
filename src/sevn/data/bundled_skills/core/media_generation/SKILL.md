---
name: media_generation
description: Generate images, video, and music via the MiniMax-backed media_generator specialist (spec 36 D8).
version: "1.0.0"
specialist: media_generator
requires_specialist: media_generator
see_also:
  - spawn_subagent
scripts:
  - path: scripts/_common.py
    description: Shared MiniMax client helpers for media_generation scripts.
    args_overview: "(library module — not invoked directly)"
  - path: scripts/generate_image.py
    description: Generate a JPEG image from a text prompt via media_generator.
    args_overview: "PROMPT [--aspect-ratio 16:9]"
  - path: scripts/generate_video.py
    description: Generate an MP4 clip from a text prompt via media_generator.
    args_overview: "PROMPT [--duration 6] [--resolution 720P]"
  - path: scripts/generate_music.py
    description: Generate an MP3 track from style prompt (+ optional lyrics) via media_generator.
    args_overview: "PROMPT [--lyrics TEXT] [--instrumental]"
---

# media_generation skill

MiniMax-backed media generation through the **`media_generator`** level-2 specialist
(`subagents.specialists.media_generator`, D8). Requires the specialist block in
`sevn.json` plus a MiniMax API key (`providers.minimax.api_key` or `SEVN_SECRET_MINIMAX`).

## Preferred tier-B path (spawn + wait)

From tier B, prefer the native spawn tool so the run is tracked in the sub-agent registry:

```
spawn_subagent(
  specialist="media_generator",
  wait=true,
  task='{"kind":"image","prompt":"a watercolor fox in autumn"}'
)
```

Task shorthand also works: `task="image:a watercolor fox in autumn"`.

On success the tool returns JSON with `artifact_path` under `channel_files/<session_id>/…`
for `send_file` / channel delivery.

## Skill scripts (`run_skill_script`)

These scripts execute the **same** `media_generator` worker path inline (useful when the
model already loaded this skill). They require `subagents.specialists.media_generator`
and persist artifacts through `media_store`.

```
run_skill_script(skill="media_generation", script="scripts/generate_image.py", argv=["sunset over mountains"])
run_skill_script(skill="media_generation", script="scripts/generate_video.py", argv=["a cat walking in the rain"])
run_skill_script(skill="media_generation", script="scripts/generate_music.py", argv=["lo-fi study beat", "--instrumental"])
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

When the specialist is missing, scripts and the spawn tool return a clear message:
`configure subagents.specialists.media_generator`.
