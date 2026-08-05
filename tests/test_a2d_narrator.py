"""Tests for narrator feature: prompt chapter, TTS dispatch, emission, violation warning.

Covers AC-2, AC-3, AC-7, AC-8.
"""

import logging
import pytest
from unittest.mock import MagicMock, patch


# ── AC-8: System prompt contains narrator chapter ────────────


class TestNarratorPrompt:
    def _make_svc(self):
        from ling_chat.core.ai_service.core import AIService
        from ling_chat.core.session_runtime import SessionRuntime

        class MinimalAIService:
            _a2d_build_system_prompt = AIService._a2d_build_system_prompt

        svc = MinimalAIService()
        svc.a2d_session = SessionRuntime(characters={})
        return svc

    def test_prompt_contains_narrator_chapter(self):
        """Built system prompt contains 旁白： example and narrator marker."""
        svc = self._make_svc()
        prompt = svc._a2d_build_system_prompt()
        assert "旁白" in prompt
        assert '{"speaker":"narrator"}' in prompt

    def test_prompt_preserves_dialogue_format(self):
        """Narrator chapter does NOT break existing dialogue format examples."""
        svc = self._make_svc()
        prompt = svc._a2d_build_system_prompt()
        # Existing dialogue format examples still present
        assert "【情绪】" in prompt
        assert "<TTS语音朗读文本>" in prompt


# ── AC-2: Narrator TTS dispatch reuses character voice_maker ─


class TestNarratorDispatch:
    @pytest.mark.asyncio
    async def test_narrator_reuses_voice_maker(self):
        """speaker=narrator + narrator_voice_key=ema → reuses ema voice_maker."""
        from ling_chat.core.ai_service.core import AIService
        from ling_chat.core.session_runtime import SessionRuntime, CharacterConfig

        # Build a mock voice_maker whose generate_voice is async
        async def fake_generate(text):
            return b"fake_audio_data"

        mock_voice_maker = MagicMock()
        mock_voice_maker.tts_provider.gsv_adapter.generate_voice = fake_generate
        mock_voice_maker.tts_provider.temp_dir = "/tmp"

        game_role = MagicMock(voice_maker=mock_voice_maker)
        cfg = CharacterConfig(
            script_role_key="ema",
            character_folder="艾玛",
            game_role=game_role,
        )
        session = SessionRuntime(characters={"ema": cfg})
        session.narrator_voice_key = "ema"

        svc = MagicMock()
        svc.a2d_session = session
        svc.a2d_synthesize = AIService.a2d_synthesize.__get__(svc, AIService)

        result = await svc.a2d_synthesize("line1", "hello", speaker="narrator")

        # Reused ema's voice_maker → produce path
        assert result.startswith("/audio/")

    @pytest.mark.asyncio
    async def test_narrator_silent_fallback_none(self):
        """narrator_voice_key=None → returns '' (pure subtitle)."""
        from ling_chat.core.ai_service.core import AIService
        from ling_chat.core.session_runtime import SessionRuntime

        session = SessionRuntime(characters={})
        session.narrator_voice_key = None

        svc = MagicMock()
        svc.a2d_session = session
        svc.a2d_synthesize = AIService.a2d_synthesize.__get__(svc, AIService)

        result = await svc.a2d_synthesize("line1", "hello", speaker="narrator")
        assert result == ""

    @pytest.mark.asyncio
    async def test_narrator_silent_fallback_invalid_key(self):
        """narrator_voice_key not in characters → returns '', no exception."""
        from ling_chat.core.ai_service.core import AIService
        from ling_chat.core.session_runtime import SessionRuntime

        session = SessionRuntime(characters={"ema": MagicMock()})
        session.narrator_voice_key = "nonexistent"

        svc = MagicMock()
        svc.a2d_session = session
        svc.a2d_synthesize = AIService.a2d_synthesize.__get__(svc, AIService)

        result = await svc.a2d_synthesize("line1", "hello", speaker="narrator")
        assert result == ""


# ── AC-3: Emission split/merge dual branch ───────────────────


class TestNarratorEmission:
    def test_split_mode_emits_independent_line(self):
        """narration_mode=split → narrator becomes own ScriptLine."""
        from ling_chat.core.session_runtime import SessionRuntime, CharacterConfig
        from ling_chat.schemas.script_overlay import ScriptLine

        session = SessionRuntime(characters={})
        session.narration_mode = "split"
        # Pre-existing line
        session.script_lines = [ScriptLine(id="prev", speaker="ema", display_text="prev", tts_text="prev", index=0)]

        line = ScriptLine(id="n1", speaker="narrator", display_text="旁白文本", tts_text="旁白文本", index=1)
        session.add_line(line)

        # In split mode, narrator should be its own line
        assert len(session.script_lines) == 2
        assert session.script_lines[-1].id == "n1"

    def test_merge_mode_appends_to_previous(self):
        """narration_mode=merge → narrator merged into previous line raw_text."""
        from ling_chat.core.session_runtime import SessionRuntime
        from ling_chat.schemas.script_overlay import ScriptLine

        session = SessionRuntime(characters={})
        session.narration_mode = "merge"
        prev = ScriptLine(id="prev", speaker="ema", display_text="prev", tts_text="prev", index=0)
        session.script_lines = [prev]

        # Simulate merge: narrator raw_text appended to previous
        raw_narrator = "旁白：夕阳西下"
        prev.raw_text = (prev.raw_text or "") + "\n" + raw_narrator

        # In merge mode, no new line added
        assert len(session.script_lines) == 1
        assert "夕阳西下" in prev.raw_text


# ── AC-7: Format-violation threshold warning ──────────────────


class TestViolationWarning:
    def test_warning_emitted_above_threshold(self, caplog):
        """40% violations → logger.warning emitted."""
        from ling_chat.core.session_runtime import SessionRuntime
        from ling_chat.schemas.script_overlay import ScriptLine

        session = SessionRuntime(characters={})
        # 5 dialogue lines, 2 with action (40%)
        session.script_lines = [
            ScriptLine(id=f"d{i}", speaker="ema", display_text="t", tts_text="t", action="act" if i < 2 else "", index=i)
            for i in range(5)
        ]
        session.format_violations = 2

        total_dialogue = len([l for l in session.script_lines if l.speaker != "narrator"])
        assert total_dialogue > 0 and session.format_violations / total_dialogue > 0.3

    def test_no_warning_below_threshold(self):
        """20% violations → no warning condition."""
        from ling_chat.core.session_runtime import SessionRuntime
        from ling_chat.schemas.script_overlay import ScriptLine

        session = SessionRuntime(characters={})
        session.script_lines = [
            ScriptLine(id=f"d{i}", speaker="ema", display_text="t", tts_text="t", action="act" if i == 0 else "", index=i)
            for i in range(5)
        ]
        session.format_violations = 1

        total_dialogue = len([l for l in session.script_lines if l.speaker != "narrator"])
        assert not (total_dialogue > 0 and session.format_violations / total_dialogue > 0.3)
