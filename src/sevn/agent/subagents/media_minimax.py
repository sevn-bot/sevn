"""MiniMax media REST adapter for the ``media_generator`` specialist (W8.2).

Isolates image / video / music / voice endpoint knowledge so provider drift stays local.

Module: sevn.agent.subagents.media_minimax
Depends: asyncio, base64, httpx, loguru

Exports:
    MiniMaxMediaError — typed failure from MiniMax media APIs.
    generate_image_bytes — POST ``/v1/image_generation`` → JPEG bytes.
    generate_video_bytes — async video task poll + download → MP4 bytes.
    generate_video_from_image_bytes — image-to-video with optional text prompt.
    generate_video_template_bytes — Video Agent template generation → MP4 bytes.
    clone_voice_bytes — upload + clone voice; optional preview TTS → MP3 bytes.
    synthesize_speech_bytes — T2A with cloned or system voice → MP3 bytes.
    upload_file_bytes — multipart upload for voice_clone / prompt_audio.
    generate_music_bytes — POST ``/v1/music_generation`` → MP3 bytes.

Examples:
    >>> from sevn.agent.subagents.media_minimax import DEFAULT_IMAGE_MODEL
    >>> DEFAULT_IMAGE_MODEL
    'image-01'
"""

from __future__ import annotations

import asyncio
import base64
import mimetypes
from pathlib import Path
from typing import Any

import httpx

MINIMAX_MEDIA_BASE_URL = "https://api.minimax.io/v1"
DEFAULT_IMAGE_MODEL = "image-01"
DEFAULT_VIDEO_MODEL = "MiniMax-Hailuo-2.3"
DEFAULT_VIDEO_I2V_MODEL = "MiniMax-Hailuo-2.3"
DEFAULT_VIDEO_S2V_MODEL = "S2V-01"
DEFAULT_VIDEO_FL2V_MODEL = "MiniMax-Hailuo-02"
DEFAULT_MUSIC_MODEL = "music-2.6"
DEFAULT_SPEECH_MODEL = "speech-2.8-hd"

_DEFAULT_HTTP_TIMEOUT_S = 120.0
_DEFAULT_VIDEO_POLL_INTERVAL_S = 5.0
_DEFAULT_VIDEO_MAX_POLLS = 120


class MiniMaxMediaError(RuntimeError):
    """Raised when a MiniMax media API call fails or returns an unexpected shape."""


def _auth_headers(api_key: str) -> dict[str, str]:
    """Build MiniMax bearer auth headers.

    Args:
        api_key (str): Resolved MiniMax API key.

    Returns:
        dict[str, str]: Request headers.

    Examples:
        >>> _auth_headers("sk-test")["Authorization"]
        'Bearer sk-test'
    """
    return {
        "Authorization": f"Bearer {api_key.strip()}",
        "Content-Type": "application/json",
    }


def _raise_for_status_payload(response: httpx.Response, *, context: str) -> dict[str, Any]:
    """Parse JSON and raise :class:`MiniMaxMediaError` on HTTP or API errors.

    Args:
        response (httpx.Response): Upstream HTTP response.
        context (str): Short label for error messages.

    Returns:
        dict[str, Any]: Parsed JSON object.

    Raises:
        MiniMaxMediaError: On non-2xx HTTP or ``base_resp.status_code != 0``.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(_raise_for_status_payload)
        True
    """
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        msg = f"{context}: HTTP {exc.response.status_code}"
        raise MiniMaxMediaError(msg) from exc
    payload = response.json()
    if not isinstance(payload, dict):
        msg = f"{context}: expected JSON object"
        raise MiniMaxMediaError(msg)
    base = payload.get("base_resp")
    if isinstance(base, dict):
        code = base.get("status_code")
        if code not in (None, 0, "0"):
            status_msg = str(base.get("status_msg") or base.get("status_message") or code)
            raise MiniMaxMediaError(f"{context}: {status_msg}")
    return payload


