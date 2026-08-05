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


# ── Explicit narration marker (旁白：xxx) ────────────────────


class TestExplicitNarration:
    def test_narrator_parses_with_prefix_stripped(self, parser):
        """旁白：xxx → narrator, display_text without prefix, tts_text = content."""
        line = parse(parser, "旁白：希罗和艾玛来到了公园")
        assert line is not None
        assert line.speaker == "narrator"
        assert line.emotion == ""
        assert line.display_text == "希罗和艾玛来到了公园"
        assert line.tts_text == "希罗和艾玛来到了公园"  # voiceable

    def test_narrator_with_halfwidth_colon(self, parser):
        """旁白:xxx (halfwidth colon) also recognized."""
        line = parse(parser, "旁白:夕阳把教室染成橙红色")
        assert line is not None
        assert line.speaker == "narrator"
        assert line.display_text == "夕阳把教室染成橙红色"

    def test_narrator_prefix_not_in_display(self, parser):
        """Frontend must never see the 旁白： marker."""
        line = parse(parser, "旁白：窗外下着淅淅沥沥的雨")
        assert "旁白" not in line.display_text
        assert "：" not in line.display_text

    def test_narrator_preserves_raw_text(self, parser):
        """raw_text keeps the full LLM output for KV-cache history."""
        raw = "旁白：三天后的早晨……"
        line = parse(parser, raw)
        assert line.raw_text == raw

    def test_narrator_empty_content_falls_through(self, parser):
        """旁白： (empty) — falls through to pure-action heuristic, not empty narrator."""
        line = parse(parser, "旁白：")
        # Empty content after prefix — should NOT produce a narrator with empty display
        if line is not None:
            assert line.display_text != ""  # either None or non-empty display

    def test_narrator_takes_priority_over_pure_action(self, parser):
        """旁白：（摔门）— explicit marker wins, tts_text = content (voiceable)."""
        line = parse(parser, "旁白：（摔门）")
        assert line is not None
        assert line.speaker == "narrator"
        # Explicit marker path: tts_text = "（摔门）" (the content after prefix)
        assert line.tts_text == "（摔门）"

    def test_halfwidth_paren_not_misrecognized(self, parser):
        """(action) halfwidth — NOT a narration marker, treated as dialogue."""
        line = parse(parser, "(hello there)")
        assert line is not None
        assert line.speaker != "narrator"  # not fullwidth （）, not 旁白： prefix


# ── TTS cleaning: strip parenthetical leakage ────────────────


class TestTTSCleaning:
    def test_strip_fullwidth_parens_from_tts(self, parser):
        """<你够了（摔门）> → tts_text="你够了" (parens stripped, action captured)."""
        line = parse(parser, "【生气】你够了<你够了（摔门）>")
        assert line is not None
        assert line.tts_text == "你够了"
        assert "摔门" in line.action  # stripped content goes to action field

    def test_strip_halfwidth_parens_from_tts(self, parser):
        """<hello (angry)> → tts_text="hello"."""
        line = parse(parser, "【angry】hello<hello (angry)>")
        assert line is not None
        assert line.tts_text == "hello"
        assert "angry" in line.action

    def test_strip_multiple_parens_from_tts(self, parser):
        """Multiple parentheticals all stripped."""
        line = parse(parser, "【test】hello<hello (angry) (loud)>")
        assert line is not None
        assert line.tts_text == "hello"

    def test_tts_empty_after_strip_retains_original(self, parser):
        """Safety net: if stripping empties tts_text, retain original."""
        line = parse(parser, "【test】text<（only parens）>")
        assert line is not None
        # Stripping leaves empty → retain original as safety net
        assert line.tts_text == "（only parens）"

    def test_no_parens_in_tts_unchanged(self, parser):
        """Clean TTS unchanged."""
        line = parse(parser, "【happy】hello<hello>")
        assert line is not None
        assert line.tts_text == "hello"

    def test_action_field_accumulates_stripped(self, parser):
        """Existing action + stripped parens merge with 、 separator."""
        line = parse(parser, "【shy】hi<hi (wave)>（blush）")
        assert line is not None
        assert line.tts_text == "hi"
        assert "wave" in line.action and "blush" in line.action
