"""Unit tests for _a2d_parse_script_line — LLM output parsing.

Tests: pure action lines, emotion extraction, TTS extraction,
action stripping, raw_text preservation, edge cases.
"""

import pytest
from ling_chat.schemas.script_overlay import ScriptLine


# ── Helpers ──────────────────────────────────────────────────

# _a2d_parse_script_line is a method on AIService but doesn't use self.
# We can call it on any object since all imports are local.


@pytest.fixture
def parser():
    """A minimal host object that exposes _a2d_parse_script_line."""
    from ling_chat.core.ai_service.core import AIService

    class MinimalParser:
        """Mimics AIService just enough to call _a2d_parse_script_line."""
        _a2d_parse_script_line = AIService._a2d_parse_script_line

    return MinimalParser()


def parse(parser, text, speaker="ema"):
    """Shorthand: parse one line, return ScriptLine or None."""
    return parser._a2d_parse_script_line(text, speaker)


# ── Pure action-line detection ────────────────────────────────


class TestPureActionLine:
    def test_action_only_becomes_narrator(self, parser):
        """（把外套轻轻披在艾玛肩上）→ narrator, no TTS."""
        line = parse(parser, "（把外套轻轻披在艾玛肩上）")
        assert line is not None
        assert line.speaker == "narrator"
        assert line.emotion == ""
        assert line.tts_text == ""
        assert line.display_text == "（把外套轻轻披在艾玛肩上）"

    def test_action_only_preserves_raw_text(self, parser):
        """Narrator lines keep raw_text for KV-cache history."""
        line = parse(parser, "（别过脸去，耳根却悄悄泛红）")
        assert line.raw_text == "（别过脸去，耳根却悄悄泛红）"

    def test_action_at_end_of_dialogue_is_not_narrator(self, parser):
        """【害羞】你好（挥手）→ normal parse, speaker=ema, action stripped."""
        line = parse(parser, "【害羞】你好（挥手）")
        assert line.speaker == "ema"
        assert line.emotion == "害羞"
        assert "你好" in line.display_text
        assert "挥手" not in line.display_text  # action stripped from display

    def test_action_prefix_with_text_is_not_narrator(self, parser):
        """（笑）你好 → NOT a pure action line (text follows action)."""
        line = parse(parser, "（笑）你好")
        # Should NOT be narrator — (笑) is at start but 你好 follows
        assert line is not None
        assert line.speaker != "narrator"


# ── Emotion extraction ───────────────────────────────────────


class TestEmotionExtraction:
    def test_extracts_emotion(self, parser):
        line = parse(parser, "【害羞】你好")
        assert line.emotion == "害羞"

    def test_empty_when_no_emotion(self, parser):
        line = parse(parser, "你好")
        assert line.emotion == ""

    def test_unicode_emotion(self, parser):
        line = parse(parser, "【高兴】今天天气真好")
        assert line.emotion == "高兴"


# ── TTS extraction ───────────────────────────────────────────


class TestTTSExtraction:
    def test_extracts_tts_from_brackets(self, parser):
        line = parse(parser, "【害羞】你好<Hello>")
        assert line.tts_text == "Hello"

    def test_tts_falls_back_to_text_when_no_brackets(self, parser):
        line = parse(parser, "【害羞】你好")
        assert line.tts_text == "你好"

    def test_tts_not_confused_by_action_brackets(self, parser):
        """<TTS> should not be confused with （action）."""
        line = parse(parser, "【高兴】こんにちは<Hello>（挥手）")
        assert line.tts_text == "Hello"
        assert "挥手" not in line.display_text


# ── Display text ─────────────────────────────────────────────


class TestDisplayText:
    def test_strips_action_from_display(self, parser):
        line = parse(parser, "【害羞】你好<Hello>（轻轻挥手）")
        assert line.display_text == "你好"
        assert "轻轻挥手" not in line.display_text

    def test_strips_tts_brackets_from_display(self, parser):
        line = parse(parser, "【害羞】你好<Hello>")
        assert line.display_text == "你好"
        assert "<Hello>" not in line.display_text

    def test_preserves_text_without_action_or_tts(self, parser):
        line = parse(parser, "【认真】今天天气不错")
        assert line.display_text == "今天天气不错"


# ── raw_text preservation ────────────────────────────────────


class TestRawTextPreservation:
    def test_raw_text_matches_input(self, parser):
        raw = "【害羞】希罗酱、今日も来てくれたんだね……<ヒロちゃん、今日も来てくれたんだね……>（低頭玩耍著衣角，臉頰微紅）"
        line = parse(parser, raw)
        assert line.raw_text == raw

    def test_raw_text_preserves_action(self, parser):
        """raw_text keeps （action） even though display_text strips it."""
        raw = "【无奈】嗯，怕你又在图书馆睡着。<ああ、また図書館で寝て、本を枕にしそうだからな。>（轻轻叹了口气）"
        line = parse(parser, raw)
        assert "（轻轻叹了口气）" in line.raw_text
        assert "轻轻叹了口气" not in line.display_text


# ── Edge cases ───────────────────────────────────────────────


class TestEdgeCases:
    def test_empty_string_returns_none(self, parser):
        assert parse(parser, "") is None

    def test_whitespace_only_returns_none(self, parser):
        assert parse(parser, "   ") is None

    def test_newline_stripped_returns_none(self, parser):
        assert parse(parser, "\n") is None

    def test_speaker_marker_not_parsed_as_line(self, parser):
        """{"speaker":"ema"} — no emotion marker, treated as raw text."""
        line = parse(parser, '{"speaker":"ema"}')
        assert line is not None
        # No 【emotion】 so emotion is empty, display_text is the raw text
        assert line.emotion == ""