def _image_to_data_url(path: Path) -> str:
    """Encode a local image file as a MiniMax-compatible data URL.

    Args:
        path (Path): Local image path.

    Returns:
        str: ``data:image/…;base64,…`` string.

    Raises:
        MiniMaxMediaError: When the file is missing or unreadable.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(_image_to_data_url)
        True
    """
    if not path.is_file():
        raise MiniMaxMediaError(f"image not found: {path}")
    mime, _ = mimetypes.guess_type(str(path))
    mime = mime or "image/jpeg"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _resolve_image_ref(image_ref: str, *, content_root: Path | None = None) -> str:
    """Resolve an image reference to a URL or data URL for MiniMax APIs.

    Args:
        image_ref (str): Public URL, data URL, or workspace-relative/local path.
        content_root (Path | None, optional): Workspace root for relative paths.

    Returns:
        str: URL or data URL accepted by MiniMax.

    Raises:
        MiniMaxMediaError: When a local path cannot be resolved.

    Examples:
        >>> _resolve_image_ref("https://example.com/a.jpg").startswith("https://")
        True
    """
    ref = image_ref.strip()
    if not ref:
        raise MiniMaxMediaError("image reference must be non-empty")
    if ref.startswith(("http://", "https://", "data:")):
        return ref
    path = Path(ref).expanduser()
    if not path.is_absolute() and content_root is not None:
        candidate = (content_root / ref).resolve()
        if candidate.is_file():
            path = candidate
    if path.is_file():
        return _image_to_data_url(path)
    raise MiniMaxMediaError(f"image not found: {image_ref}")


async def upload_file_bytes(
    api_key: str,
    data: bytes,
    *,
    purpose: str,
    filename: str,
    client: httpx.AsyncClient | None = None,
) -> int:
    """Upload bytes via ``/v1/files/upload`` (voice_clone, prompt_audio, etc.).

    Args:
        api_key (str): Resolved MiniMax API key.
        data (bytes): File bytes.
        purpose (str): MiniMax upload purpose (``voice_clone`` or ``prompt_audio``).
        filename (str): Original filename with extension.
        client (httpx.AsyncClient | None, optional): Injectable client for tests.

    Returns:
        int: ``file_id`` from the upload response.

    Raises:
        MiniMaxMediaError: On transport or API failure.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(upload_file_bytes)
        True
    """
    owns = client is None
    http = client or httpx.AsyncClient(timeout=_DEFAULT_HTTP_TIMEOUT_S)
    headers = {"Authorization": f"Bearer {api_key.strip()}"}
    files = {"file": (filename, data)}
    form = {"purpose": purpose}
    try:
        response = await http.post(
            f"{MINIMAX_MEDIA_BASE_URL}/files/upload",
            headers=headers,
            data=form,
            files=files,
        )
        payload = _raise_for_status_payload(response, context="files_upload")
    finally:
        if owns:
            await http.aclose()
    file_obj = payload.get("file")
    if not isinstance(file_obj, dict):
        raise MiniMaxMediaError("files_upload: missing file object")
    file_id = file_obj.get("file_id")
    if not isinstance(file_id, int):
        raise MiniMaxMediaError("files_upload: missing file_id")
    return file_id


async def generate_image_bytes(
    api_key: str,
    prompt: str,
    *,
    model: str = DEFAULT_IMAGE_MODEL,
    aspect_ratio: str = "1:1",
    client: httpx.AsyncClient | None = None,
) -> bytes:
    """Generate one image from text via MiniMax ``/v1/image_generation``.

    Args:
        api_key (str): Resolved MiniMax API key.
        prompt (str): Text prompt (typically template-augmented).
        model (str, optional): MiniMax image model id. Defaults to ``image-01``.
        aspect_ratio (str, optional): Aspect ratio string. Defaults to ``1:1``.
        client (httpx.AsyncClient | None, optional): Injectable client for tests.

    Returns:
        bytes: Decoded JPEG bytes (first image when multiple are returned).

    Raises:
        MiniMaxMediaError: On transport or API failure.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(generate_image_bytes)
        True
    """
    body = {
        "model": model,
        "prompt": prompt.strip(),
        "aspect_ratio": aspect_ratio,
        "response_format": "base64",
    }
    owns = client is None
    http = client or httpx.AsyncClient(timeout=_DEFAULT_HTTP_TIMEOUT_S)
    try:
        response = await http.post(
            f"{MINIMAX_MEDIA_BASE_URL}/image_generation",
            headers=_auth_headers(api_key),
            json=body,
        )
        payload = _raise_for_status_payload(response, context="image_generation")
    finally:
        if owns:
            await http.aclose()
    data = payload.get("data")
    if not isinstance(data, dict):
        raise MiniMaxMediaError("image_generation: missing data object")
    images = data.get("image_base64")
    if not isinstance(images, list) or not images:
        raise MiniMaxMediaError("image_generation: missing image_base64")
    first = images[0]
    if not isinstance(first, str):
        raise MiniMaxMediaError("image_generation: invalid image_base64 entry")
    return base64.b64decode(first.encode("ascii"))


