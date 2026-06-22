"""Test KV-cache-friendly history reconstruction.

_a2d_build_messages must:
- Use raw_text verbatim when available (preserve action, TTS tags, exact spacing)
- Fall back to field reconstruction when raw_text is empty (edited/legacy lines)
- Format narrator lines as {旁白: ...}
- Include speaker markers for dialogue lines
"""

import pytest
from unittest.mock import MagicMock
from ling_chat.core.session_runtime import SessionRuntime
from ling_chat.schemas.script_overlay import ScriptLine


def make_sr():
    return SessionRuntime()


def build_messages(sr, system_prompt="你是一个双人对话生成器。"):
    """Call _a2d_build_messages on a mock AIService with the given session."""
    from ling_chat.core.ai_service.core import AIService

    mock_ai = MagicMock()
    mock_ai.a2d_session = sr
    # Bind the real method
    mock_ai._a2d_build_messages = AIService._a2d_build_messages.__get__(mock_ai, AIService)
    return mock_ai._a2d_build_messages(system_prompt)


def find_assistant(msgs, speaker):
    """Find the first assistant message containing the given speaker marker."""
    marker = f'"speaker":"{speaker}"'
    for m in msgs:
        if m["role"] == "assistant" and marker in m["content"]:
            return m
    return None


# ── raw_text verbatim path ───────────────────────────────────


class TestRawTextVerbatim:
    def test_action_preserved_in_history(self):
        """raw_text keeps （action） in history — KV cache matches LLM output."""
        sr = make_sr()
        raw = "【害羞】希罗酱、今日も来てくれたんだね……<ヒロちゃん>（低头玩弄着衣角）"
        sr.add_line(ScriptLine(
            speaker="ema", emotion="害羞",
            display_text="希罗酱、今日も来てくれたんだね……",
            tts_text="ヒロちゃん",
            raw_text=raw, state="approved",
        ))
        msgs = build_messages(sr)
        msg = find_assistant(msgs, "ema")
        assert msg is not None
        # The content should start with speaker marker + newline + raw_text
        expected = '{"speaker":"ema"}\n' + raw
        assert msg["content"] == expected
        assert "（低头玩弄着衣角）" in msg["content"]

    def test_tts_tags_preserved(self):
        """<TTS> tags in raw_text are not stripped."""
        sr = make_sr()
        raw = "【无奈】嗯、怕你又在图书馆睡着。<ああ、また図書館で寝て>（轻轻叹了口气）"
        sr.add_line(ScriptLine(
            speaker="hiro", emotion="无奈",
            display_text="嗯、怕你又在图书馆睡着。",
            tts_text="ああ、また図書館で寝て",
            raw_text=raw, state="approved",
        ))
        msgs = build_messages(sr)
        msg = find_assistant(msgs, "hiro")
        assert "<ああ、また図書館で寝て>" in msg["content"]

    def test_multiple_lines_all_preserve_raw(self):
        """3 lines with raw_text → all 3 preserve their raw content."""
        sr = make_sr()
        raws = [
            "【害羞】你好<Hello>（挥手）",
            "【无奈】嗯<Yeah>（叹气）",
            "【高兴】好的<OK>（笑）",
        ]
        for i, raw in enumerate(raws):
            speaker = "ema" if i % 2 == 0 else "hiro"
            sr.add_line(ScriptLine(
                speaker=speaker, emotion="test",
                display_text="test", tts_text="test",
                raw_text=raw, state="approved",
            ))
        msgs = build_messages(sr)
        assistants = [m for m in msgs if m["role"] == "assistant"]
        assert len(assistants) == 3
        for i, msg in enumerate(assistants):
            assert raws[i] in msg["content"]


# ── Fallback path (raw_text empty) ───────────────────────────


