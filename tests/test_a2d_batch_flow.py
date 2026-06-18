"""Test A2D batch flow — multi-line generation, retry, user actions, config."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from ling_chat.core.session_runtime import SessionRuntime
from ling_chat.schemas.script_overlay import ScriptLine
from ling_chat.core.a2d_message_handler import (
    _handle_start,
    _handle_retry,
    _handle_set_batch_size,
    _handle_user_action,
    _handle_continue,
)


def make_sr():
    return SessionRuntime()


# ── SessionRuntime: batch_size + last_batch_count ──────────


class TestBatchConfig:
    """batch_size defaults and last_batch_count lifecycle."""

    def test_default_batch_size(self):
        sr = make_sr()
        assert sr.batch_size == 1

    def test_default_last_batch_count(self):
        sr = make_sr()
        assert sr.last_batch_count == 0

    def test_set_batch_size(self):
        sr = make_sr()
        sr.batch_size = 3
        assert sr.batch_size == 3


# ── a2d.start: batch_size from payload ────────────────────


class TestStartBatchSize:
    @pytest.mark.asyncio
    async def test_start_uses_payload_batch_size(self):
        """a2d.start reads batch_size from payload and clamps to >=1."""
        ai_svc = MagicMock()
        ai_svc.a2d_session = make_sr()
        sent = []

        async def capture(msg):
            sent.append(msg)

        # Patch _a2d_build_character_configs (imported inside handler from api.new_chat_main)
        with (
            patch(
                "ling_chat.api.new_chat_main._a2d_build_character_configs",
                return_value={"ema": MagicMock()},
            ),
            patch(
                "ling_chat.core.a2d_message_handler._send_a2d_characters",
                new_callable=AsyncMock,
            ),
            patch(
                "ling_chat.core.a2d_message_handler._generate_and_synthesize",
                new_callable=AsyncMock,
                return_value=3,
            ),
        ):
            await _handle_start(ai_svc, "test", {"batch_size": 5}, capture)

        assert ai_svc.a2d_session.batch_size == 5

    @pytest.mark.asyncio
    async def test_start_clamps_negative_to_1(self):
        """batch_size <= 0 is clamped to 1."""
        ai_svc = MagicMock()
        ai_svc.a2d_session = make_sr()

        with (
            patch(
                "ling_chat.api.new_chat_main._a2d_build_character_configs",
                return_value={"ema": MagicMock()},
            ),
            patch(
                "ling_chat.core.a2d_message_handler._send_a2d_characters",
                new_callable=AsyncMock,
            ),
            patch(
                "ling_chat.core.a2d_message_handler._generate_and_synthesize",
                new_callable=AsyncMock,
                return_value=1,
            ),
        ):
            async def noop(msg):
                pass

            await _handle_start(ai_svc, "test", {"batch_size": -3}, noop)

        assert ai_svc.a2d_session.batch_size == 1

    @pytest.mark.asyncio
    async def test_start_defaults_to_1_when_missing(self):
        """batch_size missing from payload → defaults to 1."""
        ai_svc = MagicMock()
        ai_svc.a2d_session = make_sr()

        with (
            patch(
                "ling_chat.api.new_chat_main._a2d_build_character_configs",
                return_value={"ema": MagicMock()},
            ),
            patch(
                "ling_chat.core.a2d_message_handler._send_a2d_characters",
                new_callable=AsyncMock,
            ),
            patch(
                "ling_chat.core.a2d_message_handler._generate_and_synthesize",
                new_callable=AsyncMock,
                return_value=1,
            ),
        ):
            async def noop(msg):
                pass

            await _handle_start(ai_svc, "test", {}, noop)

        assert ai_svc.a2d_session.batch_size == 1


# ── a2d.set_batch_size ────────────────────────────────────


class TestSetBatchSize:
    @pytest.mark.asyncio
    async def test_set_batch_size_updates_session(self):
        ai_svc = MagicMock()
        ai_svc.a2d_session = make_sr()
        ai_svc.a2d_session.batch_size = 1

        async def noop(msg):
            pass

        await _handle_set_batch_size(ai_svc, "test", {"batch_size": 4}, noop)
        assert ai_svc.a2d_session.batch_size == 4

    @pytest.mark.asyncio
    async def test_set_batch_size_clamps_to_1(self):
        ai_svc = MagicMock()
        ai_svc.a2d_session = make_sr()

        async def noop(msg):
            pass

        await _handle_set_batch_size(ai_svc, "test", {"batch_size": 0}, noop)
        assert ai_svc.a2d_session.batch_size == 1


# ── a2d.retry: last_batch_count pop ───────────────────────


class TestRetryLastBatchCount:
    @pytest.mark.asyncio
    async def test_retry_pops_last_batch_count_lines(self):
        """a2d.retry pops last_batch_count lines (not hardcoded 1)."""
        ai_svc = MagicMock()
        sr = make_sr()
        # Simulate 3 lines generated in last batch
        for i in range(5):
            sr.add_line(ScriptLine(speaker="ema", display_text=f"line{i}"))
        sr.last_batch_count = 3
        ai_svc.a2d_session = sr

        with patch(
            "ling_chat.core.a2d_message_handler._generate_and_synthesize",
            new_callable=AsyncMock,
            return_value=2,
        ):
            async def noop(msg):
                pass

            await _handle_retry(ai_svc, "test", {}, noop)

        # 5 - 3 = 2 lines remaining
        assert len(sr.script_lines) == 2
        assert sr.last_batch_count == 0

    @pytest.mark.asyncio
    async def test_retry_with_zero_last_batch_pops_1(self):
        """When last_batch_count=0, retry pops at least 1 line."""
        ai_svc = MagicMock()
        sr = make_sr()
        sr.add_line(ScriptLine(speaker="ema", display_text="only"))
        sr.last_batch_count = 0
        ai_svc.a2d_session = sr

        with patch(
            "ling_chat.core.a2d_message_handler._generate_and_synthesize",
            new_callable=AsyncMock,
            return_value=1,
        ):
            async def noop(msg):
                pass

            await _handle_retry(ai_svc, "test", {}, noop)

        assert len(sr.script_lines) == 0


# ── a2d.user_action ───────────────────────────────────────


class TestUserAction:
    @pytest.mark.asyncio
    async def test_user_action_logs_all_fields(self):
        """a2d.user_action reads action, target, detail, timestamp."""
        ai_svc = MagicMock()

        async def noop(msg):
            pass

        # Should not raise — just logs
        await _handle_user_action(
            ai_svc,
            "test",
            {
                "action": "click",
                "target": "EventTrack line[3]",
                "detail": "ema: 你好",
                "timestamp": 1718700000000,
            },
            noop,
        )
        # No assertion needed — handler only logs. Test passes if no exception.

    @pytest.mark.asyncio
    async def test_user_action_missing_fields_defaults(self):
        """Missing fields get '?' defaults."""
        ai_svc = MagicMock()

        async def noop(msg):
            pass

        await _handle_user_action(ai_svc, "test", {}, noop)
        # Should not raise with empty payload


# ── _generate_and_synthesize error cleanup ────────────────


class TestGenerateAndSynthesizeErrorCleanup:
    @pytest.mark.asyncio
    async def test_error_pops_partial_generated_lines(self):
        """When a fatal error occurs mid-batch, generated lines are cleaned up."""
        from ling_chat.core.a2d_message_handler import _generate_and_synthesize

        ai_svc = MagicMock()
        sr = make_sr()
        ai_svc.a2d_session = sr

        line1 = ScriptLine(speaker="ema", display_text="hello", emotion="高兴")
        line2 = ScriptLine(speaker="hiro", display_text="hi", emotion="疑惑")
        line3 = ScriptLine(speaker="ema", display_text="bye", emotion="正常")

        # simulate: a2d_generate_next already added 3 lines to session
        sr.add_line(line1)
        sr.add_line(line2)
        sr.add_line(line3)

        results = [
            {"type": "script_line", "payload": {"id": line1.id, "speaker": "ema", "emotion": "高兴", "display_text": "hello", "tts_text": "hello", "index": 0}},
            {"type": "script_line", "payload": {"id": line2.id, "speaker": "hiro", "emotion": "疑惑", "display_text": "hi", "tts_text": "hi", "index": 1}},
            {"type": "script_line", "payload": {"id": line3.id, "speaker": "ema", "emotion": "正常", "display_text": "bye", "tts_text": "bye", "index": 2}},
        ]

        async def mock_generate_next(*args, **kwargs):
            return results

        ai_svc.a2d_generate_next = mock_generate_next
        ai_svc.a2d_synthesize = AsyncMock(return_value="/audio/test.wav")
        ai_svc._a2d_translate_for_tts = MagicMock(return_value="")

        # Make send() raise on the first script_line (simulate WS disconnect mid-batch).
        # The thinking status and error messages must still go through.
        send_count = [0]

        async def capture(msg):
            send_count[0] += 1
            if msg.get("type") == "script_line":
                raise ConnectionError("WS disconnected")

        await _generate_and_synthesize(ai_svc, capture)

        # Should clean up: pop the lines, reset state
        assert len(sr.script_lines) == 0
        assert sr.last_batch_count == 0

    @pytest.mark.asyncio
    async def test_tts_failure_is_non_fatal_continues_batch(self):
        """TTS failure for one line does not abort the batch (non-fatal)."""
        from ling_chat.core.a2d_message_handler import _generate_and_synthesize

        ai_svc = MagicMock()
        sr = make_sr()
        ai_svc.a2d_session = sr

        line1 = ScriptLine(speaker="ema", display_text="hello", emotion="高兴")
        line2 = ScriptLine(speaker="hiro", display_text="hi", emotion="疑惑")

        sr.add_line(line1)
        sr.add_line(line2)

        results = [
            {"type": "script_line", "payload": {"id": line1.id, "speaker": "ema", "emotion": "高兴", "display_text": "hello", "tts_text": "hello", "index": 0}},
            {"type": "script_line", "payload": {"id": line2.id, "speaker": "hiro", "emotion": "疑惑", "display_text": "hi", "tts_text": "hi", "index": 1}},
        ]

        async def mock_generate_next(*args, **kwargs):
            return results

        ai_svc.a2d_generate_next = mock_generate_next
        # TTS fails for line 1, succeeds for line 2
        tts_calls = [0]

        async def mock_synthesize(line_id, tts_text, speaker=None):
            tts_calls[0] += 1
            if tts_calls[0] == 1:
                raise RuntimeError("TTS timeout")
            return f"/audio/{line_id}.wav"

        ai_svc.a2d_synthesize = mock_synthesize
        ai_svc._a2d_translate_for_tts = MagicMock(return_value="translated")

        sent = []

        async def capture(msg):
            sent.append(msg)

        result = await _generate_and_synthesize(ai_svc, capture)

        # Batch completes successfully (TTS failure is non-fatal)
        assert result == 2
        # Lines remain in session
        assert len(sr.script_lines) == 2
        # Paused status sent at end
        assert any(msg.get("type") == "status" and msg.get("payload", {}).get("phase") == "paused" for msg in sent)