async def generate_image_from_reference_bytes(
    api_key: str,
    prompt: str,
    reference_image: str,
    *,
    model: str = DEFAULT_IMAGE_MODEL,
    aspect_ratio: str = "1:1",
    content_root: Path | None = None,
    client: httpx.AsyncClient | None = None,
) -> bytes:
    """Generate image from reference portrait via image-to-image API.

    Args:
        api_key (str): Resolved MiniMax API key.
        prompt (str): Template-augmented transformation prompt.
        reference_image (str): Reference portrait URL or workspace path.
        model (str, optional): Image model. Defaults to ``image-01``.
        aspect_ratio (str, optional): Aspect ratio.
        content_root (Path | None, optional): Workspace root for relative paths.
        client (httpx.AsyncClient | None, optional): Injectable client for tests.

    Returns:
        bytes: Decoded JPEG bytes.

    Raises:
        MiniMaxMediaError: On transport or API failure.
    """
    body = {
        "model": model,
        "prompt": prompt.strip(),
        "aspect_ratio": aspect_ratio,
        "response_format": "base64",
        "subject_reference": [
            {
                "type": "character",
                "image_file": _resolve_image_ref(reference_image, content_root=content_root),
            },
        ],
    }
    owns = client is None
    http = client or httpx.AsyncClient(timeout=_DEFAULT_HTTP_TIMEOUT_S)
    try:
        response = await http.post(
            f"{MINIMAX_MEDIA_BASE_URL}/image_generation",
            headers=_auth_headers(api_key),
            json=body,
        )
        payload = _raise_for_status_payload(response, context="image_generation_i2i")
    finally:
        if owns:
            await http.aclose()
    data = payload.get("data")
    if not isinstance(data, dict):
        raise MiniMaxMediaError("image_generation_i2i: missing data object")
    images = data.get("image_base64")
    if not isinstance(images, list) or not images:
        raise MiniMaxMediaError("image_generation_i2i: missing image_base64")
    first = images[0]
    if not isinstance(first, str):
        raise MiniMaxMediaError("image_generation_i2i: invalid image_base64 entry")
    return base64.b64decode(first.encode("ascii"))


async def _create_and_download_video(
    http: httpx.AsyncClient,
    api_key: str,
    body: dict[str, Any],
    *,
    poll_interval_s: float,
    max_polls: int,
) -> bytes:
    """POST video_generation, poll, and download MP4 bytes."""
    response = await http.post(
        f"{MINIMAX_MEDIA_BASE_URL}/video_generation",
        headers=_auth_headers(api_key),
        json=body,
    )
    payload = _raise_for_status_payload(response, context="video_generation")
    task_id = payload.get("task_id")
    if not isinstance(task_id, str) or not task_id.strip():
        raise MiniMaxMediaError("video_generation: missing task_id")
    file_id = await _poll_video_file_id(
        http,
        api_key,
        task_id.strip(),
        poll_interval_s=poll_interval_s,
        max_polls=max_polls,
    )
    return await _download_minimax_file(http, api_key, file_id)


async def generate_video_subject_reference_bytes(
    api_key: str,
    prompt: str,
    subject_reference: str,
    *,
    model: str = DEFAULT_VIDEO_S2V_MODEL,
    content_root: Path | None = None,
    poll_interval_s: float = _DEFAULT_VIDEO_POLL_INTERVAL_S,
    max_polls: int = _DEFAULT_VIDEO_MAX_POLLS,
    client: httpx.AsyncClient | None = None,
) -> bytes:
    """Subject-reference video (face-consistent character clip)."""
    body: dict[str, Any] = {
        "model": model,
        "prompt": prompt.strip(),
        "subject_reference": [
            {
                "type": "character",
                "image": [_resolve_image_ref(subject_reference, content_root=content_root)],
            },
        ],
    }
    owns = client is None
    http = client or httpx.AsyncClient(timeout=_DEFAULT_HTTP_TIMEOUT_S)
    try:
        return await _create_and_download_video(
            http, api_key, body, poll_interval_s=poll_interval_s, max_polls=max_polls,
        )
    finally:
        if owns:
            await http.aclose()


