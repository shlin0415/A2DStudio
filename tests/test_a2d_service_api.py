"""Contract checks for the A2D methods used by the message handler."""

from types import SimpleNamespace

import pytest


def test_ai_service_exposes_a2d_synthesize():
    from ling_chat.core.ai_service.core import AIService

    assert callable(getattr(AIService, "a2d_synthesize", None))


def test_ai_service_exposes_a2d_tts_translation():
    from ling_chat.core.ai_service.core import AIService

    assert callable(getattr(AIService, "_a2d_translate_for_tts", None))


@pytest.mark.asyncio
async def test_manual_tts_uses_explicit_speaker_without_session_line():
    from ling_chat.core.a2d_message_handler import _handle_regenerate_tts

    translations = []
    service = SimpleNamespace(
        a2d_session=SimpleNamespace(
            script_lines=[],
            characters={"hiro": SimpleNamespace(voice_language="ja", display_language="zh")},
        ),
        _a2d_translate_for_tts=lambda text, speaker: translations.append((text, speaker)) or text,
    )
    calls = []

    async def synthesize(line_id, text, speaker=""):
        calls.append((line_id, text, speaker))
        return f"/audio/a2d_{line_id}.wav"

    service.a2d_synthesize = synthesize
    messages = []

    async def send(message):
        messages.append(message)

    await _handle_regenerate_tts(
        service,
        "client-1",
        {"id": "manual-line-1", "text": "早上好。", "speaker": "hiro", "auto_play": False},
        send,
    )

    assert calls == [("manual-line-1", "早上好。", "hiro")]
    assert translations == []
    assert messages[1] == {
        "type": "tts_ready",
        "payload": {
            "id": "manual-line-1",
            "audio_path": "/audio/a2d_manual-line-1.wav",
            "tts_text": "早上好。",
            "auto_play": False,
        },
    }


@pytest.mark.asyncio
async def test_regenerate_tts_uses_updated_speaker_for_existing_line():
    from ling_chat.core.a2d_message_handler import _handle_regenerate_tts

    target_line = SimpleNamespace(
        id="generated-line-1",
        speaker="ema",
        display_text="早上好。",
        tts_text="早上好。",
    )
    characters = {
        "ema": SimpleNamespace(voice_language="zh", display_language="zh"),
        "hiro": SimpleNamespace(voice_language="zh", display_language="zh"),
    }
    service = SimpleNamespace(
        a2d_session=SimpleNamespace(script_lines=[target_line], characters=characters),
        _a2d_translate_for_tts=lambda text, speaker: text,
    )
    synthesized_speakers = []

    async def synthesize(line_id, text, speaker=""):
        synthesized_speakers.append(speaker)
        return f"/audio/a2d_{line_id}.wav"

    service.a2d_synthesize = synthesize

    async def send(message):
        return None

    await _handle_regenerate_tts(
        service,
        "client-1",
        {
            "id": "generated-line-1",
            "text": "早上好。",
            "speaker": "hiro",
            "auto_play": False,
        },
        send,
    )

    assert synthesized_speakers == ["hiro"]
    assert target_line.speaker == "hiro"


@pytest.mark.asyncio
async def test_manual_tts_rejects_path_like_line_id():
    from ling_chat.core.a2d_message_handler import _handle_regenerate_tts

    service = SimpleNamespace(a2d_session=SimpleNamespace(script_lines=[], characters={}))
    messages = []

    async def send(message):
        messages.append(message)

    await _handle_regenerate_tts(
        service,
        "client-1",
        {"id": "../outside", "text": "台词", "speaker": "hiro"},
        send,
    )

    assert messages[0]["type"] == "error"
    assert "无效的台词 ID" in messages[0]["payload"]["message"]


@pytest.mark.asyncio
async def test_initialize_loads_character_configs_without_starting_generation(monkeypatch):
    from ling_chat.core import a2d_message_handler

    character_config = object()
    service = SimpleNamespace(a2d_session=SimpleNamespace(characters={}))
    monkeypatch.setattr(
        "ling_chat.api.new_chat_main._a2d_build_character_configs",
        lambda ai_service: {"ema": character_config},
    )

    async def send_characters(session, send):
        await send({"type": "a2d.characters", "payload": {"characters": []}})

    monkeypatch.setattr(a2d_message_handler, "_send_a2d_characters", send_characters)
    messages = []

    async def send(message):
        messages.append(message)

    handled = await a2d_message_handler.dispatch("a2d.initialize", service, "client-1", {}, send)

    assert handled is True
    assert service.a2d_session.characters == {"ema": character_config}
    assert [message["type"] for message in messages] == ["a2d.characters", "a2d.initialized"]
