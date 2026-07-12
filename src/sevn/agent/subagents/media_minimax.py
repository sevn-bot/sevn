"""MiniMax media REST adapter for the ``media_generator`` specialist (W8.2).

Isolates image / video / music endpoint knowledge so provider drift stays local.

Module: sevn.agent.subagents.media_minimax
Depends: asyncio, base64, httpx, loguru

Exports:
    MiniMaxMediaError — typed failure from MiniMax media APIs.
    generate_image_bytes — POST ``/v1/image_generation`` → JPEG bytes.
    generate_video_bytes — async video task poll + download → MP4 bytes.
    generate_music_bytes — POST ``/v1/music_generation`` → MP3 bytes.

Examples:
    >>> from sevn.agent.subagents.media_minimax import DEFAULT_IMAGE_MODEL
    >>> DEFAULT_IMAGE_MODEL
    'image-01'
"""

from __future__ import annotations

import asyncio
import base64
from typing import Any

import httpx

MINIMAX_MEDIA_BASE_URL = "https://api.minimax.io/v1"
DEFAULT_IMAGE_MODEL = "image-01"
DEFAULT_VIDEO_MODEL = "MiniMax-Hailuo-2.3"
DEFAULT_MUSIC_MODEL = "music-2.6"

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
        prompt (str): Text prompt.
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


async def generate_video_bytes(
    api_key: str,
    prompt: str,
    *,
    model: str = DEFAULT_VIDEO_MODEL,
    duration: int = 6,
    resolution: str = "720P",
    poll_interval_s: float = _DEFAULT_VIDEO_POLL_INTERVAL_S,
    max_polls: int = _DEFAULT_VIDEO_MAX_POLLS,
    client: httpx.AsyncClient | None = None,
) -> bytes:
    """Generate a video from text via MiniMax async video APIs.

    Args:
        api_key (str): Resolved MiniMax API key.
        prompt (str): Text prompt.
        model (str, optional): Video model id. Defaults to ``MiniMax-Hailuo-2.3``.
        duration (int, optional): Clip duration seconds. Defaults to ``6``.
        resolution (str, optional): Output resolution label. Defaults to ``720P``.
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
    body = {
        "model": model,
        "prompt": prompt.strip(),
        "duration": duration,
        "resolution": resolution,
    }
    owns = client is None
    http = client or httpx.AsyncClient(timeout=_DEFAULT_HTTP_TIMEOUT_S)
    try:
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
        prompt (str): Style / mood description.
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
    "DEFAULT_VIDEO_MODEL",
    "MINIMAX_MEDIA_BASE_URL",
    "MiniMaxMediaError",
    "generate_image_bytes",
    "generate_music_bytes",
    "generate_video_bytes",
]
