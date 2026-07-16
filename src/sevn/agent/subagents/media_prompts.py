"""Prompt templates and augmentation for the ``media_generator`` specialist.

Module: sevn.agent.subagents.media_prompts
Depends: dataclasses, typing

Exports:
    MediaPromptKind — supported augmentation families.
    MediaPromptVars — structured scene/style/subject variables.
    VideoAgentTemplate — one MiniMax Video Agent template entry.
    VIDEO_AGENT_TEMPLATES — official template catalog (IDs from MiniMax docs).
    PROMPT_TEMPLATES — per-kind prompt augmentation templates with variable slots.
    augment_prompt — merge user request + variables into a provider prompt.
    resolve_video_agent_template — lookup by id or slug.
    list_prompt_templates — discover augmentation templates per kind.
    build_media_trace — trace metadata for worker results.

Examples:
    >>> from sevn.agent.subagents.media_prompts import augment_prompt, MediaPromptVars
    >>> augment_prompt("image", "fox in leaves", vars=MediaPromptVars(scene="forest", style="watercolor"))
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

MediaPromptKind = Literal[
    "image",
    "image_i2i",
    "video",
    "video_i2v",
    "video_s2v",
    "video_fl2v",
    "video_template",
    "music",
    "voice",
]

_DEFAULT_TEMPLATE_KEY = "default"

# Variable placeholders available in augmentation templates.
PROMPT_VARIABLES: tuple[str, ...] = (
    "user_request",
    "scene",
    "style",
    "subject",
    "mood",
    "lighting",
    "camera",
    "genre",
    "tempo",
    "instrumentation",
    "delivery",
)


@dataclass(frozen=True, slots=True)
class MediaPromptVars:
    """Structured prompt variables — operator fills only what they know."""

    scene: str | None = None
    style: str | None = None
    subject: str | None = None
    mood: str | None = None
    lighting: str | None = None
    camera: str | None = None
    genre: str | None = None
    tempo: str | None = None
    instrumentation: str | None = None
    delivery: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        """Serialize vars for trace output.

        Returns:
            dict[str, str | None]: Non-empty fields only.

        Examples:
            >>> MediaPromptVars(scene="forest").to_dict()
            {'scene': 'forest'}
        """
        out: dict[str, str | None] = {}
        for name in PROMPT_VARIABLES:
            if name == "user_request":
                continue
            val = getattr(self, name, None)
            if isinstance(val, str) and val.strip():
                out[name] = val.strip()
        return out

    @classmethod
    def from_mapping(cls, raw: dict[str, object] | None) -> MediaPromptVars:
        """Build vars from a JSON task object subset.

        Args:
            raw (dict[str, object] | None): Task fields (``scene``, ``style``, …).

        Returns:
            MediaPromptVars: Parsed vars (missing keys → ``None``).

        Examples:
            >>> MediaPromptVars.from_mapping({"scene": "beach", "mood": "calm"}).scene
            'beach'
        """
        if not raw:
            return cls()
        kwargs: dict[str, str | None] = {}
        for name in PROMPT_VARIABLES:
            if name == "user_request":
                continue
            val = raw.get(name)
            if isinstance(val, str) and val.strip():
                kwargs[name] = val.strip()
        return cls(**kwargs)


@dataclass(frozen=True, slots=True)
class PromptTemplateMeta:
    """Metadata for one augmentation template."""

    slug: str
    description: str
    template: str
    variables: tuple[str, ...] = field(default_factory=lambda: PROMPT_VARIABLES)


@dataclass(frozen=True, slots=True)
class VideoAgentTemplate:
    """One MiniMax Video Agent template (see platform.minimax.io/docs/faq/video-agent-templates)."""

    template_id: str
    name: str
    slug: str
    description: str
    media_inputs_required: bool
    text_inputs_required: bool
    example_text: str | None = None
    example_media_hint: str | None = None


VIDEO_AGENT_TEMPLATES: tuple[VideoAgentTemplate, ...] = (
    VideoAgentTemplate("392747428568649728", "Diving", "diving", "Subject completes a perfect dive", True, False, example_media_hint="portrait or action photo"),
    VideoAgentTemplate("393769180141805569", "Run for Life", "run_for_life", "Pet survival video in the wilderness", True, True, "Lion", "pet photo"),
    VideoAgentTemplate("397087679467597833", "Transformers", "transformers", "Car transforms into mecha", True, False, example_media_hint="car photo"),
    VideoAgentTemplate("393881433990066176", "Still rings routine", "still_rings", "Subject performs still rings routine", True, False, example_media_hint="athlete photo"),
    VideoAgentTemplate("393498001241890824", "Weightlifting", "weightlifting", "Pet performs weightlifting", True, False, example_media_hint="pet photo"),
    VideoAgentTemplate("393488336655310850", "Climbing", "climbing", "Subject completes sport climbing", True, False, example_media_hint="climber photo"),
    VideoAgentTemplate("394514820878671878", "Anime Life Sim", "anime_life_sim", "Casual anime-style gameplay from scene description", False, True, "cozy café afternoon", None),
    VideoAgentTemplate("393879757702918151", "McDonald's Delivery Pet", "mcdonalds_delivery_pet", "Pet delivers McDonald's", True, False, example_media_hint="pet photo"),
    VideoAgentTemplate("397017167949312007", "Pet Pilot", "pet_pilot", "Pet pilots a fighter jet", True, False, example_media_hint="pet photo"),
    VideoAgentTemplate("394176968202485769", "Miniature Set Ad", "miniature_set_ad", "Miniature figure crafting for a product", True, False, example_media_hint="product photo"),
    VideoAgentTemplate("393876118804459526", "Male Model Try-On Ad", "male_tryon_ad", "Male model try-on from clothing image", True, False, example_media_hint="clothing flat lay"),
    VideoAgentTemplate("393866076583718914", "Female Model Try-On Ad", "female_tryon_ad", "Female model try-on from clothing image", True, False, example_media_hint="clothing flat lay"),
    VideoAgentTemplate("394875727173492739", "Art Fonts", "art_fonts", "Decorative text from word + element", False, True, "OCEAN waves", None),
    VideoAgentTemplate("394220989629177861", "Drinkfall", "drinkfall", "Beverage waterfall product video", True, False, example_media_hint="beverage product"),
    VideoAgentTemplate("393853165953970178", "E-commerce Display Ad", "ecommerce_display_ad", "Minimalist product display video", False, True, "wireless earbuds, matte black", None),
    VideoAgentTemplate("401431836934868999", "3D character product presentation", "3d_character_product", "3D character explains product", True, True, "explain battery life and comfort", "product photo"),
)

_VIDEO_AGENT_BY_ID = {t.template_id: t for t in VIDEO_AGENT_TEMPLATES}
_VIDEO_AGENT_BY_SLUG = {t.slug: t for t in VIDEO_AGENT_TEMPLATES}

# Rich augmentation templates. All slots in PROMPT_VARIABLES are filled with
# sensible defaults when omitted — operators only pass scene/style/mood they care about.
_PROMPT_TEMPLATE_REGISTRY: dict[MediaPromptKind, tuple[PromptTemplateMeta, ...]] = {
    "image": (
        PromptTemplateMeta("default", "General high-quality image", "Create a high-quality image. Scene: {scene}. Subject: {subject}. Style: {style}. Mood: {mood}. Lighting: {lighting}. Details: {user_request}."),
        PromptTemplateMeta("portrait", "Professional portrait", "Professional portrait photograph. Subject: {subject}. Scene: {scene}. Style: {style}. Mood: {mood}. Lighting: {lighting}, shallow depth of field. {user_request}."),
        PromptTemplateMeta("product", "E-commerce product shot", "E-commerce product photography. Subject: {subject}. Scene: {scene}. Style: clean {style}. Lighting: studio {lighting}. {user_request}."),
        PromptTemplateMeta("illustration", "Digital illustration", "Digital illustration. Scene: {scene}. Subject: {subject}. Art style: {style}. Mood: {mood}. {user_request}."),
        PromptTemplateMeta("cinematic", "Cinematic still frame", "Cinematic film still. Scene: {scene}. Subject: {subject}. Style: {style}. Camera: {camera}. Mood: {mood}. Lighting: {lighting}. {user_request}."),
        PromptTemplateMeta("anime", "Anime / manga style", "Anime illustration. Scene: {scene}. Subject: {subject}. Style: {style}. Mood: {mood}. {user_request}."),
        PromptTemplateMeta("landscape", "Landscape / environment", "Landscape photography. Scene: {scene}. Style: {style}. Mood: {mood}. Lighting: {lighting}. Camera: {camera}. {user_request}."),
        PromptTemplateMeta("architectural", "Architecture / interior", "Architectural photography. Scene: {scene}. Style: {style}. Lighting: {lighting}. Camera: {camera}. {user_request}."),
    ),
    "image_i2i": (
        PromptTemplateMeta("default", "Transform reference while preserving subject", "Image-to-image. Preserve subject identity from reference. Scene: {scene}. Style: {style}. Mood: {mood}. Changes: {user_request}."),
        PromptTemplateMeta("style_transfer", "Apply art style to reference", "Apply art style to reference portrait. Target style: {style}. Scene: {scene}. Mood: {mood}. {user_request}."),
        PromptTemplateMeta("wardrobe", "Change outfit/appearance", "Modify wardrobe/appearance of reference subject. Scene: {scene}. Style: {style}. New look: {user_request}."),
        PromptTemplateMeta("background", "Replace background", "Keep subject, replace background. New scene: {scene}. Style: {style}. Lighting: {lighting}. {user_request}."),
    ),
    "video": (
        PromptTemplateMeta("default", "Cinematic text-to-video", "Cinematic video. Scene: {scene}. Subject: {subject}. Style: {style}. Camera: {camera}. Mood: {mood}. Action: {user_request}."),
        PromptTemplateMeta("commercial", "Product commercial", "Short commercial. Product/scene: {scene}. Style: {style}. Camera: {camera}. Mood: {mood}. {user_request}."),
        PromptTemplateMeta("nature", "Nature documentary", "Nature documentary clip. Scene: {scene}. Style: realistic {style}. Camera: {camera}. Mood: {mood}. {user_request}."),
        PromptTemplateMeta("action", "Dynamic action", "Dynamic action sequence. Scene: {scene}. Subject: {subject}. Camera: {camera}. Style: {style}. {user_request}."),
        PromptTemplateMeta("timelapse", "Timelapse / hyperlapse", "Timelapse video. Scene: {scene}. Style: {style}. Camera: {camera}. Mood: {mood}. {user_request}."),
        PromptTemplateMeta("dialogue", "Character moment", "Character moment. Scene: {scene}. Subject: {subject}. Mood: {mood}. Camera: {camera}. {user_request}."),
    ),
    "video_i2v": (
        PromptTemplateMeta("default", "Natural motion from source frame", "Animate source image. Scene: {scene}. Style: {style}. Camera: {camera}. Motion: {user_request}. Preserve visual consistency."),
        PromptTemplateMeta("subtle", "Subtle ambient motion", "Subtle ambient animation. Scene: {scene}. Mood: {mood}. Gentle motion: {user_request}. Preserve composition."),
        PromptTemplateMeta("dynamic", "Expressive motion + camera", "Dynamic evolution from source. Scene: {scene}. Camera: [Push in] {camera}. Style: {style}. {user_request}."),
        PromptTemplateMeta("portrait_live", "Portrait comes alive", "Portrait animation. Subject: {subject}. Mood: {mood}. Natural expression/motion: {user_request}."),
    ),
    "video_s2v": (
        PromptTemplateMeta("default", "Subject-consistent character video", "Character video with consistent face. Subject: {subject}. Scene: {scene}. Style: {style}. Action: {user_request}."),
        PromptTemplateMeta("talking_head", "Talking head / presenter", "Talking-head video. Subject: {subject}. Scene: {scene}. Delivery: {delivery}. {user_request}."),
        PromptTemplateMeta("reaction", "Expressive reaction", "Expressive character reaction. Subject: {subject}. Mood: {mood}. Scene: {scene}. {user_request}."),
    ),
    "video_fl2v": (
        PromptTemplateMeta("default", "Morph between start and end frames", "Interpolate from first to last frame. Scene: {scene}. Style: {style}. Transition story: {user_request}."),
        PromptTemplateMeta("growth", "Transformation arc", "Visual transformation arc. Scene: {scene}. Mood: {mood}. Narrative: {user_request}."),
        PromptTemplateMeta("morph", "Creative morph", "Creative morph between frames. Style: {style}. Scene: {scene}. {user_request}."),
    ),
    "video_template": (
        PromptTemplateMeta("default", "Passthrough for template slots", "{user_request}"),
    ),
    "music": (
        PromptTemplateMeta("default", "General original track", "Original music. Genre: {genre}. Mood: {mood}. Tempo: {tempo}. Instrumentation: {instrumentation}. Concept: {user_request}."),
        PromptTemplateMeta("lofi", "Lo-fi study beat", "Lo-fi beat. Mood: {mood}. Tempo: {tempo}. Texture: warm vinyl. Scene vibe: {scene}. {user_request}."),
        PromptTemplateMeta("cinematic", "Cinematic score", "Cinematic score. Mood: {mood}. Scene: {scene}. Instrumentation: {instrumentation}. Arc: {user_request}."),
        PromptTemplateMeta("jingle", "Branded jingle", "Short jingle. Genre: {genre}. Mood: upbeat {mood}. Hook concept: {user_request}."),
        PromptTemplateMeta("ambient", "Ambient soundscape", "Ambient soundscape. Scene: {scene}. Mood: {mood}. Style: {style}. {user_request}."),
        PromptTemplateMeta("electronic", "Electronic dance", "Electronic track. Genre: {genre}. Tempo: {tempo}. Mood: {mood}. {user_request}."),
        PromptTemplateMeta("acoustic", "Acoustic singer-songwriter", "Acoustic song. Mood: {mood}. Scene: {scene}. Instrumentation: {instrumentation}. Theme: {user_request}."),
    ),
    "voice": (
        PromptTemplateMeta("default", "Natural conversational speech", "Natural speech. Delivery: {delivery}. Mood: {mood}. Voice character: {subject}. Text intent: {user_request}."),
        PromptTemplateMeta("narration", "Documentary narration", "Documentary narration. Delivery: {delivery}. Mood: {mood}. Pacing: steady. {user_request}."),
        PromptTemplateMeta("character", "Character performance", "Character voice. Subject: {subject}. Mood: {mood}. Delivery: {delivery}. {user_request}."),
        PromptTemplateMeta("commercial", "Ad voiceover", "Commercial VO. Delivery: {delivery}. Mood: {mood}. Product/scene: {scene}. {user_request}."),
        PromptTemplateMeta("audiobook", "Audiobook reading", "Audiobook reading. Delivery: warm {delivery}. Mood: {mood}. {user_request}."),
    ),
}

# Back-compat flat dict used in tests
PROMPT_TEMPLATES: dict[MediaPromptKind, dict[str, str]] = {
    kind: {meta.slug: meta.template for meta in metas}
    for kind, metas in _PROMPT_TEMPLATE_REGISTRY.items()
}

_DEFAULTS: dict[str, str] = {
    "scene": "neutral environment",
    "style": "realistic, polished",
    "subject": "main subject",
    "mood": "balanced",
    "lighting": "natural soft light",
    "camera": "steady medium shot",
    "genre": "versatile",
    "tempo": "moderate",
    "instrumentation": "appropriate to genre",
    "delivery": "clear and expressive",
}


def _normalize_template_key(kind: MediaPromptKind, template_key: str | None) -> str:
    family = _PROMPT_TEMPLATE_REGISTRY.get(kind, ())
    slugs = {m.slug for m in family}
    key = (template_key or _DEFAULT_TEMPLATE_KEY).strip().lower() or _DEFAULT_TEMPLATE_KEY
    return key if key in slugs else _DEFAULT_TEMPLATE_KEY


def _build_format_context(user_request: str, vars: MediaPromptVars | None) -> dict[str, str]:
    v = vars or MediaPromptVars()
    ctx = dict(_DEFAULTS)
    ctx["user_request"] = user_request.strip()
    ctx["subject"] = (v.subject or user_request).strip()
    for name in PROMPT_VARIABLES:
        if name in ("user_request", "subject"):
            continue
        val = getattr(v, name, None)
        if isinstance(val, str) and val.strip():
            ctx[name] = val.strip()
    return ctx


def augment_prompt(
    kind: MediaPromptKind,
    user_request: str,
    *,
    template_key: str | None = None,
    vars: MediaPromptVars | None = None,
) -> tuple[str, str, dict[str, str]]:
    """Augment a short user request into a provider-ready prompt.

    Args:
        kind (MediaPromptKind): Media family.
        user_request (str): Short operator intent.
        template_key (str | None, optional): Template slug. Defaults to ``default``.
        vars (MediaPromptVars | None, optional): Structured scene/style/subject variables.

    Returns:
        tuple[str, str, dict[str, str]]: ``(template_key, augmented_prompt, format_context)``.

    Raises:
        ValueError: When ``user_request`` is empty.

    Examples:
        >>> k, p, c = augment_prompt("image", "fox", vars=MediaPromptVars(scene="forest", style="watercolor"))
        >>> "forest" in p and "fox" in p
        True
    """
    text = user_request.strip()
    if not text:
        raise ValueError("user_request must be non-empty")
    resolved_key = _normalize_template_key(kind, template_key)
    metas = {m.slug: m for m in _PROMPT_TEMPLATE_REGISTRY[kind]}
    pattern = metas[resolved_key].template
    ctx = _build_format_context(text, vars)
    return resolved_key, pattern.format(**ctx), ctx


def list_prompt_templates(kind: MediaPromptKind | None = None) -> list[dict[str, object]]:
    """Return augmentation template catalog for agent discovery.

    Args:
        kind (MediaPromptKind | None, optional): Filter to one kind; omit for all.

    Returns:
        list[dict[str, object]]: Template metadata entries.

    Examples:
        >>> any(t["slug"] == "lofi" for t in list_prompt_templates("music"))
        True
    """
    kinds = (kind,) if kind else tuple(_PROMPT_TEMPLATE_REGISTRY.keys())
    out: list[dict[str, object]] = []
    for k in kinds:
        for meta in _PROMPT_TEMPLATE_REGISTRY[k]:
            out.append({
                "kind": k,
                "slug": meta.slug,
                "description": meta.description,
                "variables": list(PROMPT_VARIABLES),
                "template_preview": meta.template[:120] + ("…" if len(meta.template) > 120 else ""),
            })
    return out


def resolve_video_agent_template(ref: str) -> VideoAgentTemplate:
    key = ref.strip()
    if not key:
        raise ValueError("video agent template ref must be non-empty")
    if key in _VIDEO_AGENT_BY_ID:
        return _VIDEO_AGENT_BY_ID[key]
    slug = key.lower().replace(" ", "_").replace("-", "_")
    if slug in _VIDEO_AGENT_BY_SLUG:
        return _VIDEO_AGENT_BY_SLUG[slug]
    raise ValueError(f"unknown video agent template: {ref!r} — see VIDEO_AGENT_TEMPLATES")


def list_video_agent_templates() -> list[dict[str, object]]:
    return [
        {
            "template_id": t.template_id,
            "slug": t.slug,
            "name": t.name,
            "description": t.description,
            "media_inputs_required": t.media_inputs_required,
            "text_inputs_required": t.text_inputs_required,
            "example_text": t.example_text,
            "example_media_hint": t.example_media_hint,
        }
        for t in VIDEO_AGENT_TEMPLATES
    ]


def build_media_trace(
    *,
    kind: str,
    user_request: str,
    augmented_prompt: str,
    template_key: str,
    api_model: str | None = None,
    variables: dict[str, str] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, object]:
    trace: dict[str, object] = {
        "user_request": user_request,
        "template_key": template_key,
        "augmented_prompt": augmented_prompt,
    }
    if variables:
        trace["variables"] = variables
    if api_model:
        trace["api_model"] = api_model
    if extra:
        trace.update(extra)
    return trace


__all__ = [
    "MediaPromptKind",
    "MediaPromptVars",
    "PROMPT_TEMPLATES",
    "PROMPT_VARIABLES",
    "VIDEO_AGENT_TEMPLATES",
    "VideoAgentTemplate",
    "augment_prompt",
    "build_media_trace",
    "list_prompt_templates",
    "list_video_agent_templates",
    "resolve_video_agent_template",
]
