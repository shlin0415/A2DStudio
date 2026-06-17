"""测试 SessionRuntime — epoch 编辑 + scene config"""
import pytest
from ling_chat.core.session_runtime import SessionRuntime
from ling_chat.schemas.script_overlay import ScriptLine


def make_sr():
    """创建 SessionRuntime 实例"""
    return SessionRuntime()


class TestScriptLines:
    def test_add_line_sets_index(self):
        sr = make_sr()
        sr.add_line(ScriptLine(speaker="ema", display_text="hello"))
        assert len(sr.script_lines) == 1
        assert sr.script_lines[0].index == 0

    def test_add_multiple_lines(self):
        sr = make_sr()
        sr.add_line(ScriptLine(speaker="ema", display_text="a"))
        sr.add_line(ScriptLine(speaker="hiro", display_text="b"))
        assert len(sr.script_lines) == 2
        assert sr.script_lines[1].index == 1

    def test_lines_get_current_epoch(self):
        sr = make_sr()
        sr.generation_epoch = 5
        sr.add_line(ScriptLine(speaker="ema", display_text="test"))
        assert sr.script_lines[0].generation_epoch == 5


class TestEpochAndPause:
    @pytest.mark.asyncio
    async def test_handle_continue_increments_epoch(self):
        sr = make_sr()
        epoch = await sr.handle_continue("gen-1")
        assert epoch == 1

    def test_default_mode_is_auto(self):
        sr = make_sr()
        assert sr.mode == "auto"

    def test_pause_state(self):
        sr = make_sr()
        assert sr.paused is False
        sr.paused = True
        assert sr.paused is True


class TestSceneConfig:
    def test_default_scene(self):
        sr = make_sr()
        assert sr.scene_config.scene_description == ""

    def test_update_scene(self):
        sr = make_sr()
        sr.update_scene("雨夜回家", "睡前轻语", None)
        assert sr.scene_config.scene_description == "雨夜回家"
        assert sr.scene_config.dialogue_style == "睡前轻语"

    def test_build_scene_prompt_free_style(self):
        sr = make_sr()
        sr.update_scene("测试场景", "自由对话", None)
        suffix = sr.build_scene_prompt_suffix()
        assert "测试场景" in suffix

    def test_build_scene_prompt_asmr_style(self):
        sr = make_sr()
        sr.update_scene("测试场景", "睡前轻语", None)
        suffix = sr.build_scene_prompt_suffix()
        has_quiet = "低语" in suffix or "缓慢" in suffix or "轻声" in suffix
        assert has_quiet, f"Expected quiet keyword in: {suffix}"

    def test_build_scene_prompt_with_material(self):
        sr = make_sr()
        sr.update_scene("测试", "同人演绎", "原作第3章")
        suffix = sr.build_scene_prompt_suffix()
        assert "原作第3章" in suffix


class TestEditProtocol:
    """AC-1: Verify edit protocol fix — frontend [{id, text}] format is applied."""

    @pytest.mark.asyncio
    async def test_edit_single_line_updates_text(self):
        """User edits one line → display_text and tts_text are updated."""
        sr = make_sr()
        line1 = ScriptLine(speaker="ema", display_text="original ema text")
        line2 = ScriptLine(speaker="hiro", display_text="original hiro text")
        sr.add_line(line1)
        sr.add_line(line2)

        await sr.handle_continue("gen-1", edits=[
            {"id": line1.id, "text": "edited ema text"},
        ])

        assert len(sr.script_lines) == 1  # line2 truncated
        assert sr.script_lines[0].display_text == "edited ema text"
        assert sr.script_lines[0].tts_text == "edited ema text"
        assert sr.script_lines[0].speaker == "ema"  # speaker preserved from original

    @pytest.mark.asyncio
    async def test_continue_without_edits_no_truncation(self):
        """Continue without edits → no changes to script_lines."""
        sr = make_sr()
        sr.add_line(ScriptLine(speaker="ema", display_text="hello"))
        sr.add_line(ScriptLine(speaker="hiro", display_text="world"))

        await sr.handle_continue("gen-1", edits=None)

        assert len(sr.script_lines) == 2  # nothing truncated

    @pytest.mark.asyncio
    async def test_continue_with_empty_edits_no_truncation(self):
        """Empty edits list → _apply_edits skipped, lines preserved."""
        sr = make_sr()
        sr.add_line(ScriptLine(speaker="ema", display_text="hello"))

        await sr.handle_continue("gen-1", edits=[])

        assert len(sr.script_lines) == 1

    @pytest.mark.asyncio
    async def test_unknown_line_id_no_crash(self):
        """Edit with unknown line id → no crash, original kept, edit appended."""
        sr = make_sr()
        sr.add_line(ScriptLine(speaker="ema", display_text="hello"))

        await sr.handle_continue("gen-1", edits=[
            {"id": "nonexistent-id", "text": "ghost edit"},
        ])

        # Unknown id causes _find_line_index to return len(script_lines)=1
        # truncate [:1] keeps original, then edit is appended → 2 lines
        assert len(sr.script_lines) == 2
        assert sr.script_lines[0].display_text == "hello"  # original kept
        assert sr.script_lines[1].display_text == "ghost edit"

    @pytest.mark.asyncio
    async def test_edit_truncates_subsequent_lines(self):
        """Editing line 2 of 4 → lines 3-4 are discarded."""
        sr = make_sr()
        lines = [
            ScriptLine(speaker="ema", display_text="l1"),
            ScriptLine(speaker="hiro", display_text="l2"),
            ScriptLine(speaker="ema", display_text="l3"),
            ScriptLine(speaker="hiro", display_text="l4"),
        ]
        for ln in lines:
            sr.add_line(ln)

        await sr.handle_continue("gen-1", edits=[
            {"id": lines[1].id, "text": "edited l2"},
        ])

        assert len(sr.script_lines) == 2  # l1 + edited l2
        assert sr.script_lines[0].display_text == "l1"
        assert sr.script_lines[1].display_text == "edited l2"