class TestFallbackReconstruction:
    def test_edited_line_uses_field_reconstruction(self):
        """raw_text="" → fallback: 【emotion】display<TTS>."""
        sr = make_sr()
        sr.add_line(ScriptLine(
            speaker="ema", emotion="害羞",
            display_text="用户编辑后的文本",
            tts_text="translated text",
            raw_text="",  # edited — no raw_text
            state="approved",
        ))
        msgs = build_messages(sr)
        msg = find_assistant(msgs, "ema")
        expected = '{"speaker":"ema"}\n【害羞】用户编辑后的文本<translated text>'
        assert msg["content"] == expected

    def test_legacy_line_without_raw_text(self):
        """No raw_text at all → fallback (backward compat)."""
        from ling_chat.schemas.script_overlay import ScriptLine as SL

        # Simulate a ScriptLine that was created without raw_text (legacy)
        sr = make_sr()
        sr.add_line(SL(
            speaker="hiro", emotion="认真",
            display_text="你好", tts_text="Hello",
            state="approved",
        ))
        msgs = build_messages(sr)
        msg = find_assistant(msgs, "hiro")
        assert "【认真】你好<Hello>" in msg["content"]


# ── Narrator lines ───────────────────────────────────────────


class TestNarratorLines:
    def test_narrator_raw_text_in_history(self):
        """Narrator lines use {旁白: ...} format with raw_text."""
        sr = make_sr()
        sr.add_line(ScriptLine(
            speaker="narrator", emotion="",
            display_text="（把外套轻轻披在艾玛肩上）",
            tts_text="",
            raw_text="（把外套轻轻披在艾玛肩上）",
            state="approved",
        ))
        msgs = build_messages(sr)
        narrator_msgs = [m for m in msgs if m["role"] == "user" and "旁白" in m["content"]]
        assert len(narrator_msgs) == 1
        assert "（把外套轻轻披在艾玛肩上）" in narrator_msgs[0]["content"]

    def test_narrator_fallback_without_raw(self):
        """Narrator line without raw_text uses display_text."""
        sr = make_sr()
        sr.add_line(ScriptLine(
            speaker="narrator", emotion="",
            display_text="（动作描述）",
            tts_text="", raw_text="",
            state="approved",
        ))
        msgs = build_messages(sr)
        narrator_msgs = [m for m in msgs if m["role"] == "user" and "旁白" in m["content"]]
        assert len(narrator_msgs) == 1
        assert "（动作描述）" in narrator_msgs[0]["content"]


# ── End-to-end: edit → raw_text cleared → fallback ──────────


class TestEditClearsRawText:
    @pytest.mark.asyncio
    async def test_apply_edits_clears_raw_text(self):
        """After _apply_edits, raw_text='' → history uses field reconstruction."""
        sr = make_sr()
        sr.add_line(ScriptLine(
            speaker="ema", emotion="害羞",
            display_text="original display",
            tts_text="original tts",
            raw_text="【害羞】original display<original tts>（action）",
            state="approved",
        ))
        sr.add_line(ScriptLine(
            speaker="hiro", emotion="无奈",
            display_text="second line",
            tts_text="second tts",
            raw_text="【无奈】second line<second tts>（sigh）",
            state="approved",
        ))

        # Edit the first line
        await sr.handle_continue("gen-1", [{"id": sr.script_lines[0].id, "text": "edited text"}])

        msgs = build_messages(sr)
        # _apply_edits truncates from the first edit point (index 0),
        # so only the edited line remains. line 2 (hiro) is gone.
        assistants = [m for m in msgs if m["role"] == "assistant"]
        assert len(assistants) == 1

        msg0 = assistants[0]
        assert "original display" not in msg0["content"]  # old text gone
        assert "edited text" in msg0["content"]  # new text present
        assert "（action）" not in msg0["content"]  # action NOT preserved (edited line)


# ── Empty history ────────────────────────────────────────────


class TestEmptyHistory:
    def test_no_lines_gives_opening(self):
        sr = make_sr()
        msgs = build_messages(sr)
        assert len(msgs) == 2  # system + opening user message
        assert msgs[1]["role"] == "user"
        assert msgs[1]["content"]  # opening message is non-empty
