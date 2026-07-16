"""Prompt templates and augmentation for the ``media_generator`` specialist.

Module: sevn.agent.subagents.media_prompts
Depends: dataclasses, typing

Exports:
    MediaPromptKind — supported augmentation families.
    VideoAgentTemplate — one MiniMax Video Agent template entry.
    VIDEO_AGENT_TEMPLATES — official template catalog (IDs from MiniMax docs).
    PROMPT_TEMPLATES — per-kind prompt augmentation templates.
    augment_prompt — merge user request into a template.
    resolve_video_agent_template — lookup by id or slug.
    build_media_trace — trace metadata for worker results.

Examples:
    >>> from sevn.agent.subagents.media_prompts import augment_prompt
    >>> augment_prompt("image", "a fox in autumn", template_key="default")
    'Create a high-quality image: a fox in autumn. Professional composition, sharp details.'
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

MediaPromptKind = Literal["image", "video", "video_i2v", "video_template", "music", "voice"]

_DEFAULT_TEMPLATE_KEY = "default"


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


# Official MiniMax Video Agent templates (IDs from docs/faq/video-agent-templates).
VIDEO_AGENT_TEMPLATES: tuple[VideoAgentTemplate, ...] = (
    VideoAgentTemplate("392747428568649728", "Diving", "diving", "Subject completes a perfect dive", True, False),
    VideoAgentTemplate(
        "393769180141805569",
        "Run for Life",
        "run_for_life",
        "Pet survival video in the wilderness",
        True,
        True,
        example_text="Lion",
    ),
    VideoAgentTemplate("397087679467597833", "Transformers", "transformers", "Car transforms into mecha", True, False),
    VideoAgentTemplate(
        "393881433990066176",
        "Still rings routine",
        "still_rings",
        "Subject performs still rings routine",
        True,
        False,
    ),
    VideoAgentTemplate("393498001241890824", "Weightlifting", "weightlifting", "Pet performs weightlifting", True, False),
    VideoAgentTemplate("393488336655310850", "Climbing", "climbing", "Subject completes sport climbing", True, False),
    VideoAgentTemplate(
        "394514820878671878",
        "Anime Life Sim",
        "anime_life_sim",
        "Casual anime-style gameplay video from scene description",
        False,
        True,
    ),
    VideoAgentTemplate(
        "393879757702918151",
        "McDonald's Delivery Pet",
        "mcdonalds_delivery_pet",
        "Pet delivers McDonald's",
        True,
        False,
    ),
    VideoAgentTemplate("397017167949312007", "Pet Pilot", "pet_pilot", "Pet pilots a fighter jet", True, False),
    VideoAgentTemplate(
        "394176968202485769",
        "Miniature Set Ad",
        "miniature_set_ad",
        "Miniature figure crafting process for a product",
        True,
        False,
    ),
    VideoAgentTemplate(
        "393876118804459526",
        "Male Model Try-On Ad",
        "male_tryon_ad",
        "Male model try-on advertisement from clothing image",
        True,
        False,
    ),
    VideoAgentTemplate(
        "393866076583718914",
        "Female Model Try-On Ad",
        "female_tryon_ad",
        "Female model try-on advertisement from clothing image",
        True,
        False,
    ),
    VideoAgentTemplate(
        "394875727173492739",
        "Art Fonts",
        "art_fonts",
        "Artistic decorative text from word + element",
        False,
        True,
    ),
    VideoAgentTemplate("394220989629177861", "Drinkfall", "drinkfall", "Beverage waterfall product video", True, False),
    VideoAgentTemplate(
        "393853165953970178",
        "E-commerce Display Ad",
        "ecommerce_display_ad",
        "Minimalist e-commerce display video from product description",
        False,
        True,
    ),
    VideoAgentTemplate(
        "401431836934868999",
        "3D character product presentation",
        "3d_character_product",
        "3D character explains product from image + description",
        True,
        True,
    ),
)

_VIDEO_AGENT_BY_ID: dict[str, VideoAgentTemplate] = {t.template_id: t for t in VIDEO_AGENT_TEMPLATES}
_VIDEO_AGENT_BY_SLUG: dict[str, VideoAgentTemplate] = {t.slug: t for t in VIDEO_AGENT_TEMPLATES}

# Per-kind prompt augmentation templates. ``{user_request}`` is replaced with the
# operator's short intent; the agent does not need to write a full provider prompt.
PROMPT_TEMPLATES: dict[MediaPromptKind, dict[str, str]] = {
    "image": {
        "default": (
            "Create a high-quality image: {user_request}. "
            "Professional composition, sharp details, coherent lighting."
        ),
        "portrait": (
            "Professional portrait photograph: {user_request}. "
            "Natural lighting, shallow depth of field, flattering composition."
        ),
        "product": (
            "E-commerce product photography: {user_request}. "
            "Clean background, studio lighting, crisp product focus."
        ),
        "illustration": (
            "Digital illustration: {user_request}. "
            "Consistent art style, vivid colors, polished finish."
        ),
    },
    "video": {
        "default": (
            "Cinematic video scene: {user_request}. "
            "Smooth natural motion, coherent lighting, stable composition."
        ),
        "commercial": (
            "Short commercial video: {user_request}. "
            "Polished camera work, product-focused framing, professional pacing."
        ),
        "nature": (
            "Nature documentary clip: {user_request}. "
            "Realistic motion, ambient atmosphere, steady camera."
        ),
    },
    "video_i2v": {
        "default": (
            "Animate this image with natural motion: {user_request}. "
            "Maintain visual consistency with the source frame."
        ),
        "subtle": (
            "Subtle ambient animation from the source image: {user_request}. "
            "Gentle movement, preserve original composition."
        ),
        "dynamic": (
            "Dynamic scene evolution from the source image: {user_request}. "
            "[Push in] smooth camera movement, expressive subject motion."
        ),
    },
    "video_template": {
        "default": "{user_request}",
    },
    "music": {
        "default": (
            "Original music track: {user_request}. "
            "Clear structure, balanced mix, genre-appropriate instrumentation."
        ),
        "lofi": (
            "Lo-fi study beat: {user_request}. "
            "Warm vinyl texture, relaxed groove, minimal arrangement."
        ),
        "cinematic": (
            "Cinematic score: {user_request}. "
            "Emotional arc, orchestral or hybrid textures, film-ready dynamics."
        ),
        "jingle": (
            "Short branded jingle: {user_request}. "
            "Memorable hook, upbeat energy, polished production."
        ),
    },
    "voice": {
        "default": (
            "Natural, expressive speech: {user_request}. "
            "Clear articulation, appropriate pacing, conversational tone."
        ),
        "narration": (
            "Professional narration: {user_request}. "
            "Warm authoritative tone, steady pacing, broadcast quality."
        ),
        "character": (
            "Character voice performance: {user_request}. "
            "Distinct personality, expressive delivery, consistent timbre."
        ),
    },
}


def _normalize_template_key(kind: MediaPromptKind, template_key: str | None) -> str:
    """Return a valid template key for ``kind``, falling back to ``default``.

    Args:
        kind (MediaPromptKind): Media family.
        template_key (str | None): Requested template slug.

    Returns:
        str: Resolved template key.

    Examples:
        >>> _normalize_template_key("image", None)
        'default'
    """
    key = (template_key or _DEFAULT_TEMPLATE_KEY).strip().lower() or _DEFAULT_TEMPLATE_KEY
    family = PROMPT_TEMPLATES.get(kind, {})
    if key in family:
        return key
    return _DEFAULT_TEMPLATE_KEY


def augment_prompt(
    kind: MediaPromptKind,
    user_request: str,
    *,
    template_key: str | None = None,
) -> tuple[str, str]:
    """Augment a short user request into a provider-ready prompt.

    Args:
        kind (MediaPromptKind): Media family.
        user_request (str): Short operator intent (not a full provider prompt).
        template_key (str | None, optional): Template slug within ``kind``. Defaults to
            ``default``.

    Returns:
        tuple[str, str]: ``(resolved_template_key, augmented_prompt)``.

    Raises:
        ValueError: When ``user_request`` is empty.

    Examples:
        >>> augment_prompt("music", "rainy night café", template_key="lofi")[1]
        'Lo-fi study beat: rainy night café. Warm vinyl texture, relaxed groove, minimal arrangement.'
    """
    text = user_request.strip()
    if not text:
        msg = "user_request must be non-empty"
        raise ValueError(msg)
    resolved_key = _normalize_template_key(kind, template_key)
    pattern = PROMPT_TEMPLATES[kind][resolved_key]
    return resolved_key, pattern.format(user_request=text)


def resolve_video_agent_template(ref: str) -> VideoAgentTemplate:
    """Resolve a Video Agent template by numeric id or slug.

    Args:
        ref (str): Template id (e.g. ``393769180141805569``) or slug (e.g. ``run_for_life``).

    Returns:
        VideoAgentTemplate: Matching catalog entry.

    Raises:
        ValueError: When ``ref`` does not match any known template.

    Examples:
        >>> resolve_video_agent_template("diving").name
        'Diving'
    """
    key = ref.strip()
    if not key:
        msg = "video agent template ref must be non-empty"
        raise ValueError(msg)
    if key in _VIDEO_AGENT_BY_ID:
        return _VIDEO_AGENT_BY_ID[key]
    slug = key.lower().replace(" ", "_").replace("-", "_")
    if slug in _VIDEO_AGENT_BY_SLUG:
        return _VIDEO_AGENT_BY_SLUG[slug]
    msg = f"unknown video agent template: {ref!r} — see VIDEO_AGENT_TEMPLATES"
    raise ValueError(msg)


def list_video_agent_templates() -> list[dict[str, object]]:
    """Return the Video Agent catalog for skill/agent discovery.

    Returns:
        list[dict[str, object]]: Serializable template entries.

    Examples:
        >>> any(t["slug"] == "diving" for t in list_video_agent_templates())
        True
    """
    return [
        {
            "template_id": t.template_id,
            "slug": t.slug,
            "name": t.name,
            "description": t.description,
            "media_inputs_required": t.media_inputs_required,
            "text_inputs_required": t.text_inputs_required,
            "example_text": t.example_text,
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
    extra: dict[str, Any] | None = None,
) -> dict[str, object]:
    """Build trace metadata returned alongside generated artifacts.

    Args:
        kind (str): Media kind executed.
        user_request (str): Original short user intent.
        augmented_prompt (str): Provider prompt after template augmentation.
        template_key (str): Resolved augmentation template slug.
        api_model (str | None, optional): Upstream model id when applicable.
        extra (dict[str, Any] | None, optional): Additional trace fields.

    Returns:
        dict[str, object]: Trace block for worker results.

    Examples:
        >>> build_media_trace(kind="image", user_request="fox", augmented_prompt="Create…", template_key="default")["user_request"]
        'fox'
    """
    trace: dict[str, object] = {
        "user_request": user_request,
        "template_key": template_key,
        "augmented_prompt": augmented_prompt,
    }
    if api_model:
        trace["api_model"] = api_model
    if extra:
        trace.update(extra)
    return trace


__all__ = [
    "MediaPromptKind",
    "PROMPT_TEMPLATES",
    "VIDEO_AGENT_TEMPLATES",
    "VideoAgentTemplate",
    "augment_prompt",
    "build_media_trace",
    "list_video_agent_templates",
    "resolve_video_agent_template",
]
