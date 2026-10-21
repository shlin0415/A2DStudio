"""A2D diagnostics must retain useful metadata without storing dialogue text."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from ling_chat.core.a2d_message_handler import (
    _generate_and_synthesize,
    _handle_user_action,
)
from ling_chat.core.ai_service.core import AIService
from ling_chat.core.session_runtime import SessionRuntime
from ling_chat.schemas.script_overlay import ScriptLine


def _logged_text(logger_method: MagicMock) -> str:
    return " ".join(str(call.args) for call in logger_method.call_args_list)


@pytest.mark.asyncio
async def test_generation_log_keeps_response_length_but_not_response_text():
    private_text = "private dialogue that must not appear in service logs"
    session = SessionRuntime()
    session.batch_size = 1
    session.last_raw_llm_response = private_text
    ai_service = MagicMock()
    ai_service.a2d_session = session
    ai_service.a2d_generate_one = AsyncMock(return_value={
        "type": "script_line",
        "payload": {
            "id": "line-1",
            "speaker": "narrator",
            "display_text": private_text,
            "tts_text": "",
            "index": 0,
        },
    })

    async def noop(_message):
        return None

    with patch("ling_chat.core.a2d_message_handler.logger.info") as log_info:
        await _generate_and_synthesize(ai_service, noop)

    assert private_text not in _logged_text(log_info)
    assert str(len(private_text)) in _logged_text(log_info)
    assert all(len(call.args) == 1 for call in log_info.call_args_list)


@pytest.mark.asyncio
async def test_user_action_log_omits_content_detail():
    private_text = "private edited line that must not be logged"

    async def noop(_message):
        return None

    with patch("ling_chat.core.a2d_message_handler.logger.info") as log_info:
        await _handle_user_action(
            MagicMock(),
            "test-client",
            {
                "action": "edit",
                "target": "ReviewPanel line[2]",
                "detail": private_text,
                "timestamp": 1718700000000,
            },
            noop,
        )

    assert private_text not in _logged_text(log_info)
    assert "edit" in _logged_text(log_info)
    assert "ReviewPanel line[2]" in _logged_text(log_info)


@pytest.mark.asyncio
async def test_user_action_log_redacts_unrecognized_action_and_target():
    private_text = "private text passed in a forged telemetry target"

    async def noop(_message):
        return None

    with patch("ling_chat.core.a2d_message_handler.logger.info") as log_info:
        await _handle_user_action(
            MagicMock(),
            "test-client",
            {
                "action": private_text,
                "target": private_text,
                "detail": private_text,
            },
            noop,
        )

    assert private_text not in _logged_text(log_info)
    assert "other" in _logged_text(log_info)


@pytest.mark.asyncio
async def test_tts_failure_log_omits_exception_text():
    private_text = "provider error echoed private dialogue"
    session = SessionRuntime()
    session.batch_size = 1
    ai_service = MagicMock()
    ai_service.a2d_session = session
    ai_service.a2d_generate_one = AsyncMock(return_value={
        "type": "script_line",
        "payload": {
            "id": "line-1",
            "speaker": "ema",
            "display_text": "hello",
            "tts_text": "hello",
            "index": 0,
        },
    })
    ai_service.a2d_synthesize = AsyncMock(side_effect=RuntimeError(private_text))

    async def noop(_message):
        return None

    with patch("ling_chat.core.a2d_message_handler.logger.warning") as log_warning:
        await _generate_and_synthesize(ai_service, noop)

    assert private_text not in _logged_text(log_warning)
    assert all(len(call.args) == 1 for call in log_warning.call_args_list)


def test_a2d_prompt_log_keeps_message_counts_but_not_message_text():
    private_text = "private prior dialogue must reach the model but not logs"
    service = AIService.__new__(AIService)
    service.a2d_session = SessionRuntime()
    service.a2d_session.script_lines.append(
        ScriptLine(speaker="ema", display_text=private_text, raw_text=private_text)
    )

    with patch("ling_chat.core.ai_service.core.logger.debug") as log_debug:
        messages = service._a2d_build_messages("system prompt")

    assert private_text in messages[-1]["content"]
    assert private_text not in _logged_text(log_debug)
    assert "messages" in _logged_text(log_debug)
    assert all(len(call.args) == 1 for call in log_debug.call_args_list)


@pytest.mark.asyncio
async def test_a2d_response_debug_log_omits_response_text():
    private_text = "private model response must be returned but not logged"

    class FakeLLM:
        async def process_message_stream(self, _messages):
            yield private_text

    service = AIService.__new__(AIService)
    service.llm_model = FakeLLM()

    with patch("ling_chat.core.ai_service.core.logger.debug") as log_debug:
        response = await service._a2d_call_llm_with_retry([])

    assert response == private_text
    assert private_text not in _logged_text(log_debug)
    assert str(len(private_text)) in _logged_text(log_debug)
    assert all(len(call.args) == 1 for call in log_debug.call_args_list)
