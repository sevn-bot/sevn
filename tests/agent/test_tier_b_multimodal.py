"""W10 tier-B multimodal user prompt construction."""

from __future__ import annotations

import base64
import json
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

from pydantic_ai.messages import BinaryContent, DocumentUrl, ImageUrl

from sevn.agent.adapters.tier_b_multimodal import (
    TierBModalitySupport,
    build_tier_b_user_prompt,
    resolve_tier_b_modality_support,
    resolve_turn_media_items,
)
from sevn.gateway.turn.turn_media import TurnMediaItem, build_turn_media_summaries
from sevn.storage.migrate import apply_migrations


def test_text_only_prompt_unchanged() -> None:
    prompt = build_tier_b_user_prompt(
        incoming_text="plain question",
        triage_requires_vision=False,
        triage_requires_document=False,
        turn_media=(),
        session_id="s1",
        support=TierBModalitySupport(vision=True, document=True),
    )
    assert prompt == "plain question"


def test_image_turn_native_vision_sends_binary_content() -> None:
    png = b"\x89PNG\r\n\x1a\n"
    item = TurnMediaItem(
        kind="photo",
        media_type="image/png",
        filename="chart.png",
        rel_path="chart.png",
        data=png,
    )
    prompt = build_tier_b_user_prompt(
        incoming_text="Describe the chart",
        triage_requires_vision=True,
        triage_requires_document=False,
        turn_media=(item,),
        session_id="s1",
        support=TierBModalitySupport(vision=True, document=True),
    )
    assert isinstance(prompt, list)
    assert prompt[0] == "Describe the chart"
    assert len(prompt) == 2
    part = prompt[1]
    assert isinstance(part, BinaryContent)
    assert part.data == png
    assert part.media_type == "image/png"


def test_image_turn_uses_image_url_when_only_url_present() -> None:
    item = TurnMediaItem(
        kind="photo",
        media_type="image/jpeg",
        filename="remote.jpg",
        rel_path="remote.jpg",
        data=b"",
        url="https://cdn.example.com/remote.jpg",
    )
    prompt = build_tier_b_user_prompt(
        incoming_text="What is this?",
        triage_requires_vision=True,
        triage_requires_document=False,
        turn_media=(item,),
        session_id="s1",
        support=TierBModalitySupport(vision=True, document=False),
    )
    assert isinstance(prompt, list)
    part = prompt[1]
    assert isinstance(part, ImageUrl)
    assert part.url == "https://cdn.example.com/remote.jpg"
    assert part.force_download is False


def test_image_url_force_download_for_local_host() -> None:
    item = TurnMediaItem(
        kind="photo",
        media_type="image/png",
        filename="local.png",
        rel_path="local.png",
        data=b"",
        url="http://127.0.0.1:8787/files/local.png",
    )
    prompt = build_tier_b_user_prompt(
        incoming_text="check",
        triage_requires_vision=True,
        triage_requires_document=False,
        turn_media=(item,),
        session_id="s1",
        support=TierBModalitySupport(vision=True, document=True),
    )
    assert isinstance(prompt, list)
    part = prompt[1]
    assert isinstance(part, ImageUrl)
    assert part.force_download is True


def test_pdf_turn_native_document_sends_binary_or_url() -> None:
    pdf_bytes = b"%PDF-1.4 stub"
    item = TurnMediaItem(
        kind="document",
        media_type="application/pdf",
        filename="report.pdf",
        rel_path="report.pdf",
        data=pdf_bytes,
    )
    prompt = build_tier_b_user_prompt(
        incoming_text="Summarize report.pdf",
        triage_requires_vision=False,
        triage_requires_document=True,
        turn_media=(item,),
        session_id="sess",
        support=TierBModalitySupport(vision=True, document=True),
    )
    assert isinstance(prompt, list)
    part = prompt[1]
    assert isinstance(part, BinaryContent)
    assert part.media_type == "application/pdf"

    url_item = TurnMediaItem(
        kind="document",
        media_type="application/pdf",
        filename="remote.pdf",
        rel_path="remote.pdf",
        data=b"",
        url="https://example.com/report.pdf",
    )
    url_prompt = build_tier_b_user_prompt(
        incoming_text="Summarize",
        triage_requires_vision=False,
        triage_requires_document=True,
        turn_media=(url_item,),
        session_id="sess",
        support=TierBModalitySupport(vision=True, document=True),
    )
    assert isinstance(url_prompt, list)
    assert isinstance(url_prompt[1], DocumentUrl)