async def generate_video_first_last_frame_bytes(
    api_key: str,
    prompt: str,
    *,
    first_frame_image: str,
    last_frame_image: str,
    model: str = DEFAULT_VIDEO_FL2V_MODEL,
    duration: int = 6,
    resolution: str = "1080P",
    content_root: Path | None = None,
    poll_interval_s: float = _DEFAULT_VIDEO_POLL_INTERVAL_S,
    max_polls: int = _DEFAULT_VIDEO_MAX_POLLS,
    client: httpx.AsyncClient | None = None,
) -> bytes:
    """First-and-last-frame video interpolation (MiniMax-Hailuo-02)."""
    body: dict[str, Any] = {
        "model": model,
        "prompt": prompt.strip(),
        "first_frame_image": _resolve_image_ref(first_frame_image, content_root=content_root),
        "last_frame_image": _resolve_image_ref(last_frame_image, content_root=content_root),
        "duration": duration,
        "resolution": resolution,
    }
    owns = client is None
    http = client or httpx.AsyncClient(timeout=_DEFAULT_HTTP_TIMEOUT_S)
    try:
        return await _create_and_download_video(
            http, api_key, body, poll_interval_s=poll_interval_s, max_polls=max_polls,
        )
    finally:
        if owns:
            await http.aclose()


async def _poll_video_file_id(
    http: httpx.AsyncClient,
    api_key: str,
    task_id: str,
    *,
    poll_interval_s: float,
    max_polls: int,
) -> str:
    """Poll ``/v1/query/video_generation`` until success or failure.

    Args:
        http (httpx.AsyncClient): Shared async client.
        api_key (str): Resolved MiniMax API key.
        task_id (str): Task id from the create call.
        poll_interval_s (float): Sleep between polls.
        max_polls (int): Maximum poll attempts.

    Returns:
        str: ``file_id`` on success.

    Raises:
        MiniMaxMediaError: On failure or timeout.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_poll_video_file_id)
        True
    """
    for _ in range(max_polls):
        response = await http.get(
            f"{MINIMAX_MEDIA_BASE_URL}/query/video_generation",
            headers=_auth_headers(api_key),
            params={"task_id": task_id},
        )
        payload = _raise_for_status_payload(response, context="query_video_generation")
        status = str(payload.get("status") or "").strip()
        if status == "Success":
            file_id = payload.get("file_id")
            if not isinstance(file_id, str) or not file_id.strip():
                raise MiniMaxMediaError("query_video_generation: missing file_id")
            return file_id.strip()
        if status == "Fail":
            detail = payload.get("error_message") or payload.get("base_resp")
            raise MiniMaxMediaError(f"video_generation failed: {detail!s}")
        await asyncio.sleep(poll_interval_s)
    raise MiniMaxMediaError("video_generation timed out waiting for completion")


async def _poll_video_template_url(
    http: httpx.AsyncClient,
    api_key: str,
    task_id: str,
    *,
    poll_interval_s: float,
    max_polls: int,
) -> str:
    """Poll ``/v1/query/video_template_generation`` until success or failure.

    Args:
        http (httpx.AsyncClient): Shared async client.
        api_key (str): Resolved MiniMax API key.
        task_id (str): Task id from the create call.
        poll_interval_s (float): Sleep between polls.
        max_polls (int): Maximum poll attempts.

    Returns:
        str: ``video_url`` on success.

    Raises:
        MiniMaxMediaError: On failure or timeout.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_poll_video_template_url)
        True
    """
    for _ in range(max_polls):
        response = await http.get(
            f"{MINIMAX_MEDIA_BASE_URL}/query/video_template_generation",
            headers=_auth_headers(api_key),
            params={"task_id": task_id},
        )
        payload = _raise_for_status_payload(response, context="query_video_template_generation")
        status = str(payload.get("status") or "").strip()
        if status == "Success":
            video_url = payload.get("video_url")
            if not isinstance(video_url, str) or not video_url.strip():
                raise MiniMaxMediaError("query_video_template_generation: missing video_url")
            return video_url.strip()
        if status == "Fail":
            detail = payload.get("base_resp")
            raise MiniMaxMediaError(f"video_template_generation failed: {detail!s}")
        await asyncio.sleep(poll_interval_s)
    raise MiniMaxMediaError("video_template_generation timed out waiting for completion")


