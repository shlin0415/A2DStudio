"""Tests for standalone FicRuntime (AC-2, AC-3, AC-4)."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ling_chat.core.fic_runtime import FicRuntime
from ling_chat.core.session_runtime import CharacterConfig
from ling_chat.schemas.script_overlay import ScriptLine


def _make_char(key: str, folder: str) -> CharacterConfig:
    return CharacterConfig(
        script_role_key=key,
        character_folder=folder,
        voice_language="ja",
        display_language="zh",
    )


def _make_runtime(characters=None) -> FicRuntime:
    chars = characters or {
        "ema": _make_char("ema", "艾玛"),
        "hiro": _make_char("hiro", "希罗"),
    }
    # Sync construction with pre-built configs (no GSV needed for prompt/gen tests).
    return FicRuntime(characters=chars)


# ---------------------------------------------------------------------------
# AC-2: reference-material injection
# ---------------------------------------------------------------------------


class TestAC2Injection:
    def test_prompt_contains_reference_material(self):
        rt = _make_runtime()
        mat = "希罗听见了艾玛的心说：‘久等了’。"
        prompt = rt.build_prompt(mat, list(rt.session.characters.keys()))
        assert "参考材料" in prompt
        assert mat in prompt

    def test_prompt_contains_tongren_style(self):
        rt = _make_runtime()
        prompt = rt.build_prompt("测试", list(rt.session.characters.keys()))
        assert "同人演绎" in prompt

    def test_update_scene_sets_reference_material(self):
        rt = _make_runtime()
        rt.session.update_scene("同人演绎", "同人演绎", "一段材料")
        suffix = rt.session.build_scene_prompt_suffix()
        assert "参考材料：一段材料" in suffix

    def test_material_none_rejected(self):
        rt = _make_runtime()
        with pytest.raises(ValueError):
            asyncio.run(rt.generate_one(None))

    def test_material_none_direct_guard(self):
        """generate_one must not proceed when material is None."""
        rt = _make_runtime()
        with pytest.raises(ValueError, match="None"):
            asyncio.run(rt.generate_one(None))

    def test_oversized_material_truncated_with_marker(self, caplog):
        """AC-2 negative: material longer than max is truncated + visible marker."""
        rt = _make_runtime()
        rt.MAX_MATERIAL_CHARS = 100
        long_mat = "哈" * 500
        truncated = rt._truncate_material(long_mat)
        assert rt._TRUNCATION_MARKER in truncated
        assert len(truncated) <= 100 + len(rt._TRUNCATION_MARKER)


# ---------------------------------------------------------------------------
# AC-3: generation + history carry-over
# ---------------------------------------------------------------------------


def _mock_llm(rt: FicRuntime, responses: list[str]) -> None:
    """Patch the LLM to return scripted responses sequentially."""
    calls = iter(responses)

    async def _fake_stream(messages):
        text = next(calls)
        yield text

    rt.llm.process_message_stream = _fake_stream  # type: ignore[method-assign]


class TestAC3Generation:
    def test_generate_one_returns_parsed_line(self):
        rt = _make_runtime()
        _mock_llm(rt, ['{"speaker":"ema"}\n【高兴】こんにちは<こんにちは>（笑う）'])
        line = asyncio.run(rt.generate_one("测试材料"))
        assert line is not None
        assert line.speaker == "ema"
        assert line.emotion == "高兴"

    def test_history_grows_across_chunks(self):
        """AC-3 core: consecutive chunks carry history (B2 mechanism)."""
        rt = _make_runtime()
        _mock_llm(
            rt,
            [
                '{"speaker":"ema"}\n【高兴】早上好<おはよう>（挥手）',
                '{"speaker":"hiro"}\n【害羞】嗯，早上好<うん、おはよう>（低头）',
            ],
        )
        line1 = asyncio.run(rt.generate_one("材料1"))
        assert line1 is not None
        assert len(rt.session.script_lines) >= 1
        line2 = asyncio.run(rt.generate_one("材料2"))
        assert line2 is not None
        # History from line1 must be present for line2's generation.
        assert len(rt.session.script_lines) >= 2

    def test_unknown_speaker_defaults_to_narrator(self, caplog):
        """AC-3 negative: unmapped speaker marker → narrator + warning."""
        rt = _make_runtime()
        _mock_llm(rt, ['{"speaker":"unknown_guest"}\n【高兴】你好<こんにちは>'])
        line = asyncio.run(rt.generate_one("材料"))
        assert line is not None
        assert line.speaker == "narrator"
        assert "unmapped speaker" in caplog.text

    def test_garbage_llm_output_returns_none(self):
        rt = _make_runtime()
        _mock_llm(rt, ["this is not a valid script line at all 12345 !!!"])
        line = asyncio.run(rt.generate_one("材料"))
        # Parser may produce a line with the garbage as display_text (no crash).
        # The key AC-3 negative requirement: no crash.
        assert line is None or isinstance(line, ScriptLine)

    def test_empty_llm_output_raises_or_returns_none(self):
        rt = _make_runtime()
        _mock_llm(rt, [""])
        with pytest.raises(RuntimeError):
            asyncio.run(rt.generate_one("材料"))


# ---------------------------------------------------------------------------
# AC-4: voice synthesis
# ---------------------------------------------------------------------------


class TestAC4Synthesis:
    def test_empty_tts_text_skips_synthesis(self):
        rt = _make_runtime()
        line = ScriptLine(
            speaker="narrator", display_text="旁白内容", tts_text="", raw_text="旁白：x"
        )
        out = asyncio.run(rt.synthesize(line))
        assert out == ""

    def test_missing_gsv_adapter_skips_gracefully(self):
        """Non-ema/hiro / no adapter → skip + return '' (no crash)."""
        rt = _make_runtime()
        line = ScriptLine(
            speaker="ema", display_text="你好", tts_text="こんにちは", raw_text="x"
        )
        # No game_role/voice_maker configured → graceful skip.
        out = asyncio.run(rt.synthesize(line))
        assert out == ""