def test_non_supporting_model_falls_back_to_file_and_skill() -> None:
    item = TurnMediaItem(
        kind="document",
        media_type="application/pdf",
        filename="report.pdf",
        rel_path="report.pdf",
        data=b"%PDF",
    )
    prompt = build_tier_b_user_prompt(
        incoming_text="Summarize",
        triage_requires_vision=False,
        triage_requires_document=True,
        turn_media=(item,),
        session_id="sess-9",
        support=TierBModalitySupport(vision=False, document=False),
    )
    assert isinstance(prompt, str)
    assert "channel_files/sess-9/report.pdf" in prompt
    assert "pdf skill" in prompt


def test_openai_native_supports_vision_not_document_pdf_fallback() -> None:
    item = TurnMediaItem(
        kind="document",
        media_type="application/pdf",
        filename="report.pdf",
        rel_path="report.pdf",
        data=b"%PDF",
    )
    support = resolve_tier_b_modality_support(
        model_id="openai/gpt-4o",
        transport_name="chat_completions",
        native_model_active=True,
    )
    assert support.vision is True
    assert support.document is False
    prompt = build_tier_b_user_prompt(
        incoming_text="Summarize",
        triage_requires_vision=False,
        triage_requires_document=True,
        turn_media=(item,),
        session_id="s",
        support=support,
    )
    assert isinstance(prompt, str)
    assert "pdf skill" in prompt


def test_function_model_path_disables_native_multimodal() -> None:
    support = resolve_tier_b_modality_support(
        model_id="anthropic/claude-sonnet-4-20250514",
        transport_name="anthropic",
        native_model_active=False,
    )
    assert support == TierBModalitySupport(vision=False, document=False)


def test_resolve_turn_media_via_channel_router() -> None:
    item = TurnMediaItem(
        kind="photo",
        media_type="image/png",
        filename="a.png",
        rel_path="a.png",
        data=b"x",
    )
    router = MagicMock()
    router.load_turn_media.return_value = (item,)
    loaded = resolve_turn_media_items(
        session_id="s",
        turn_id="t",
        content_root=Path("/tmp"),
        triage_requires_vision=True,
        triage_requires_document=False,
        turn_media=None,
        channel_router=router,
    )
    assert loaded == (item,)
    router.load_turn_media.assert_called_once_with("s", "t")


def test_resolve_turn_media_skips_when_no_modality_flags() -> None:
    router = MagicMock()
    loaded = resolve_turn_media_items(
        session_id="s",
        turn_id="t",
        content_root=Path("/tmp"),
        triage_requires_vision=False,
        triage_requires_document=False,
        turn_media=None,
        channel_router=router,
    )
    assert loaded == ()
    router.load_turn_media.assert_not_called()


def test_turn_media_from_db_hydrates_bytes(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    content = root / "files"
    content.mkdir(parents=True)
    dot_sevn = root / ".sevn"
    dot_sevn.mkdir()
    db_path = dot_sevn / "sevn.db"
    conn = sqlite3.connect(str(db_path))
    apply_migrations(conn)
    media_dir = content / "channel_files" / "sess-db"
    media_dir.mkdir(parents=True)
    png = b"\x89PNG\r\n\x1a\n"
    (media_dir / "pic.png").write_bytes(png)
    summaries = build_turn_media_summaries(
        [{"type": "photo", "filename": "pic.png", "data_base64": base64.b64encode(png).decode()}],
        media_dir=media_dir,
    )
    conn.execute(
        """
        INSERT INTO gateway_messages(
            session_id, role, kind, content, visible_to_llm, status, turn_id, extras_json, created_at
        ) VALUES ('sess-db', 'user', 'message', 'hi', 1, 'sent', 'turn-db', ?, 1)
        """,
        (json.dumps({"turn_media": summaries}),),
    )
    conn.commit()
    conn.close()

    loaded = resolve_turn_media_items(
        session_id="sess-db",
        turn_id="turn-db",
        content_root=content,
        triage_requires_vision=True,
        triage_requires_document=False,
        turn_media=None,
        channel_router=None,
    )
    assert len(loaded) == 1
    assert loaded[0].data == png