async def _download_minimax_file(
    http: httpx.AsyncClient,
    api_key: str,
    file_id: str,
) -> bytes:
    """Resolve ``file_id`` to a download URL and fetch bytes.

    Args:
        http (httpx.AsyncClient): Shared async client.
        api_key (str): Resolved MiniMax API key.
        file_id (str): File id from a completed async task.

    Returns:
        bytes: Downloaded file bytes.

    Raises:
        MiniMaxMediaError: When retrieve or download fails.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_download_minimax_file)
        True
    """
    response = await http.get(
        f"{MINIMAX_MEDIA_BASE_URL}/files/retrieve",
        headers=_auth_headers(api_key),
        params={"file_id": file_id},
    )
    payload = _raise_for_status_payload(response, context="files_retrieve")
    file_obj = payload.get("file")
    if not isinstance(file_obj, dict):
        raise MiniMaxMediaError("files_retrieve: missing file object")
    download_url = file_obj.get("download_url")
    if not isinstance(download_url, str) or not download_url.strip():
        raise MiniMaxMediaError("files_retrieve: missing download_url")
    dl = await http.get(download_url.strip())
    dl.raise_for_status()
    return dl.content


async def _download_url(http: httpx.AsyncClient, url: str) -> bytes:
    """Download bytes from a public URL.

    Args:
        http (httpx.AsyncClient): Shared async client.
        url (str): Download URL.

    Returns:
        bytes: File bytes.

    Raises:
        MiniMaxMediaError: On HTTP failure.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_download_url)
        True
    """
    try:
        dl = await http.get(url.strip())
        dl.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise MiniMaxMediaError(f"download failed: HTTP {exc.response.status_code}") from exc
    return dl.content


async def generate_video_bytes(
    api_key: str,
    prompt: str,
    *,
    model: str = DEFAULT_VIDEO_MODEL,
    duration: int = 6,
    resolution: str = "720P",
    first_frame_image: str | None = None,
    content_root: Path | None = None,
    poll_interval_s: float = _DEFAULT_VIDEO_POLL_INTERVAL_S,
    max_polls: int = _DEFAULT_VIDEO_MAX_POLLS,
    client: httpx.AsyncClient | None = None,
) -> bytes:
    """Generate a video from text (optionally image-to-video) via MiniMax async APIs.

    Args:
        api_key (str): Resolved MiniMax API key.
        prompt (str): Text prompt (template-augmented).
        model (str, optional): Video model id. Defaults to ``MiniMax-Hailuo-2.3``.
        duration (int, optional): Clip duration seconds. Defaults to ``6``.
        resolution (str, optional): Output resolution label. Defaults to ``720P``.
        first_frame_image (str | None, optional): Image URL/path for image-to-video.
        content_root (Path | None, optional): Workspace root for relative image paths.
        poll_interval_s (float, optional): Poll interval. Defaults to ``5.0``.
        max_polls (int, optional): Max poll attempts. Defaults to ``120``.
        client (httpx.AsyncClient | None, optional): Injectable client for tests.

    Returns:
        bytes: MP4 file bytes.

    Raises:
        MiniMaxMediaError: On transport or API failure.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(generate_video_bytes)
        True
    """
    body: dict[str, Any] = {
        "model": model,
        "prompt": prompt.strip(),
        "duration": duration,
        "resolution": resolution,
    }
    if first_frame_image:
        body["first_frame_image"] = _resolve_image_ref(first_frame_image, content_root=content_root)
    owns = client is None
    http = client or httpx.AsyncClient(timeout=_DEFAULT_HTTP_TIMEOUT_S)
    try:
        return await _create_and_download_video(
            http,
            api_key,
            body,
            poll_interval_s=poll_interval_s,
            max_polls=max_polls,
        )
    finally:
        if owns:
            await http.aclose()


async def generate_video_from_image_bytes(
    api_key: str,
    prompt: str,
    first_frame_image: str,
    *,
    model: str = DEFAULT_VIDEO_I2V_MODEL,
    duration: int = 6,
    resolution: str = "1080P",
    content_root: Path | None = None,
    poll_interval_s: float = _DEFAULT_VIDEO_POLL_INTERVAL_S,
    max_polls: int = _DEFAULT_VIDEO_MAX_POLLS,
    client: httpx.AsyncClient | None = None,
) -> bytes:
    """Generate video from an image + text prompt (image-to-video).

    Args:
        api_key (str): Resolved MiniMax API key.
        prompt (str): Motion/scene description (template-augmented).
        first_frame_image (str): Image URL, data URL, or workspace-relative path.
        model (str, optional): I2V model. Defaults to ``MiniMax-Hailuo-2.3``.
        duration (int, optional): Clip duration. Defaults to ``6``.
        resolution (str, optional): Output resolution. Defaults to ``1080P``.
        content_root (Path | None, optional): Workspace root for relative paths.
        poll_interval_s (float, optional): Poll interval.
        max_polls (int, optional): Max poll attempts.
        client (httpx.AsyncClient | None, optional): Injectable client for tests.

    Returns:
        bytes: MP4 bytes.

    Raises:
        MiniMaxMediaError: On transport or API failure.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(generate_video_from_image_bytes)
        True
    """
    return await generate_video_bytes(
        api_key,
        prompt,
        model=model,
        duration=duration,
        resolution=resolution,
        first_frame_image=first_frame_image,
        content_root=content_root,
        poll_interval_s=poll_interval_s,
        max_polls=max_polls,
        client=client,
    )


async def generate_video_template_bytes(
    api_key: str,
    template_id: str,
    *,
    text_inputs: list[str] | None = None,
    media_inputs: list[str] | None = None,
    content_root: Path | None = None,
    poll_interval_s: float = _DEFAULT_VIDEO_POLL_INTERVAL_S,
    max_polls: int = _DEFAULT_VIDEO_MAX_POLLS,
    client: httpx.AsyncClient | None = None,
) -> bytes:
    """Generate a video via MiniMax Video Agent template API.

    Args:
        api_key (str): Resolved MiniMax API key.
        template_id (str): Official template id (see ``VIDEO_AGENT_TEMPLATES``).
        text_inputs (list[str] | None, optional): Text slots for the template.
        media_inputs (list[str] | None, optional): Image URLs/paths for media slots.
        content_root (Path | None, optional): Workspace root for relative image paths.
        poll_interval_s (float, optional): Poll interval.
        max_polls (int, optional): Max poll attempts.
        client (httpx.AsyncClient | None, optional): Injectable client for tests.

    Returns:
        bytes: MP4 bytes.

    Raises:
        MiniMaxMediaError: On transport or API failure.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(generate_video_template_bytes)
        True
    """
    body: dict[str, Any] = {"template_id": template_id.strip()}
    if text_inputs:
        body["text_inputs"] = [{"value": t.strip()} for t in text_inputs if t.strip()]
    if media_inputs:
        resolved = [
            _resolve_image_ref(ref, content_root=content_root) for ref in media_inputs if ref.strip()
        ]
        body["media_inputs"] = [{"value": v} for v in resolved]
    owns = client is None
    http = client or httpx.AsyncClient(timeout=_DEFAULT_HTTP_TIMEOUT_S)
    try:
        response = await http.post(
            f"{MINIMAX_MEDIA_BASE_URL}/video_template_generation",
            headers=_auth_headers(api_key),
            json=body,
        )
        payload = _raise_for_status_payload(response, context="video_template_generation")
        task_id = payload.get("task_id")
        if not isinstance(task_id, str) or not task_id.strip():
            raise MiniMaxMediaError("video_template_generation: missing task_id")
        video_url = await _poll_video_template_url(
            http,
            api_key,
            task_id.strip(),
            poll_interval_s=poll_interval_s,
            max_polls=max_polls,
        )
        return await _download_url(http, video_url)
    finally:
        if owns:
            await http.aclose()


async def synthesize_speech_bytes(
    api_key: str,
    text: str,
    *,
    voice_id: str,
    model: str = DEFAULT_SPEECH_MODEL,
    client: httpx.AsyncClient | None = None,
) -> bytes:
    """Synthesize speech via ``/v1/t2a_v2`` (cloned or system voice).

    Args:
        api_key (str): Resolved MiniMax API key.
        text (str): Text to speak (template-augmented).
        voice_id (str): MiniMax voice id (cloned or system).
        model (str, optional): T2A model. Defaults to ``speech-2.8-hd``.
        client (httpx.AsyncClient | None, optional): Injectable client for tests.

    Returns:
        bytes: MP3 bytes.

    Raises:
        MiniMaxMediaError: On transport or API failure.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(synthesize_speech_bytes)
        True
    """
    body = {
        "model": model,
        "text": text.strip(),
        "stream": False,
        "language_boost": "auto",
        "output_format": "hex",
        "voice_setting": {
            "voice_id": voice_id.strip(),
            "speed": 1,
            "vol": 1,
            "pitch": 0,
        },
        "audio_setting": {
            "sample_rate": 32000,
            "bitrate": 128000,
            "format": "mp3",
            "channel": 1,
        },
    }
    owns = client is None
    http = client or httpx.AsyncClient(timeout=_DEFAULT_HTTP_TIMEOUT_S)
    try:
        response = await http.post(
            f"{MINIMAX_MEDIA_BASE_URL}/t2a_v2",
            headers=_auth_headers(api_key),
            json=body,
        )
        payload = _raise_for_status_payload(response, context="t2a_v2")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise MiniMaxMediaError("t2a_v2: missing data object")
        audio_hex = data.get("audio")
        if not isinstance(audio_hex, str) or not audio_hex.strip():
            raise MiniMaxMediaError("t2a_v2: missing audio hex")
        return bytes.fromhex(audio_hex.strip())
    finally:
        if owns:
            await http.aclose()


async def clone_voice_bytes(
    api_key: str,
    source_audio: bytes,
    *,
    voice_id: str,
    source_filename: str = "voice_sample.mp3",
    preview_text: str | None = None,
    prompt_audio: bytes | None = None,
    prompt_text: str | None = None,
    prompt_filename: str = "prompt_sample.mp3",
    model: str = DEFAULT_SPEECH_MODEL,
    client: httpx.AsyncClient | None = None,
) -> tuple[str, bytes | None]:
    """Clone a voice and optionally synthesize a preview clip.

    Uploads source audio (10s–5min), calls ``/v1/voice_clone``, and when
    ``preview_text`` is set returns synthesized preview MP3 bytes.

    Args:
        api_key (str): Resolved MiniMax API key.
        source_audio (bytes): Source audio for cloning (mp3/m4a/wav).
        voice_id (str): Custom voice id (8–256 chars, starts with letter).
        source_filename (str, optional): Filename for upload. Defaults to ``voice_sample.mp3``.
        preview_text (str | None, optional): Text for preview synthesis after clone.
        prompt_audio (bytes | None, optional): Optional <8s prompt sample for quality.
        prompt_text (str | None, optional): Transcript of prompt audio.
        prompt_filename (str, optional): Filename for prompt upload.
        model (str, optional): T2A model for preview. Defaults to ``speech-2.8-hd``.
        client (httpx.AsyncClient | None, optional): Injectable client for tests.

    Returns:
        tuple[str, bytes | None]: ``(voice_id, preview_mp3_or_none)``.

    Raises:
        MiniMaxMediaError: On transport or API failure.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(clone_voice_bytes)
        True
    """
    owns = client is None
    http = client or httpx.AsyncClient(timeout=_DEFAULT_HTTP_TIMEOUT_S)
    try:
        file_id = await upload_file_bytes(
            api_key,
            source_audio,
            purpose="voice_clone",
            filename=source_filename,
            client=http,
        )
        body: dict[str, Any] = {
            "file_id": file_id,
            "voice_id": voice_id.strip(),
        }
        if preview_text and preview_text.strip():
            body["text"] = preview_text.strip()
            body["model"] = model
        if prompt_audio is not None:
            prompt_file_id = await upload_file_bytes(
                api_key,
                prompt_audio,
                purpose="prompt_audio",
                filename=prompt_filename,
                client=http,
            )
            if not prompt_text or not prompt_text.strip():
                raise MiniMaxMediaError("voice_clone: prompt_text required with prompt_audio")
            body["clone_prompt"] = {
                "prompt_audio": prompt_file_id,
                "prompt_text": prompt_text.strip(),
            }
        response = await http.post(
            f"{MINIMAX_MEDIA_BASE_URL}/voice_clone",
            headers=_auth_headers(api_key),
            json=body,
        )
        payload = _raise_for_status_payload(response, context="voice_clone")
        preview_bytes: bytes | None = None
        demo_url = payload.get("demo_audio")
        if isinstance(demo_url, str) and demo_url.strip():
            preview_bytes = await _download_url(http, demo_url.strip())
        elif preview_text and preview_text.strip():
            preview_bytes = await synthesize_speech_bytes(
                api_key,
                preview_text,
                voice_id=voice_id,
                model=model,
                client=http,
            )
        return voice_id.strip(), preview_bytes
    finally:
        if owns:
            await http.aclose()


async def generate_music_bytes(
    api_key: str,
    prompt: str,
    *,
    lyrics: str | None = None,
    model: str = DEFAULT_MUSIC_MODEL,
    is_instrumental: bool = False,
    client: httpx.AsyncClient | None = None,
) -> bytes:
    """Generate music from prompt (+ optional lyrics) via ``/v1/music_generation``.

    Args:
        api_key (str): Resolved MiniMax API key.
        prompt (str): Style / mood description (template-augmented).
        lyrics (str | None, optional): Vocal lyrics; omit for instrumental-only when
            ``is_instrumental`` is ``True``. Defaults to ``None``.
        model (str, optional): Music model id. Defaults to ``music-2.6``.
        is_instrumental (bool, optional): Request instrumental output. Defaults to ``False``.
        client (httpx.AsyncClient | None, optional): Injectable client for tests.

    Returns:
        bytes: MP3 bytes.

    Raises:
        MiniMaxMediaError: On transport or API failure.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(generate_music_bytes)
        True
    """
    body: dict[str, Any] = {
        "model": model,
        "prompt": prompt.strip(),
        "output_format": "url",
        "audio_setting": {"sample_rate": 44100, "bitrate": 256000, "format": "mp3"},
    }
    if is_instrumental:
        body["is_instrumental"] = True
    elif lyrics and lyrics.strip():
        body["lyrics"] = lyrics.strip()
    else:
        body["lyrics_optimizer"] = True
    owns = client is None
    http = client or httpx.AsyncClient(timeout=_DEFAULT_HTTP_TIMEOUT_S)
    try:
        response = await http.post(
            f"{MINIMAX_MEDIA_BASE_URL}/music_generation",
            headers=_auth_headers(api_key),
            json=body,
        )
        payload = _raise_for_status_payload(response, context="music_generation")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise MiniMaxMediaError("music_generation: missing data object")
        audio_url = data.get("audio")
        if not isinstance(audio_url, str) or not audio_url.strip():
            raise MiniMaxMediaError("music_generation: missing audio url")
        dl = await http.get(audio_url.strip())
        dl.raise_for_status()
        return dl.content
    finally:
        if owns:
            await http.aclose()


__all__ = [
    "DEFAULT_IMAGE_MODEL",
    "DEFAULT_MUSIC_MODEL",
    "DEFAULT_SPEECH_MODEL",
    "DEFAULT_VIDEO_FL2V_MODEL",
    "DEFAULT_VIDEO_I2V_MODEL",
    "DEFAULT_VIDEO_MODEL",
    "DEFAULT_VIDEO_S2V_MODEL",
    "MINIMAX_MEDIA_BASE_URL",
    "MiniMaxMediaError",
    "clone_voice_bytes",
    "generate_image_bytes",
    "generate_image_from_reference_bytes",
    "generate_music_bytes",
    "generate_video_bytes",
    "generate_video_first_last_frame_bytes",
    "generate_video_from_image_bytes",
    "generate_video_subject_reference_bytes",
    "generate_video_template_bytes",
    "synthesize_speech_bytes",
    "upload_file_bytes",
]
