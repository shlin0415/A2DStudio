"""测试 SessionRuntime — epoch 编辑 + scene config + Stage + 序列化"""
import time
import pytest
from ling_chat.core.session_runtime import SessionRuntime
from ling_chat.schemas.script_overlay import ScriptLine, Stage, LineOverlay, TextOverlay


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


class TestStage:
    def test_stage_creation(self):
        stage = Stage(title="第一幕", order=0)
        assert stage.title == "第一幕"
        assert stage.order == 0
        assert stage.line_ids == []
        assert stage.default_background == ""
        assert stage.id  # auto-generated

    def test_assign_line_to_stage(self):
        sr = make_sr()
        stage = Stage(title="test")
        sr.stages.append(stage)
        line = ScriptLine(speaker="ema", display_text="hello")
        sr.add_line(line)
        sr.assign_line_to_stage(line.id, stage.id)
        assert line.stage_id == stage.id
        assert line.id in stage.line_ids

    def test_get_line_stage(self):
        sr = make_sr()
        stage = Stage(title="test")
        sr.stages.append(stage)
        line = ScriptLine(speaker="ema", display_text="hello")
        sr.add_line(line)
        sr.assign_line_to_stage(line.id, stage.id)
        found = sr.get_line_stage(line.id)
        assert found is not None
        assert found.id == stage.id

    def test_assign_line_to_nonexistent_stage(self):
        sr = make_sr()
        line = ScriptLine(speaker="ema", display_text="hello")
        sr.add_line(line)
        sr.assign_line_to_stage(line.id, "nonexistent")
        assert line.stage_id == ""  # unchanged

    def test_stage_ordering(self):
        sr = make_sr()
        s1 = Stage(title="s1", order=1)
        s2 = Stage(title="s2", order=0)
        sr.stages.extend([s1, s2])
        ordered = sorted(sr.stages, key=lambda s: s.order)
        assert ordered[0].title == "s2"
        assert ordered[1].title == "s1"


class TestBackgroundPriority:
    def test_line_background_over_stage(self):
        sr = make_sr()
        stage = Stage(title="test", default_background="stage_bg.png")
        sr.stages.append(stage)
        line = ScriptLine(
            speaker="ema",
            display_text="hello",
            stage_id=stage.id,
            overlay=LineOverlay(background="line_bg.png"),
        )
        sr.add_line(line)
        bg = sr.get_background_for_line(line.id)
        assert bg == "line_bg.png"

    def test_stage_background_when_line_empty(self):
        sr = make_sr()
        stage = Stage(title="test", default_background="stage_bg.png")
        sr.stages.append(stage)
        line = ScriptLine(
            speaker="ema",
            display_text="hello",
            stage_id=stage.id,
            overlay=LineOverlay(),
        )
        sr.add_line(line)
        bg = sr.get_background_for_line(line.id)
        assert bg == "stage_bg.png"

    def test_empty_background(self):
        sr = make_sr()
        line = ScriptLine(speaker="ema", display_text="hello")
        sr.add_line(line)
        bg = sr.get_background_for_line(line.id)
        assert bg == ""


class TestLineOverlay:
    def test_image_overlays(self):
        overlay = LineOverlay(image_overlays=[
            {"id": "img1", "path": "img.png", "x": 10, "y": 20, "w": 100, "h": 100, "opacity": 1.0, "z": 0}
        ])
        assert len(overlay.image_overlays) == 1
        assert overlay.image_overlays[0]["path"] == "img.png"

    def test_bgm_fields(self):
        overlay = LineOverlay(bgm="bgm.mp3", bgm_volume=0.5, bgm_loop=False)
        assert overlay.bgm == "bgm.mp3"
        assert overlay.bgm_volume == 0.5
        assert overlay.bgm_loop is False

    def test_text_overlay_percentage_coords(self):
        overlay = LineOverlay(text_overlays=[
            TextOverlay(text="Hello", x=50.0, y=30.0, font_size=24)
        ])
        assert overlay.text_overlays[0].x == 50.0
        assert overlay.text_overlays[0].y == 30.0


class TestSerialization:
    def test_to_dict_roundtrip(self):
        sr = make_sr()
        stage = Stage(title="test", order=0)
        sr.stages.append(stage)
        line = ScriptLine(
            speaker="ema",
            display_text="hello",
            tts_text="hello_tts",
            emotion="happy",
            stage_id=stage.id,
            overlay=LineOverlay(
                background="bg.png",
                text_overlays=[TextOverlay(text="Hi", x=10, y=20)],
                image_overlays=[{"id": "i1", "path": "img.png"}],
                bgm="bgm.mp3",
            ),
            audio_path="audio/test.wav",
        )
        sr.add_line(line)
        stage.line_ids.append(line.id)

        data = sr.to_dict()
        assert data["version"] == 1
        assert len(data["stages"]) == 1
        assert len(data["script_lines"]) == 1
        assert data["script_lines"][0]["stage_id"] == stage.id
        assert data["script_lines"][0]["overlay"]["bgm"] == "bgm.mp3"

        # Round-trip
        sr2 = SessionRuntime.from_dict(data)
        assert len(sr2.stages) == 1
        assert len(sr2.script_lines) == 1
        assert sr2.script_lines[0].id == line.id
        assert sr2.script_lines[0].stage_id == stage.id
        assert sr2.script_lines[0].overlay.bgm == "bgm.mp3"
        assert sr2.script_lines[0].overlay.text_overlays[0].text == "Hi"
        assert sr2.stages[0].title == "test"

    def test_backward_compat_v0(self):
        """v0 JSON (no version, no stages) should load with default stage."""
        v0_data = {
            "script_lines": [
                {"id": "l1", "speaker": "ema", "display_text": "hello"},
            ]
        }
        sr = SessionRuntime.from_dict(v0_data)
        assert len(sr.script_lines) == 1
        assert len(sr.stages) == 1  # auto-created default
        assert sr.stages[0].title == "默认阶段"
        assert sr.script_lines[0].stage_id == sr.stages[0].id

    def test_invalid_version_raises(self):
        """AC-3 Negative: unsupported version should raise ValueError."""
        data = {"version": 99, "script_lines": []}
        with pytest.raises(ValueError, match="Unsupported session format version"):
            SessionRuntime.from_dict(data)

    def test_roundtrip_preserves_all_fields(self):
        """AC-3: roundtrip must preserve original_audio_path + overlay fields."""
        sr = make_sr()
        stage = Stage(title="test")
        sr.stages.append(stage)
        line = ScriptLine(
            speaker="ema",
            display_text="hello",
            stage_id=stage.id,
            audio_path="audio/a.wav",
            original_audio_path="audio/orig.wav",
            overlay=LineOverlay(
                character_id=1,
                ref_audio_path="ref.wav",
                gsv_params={"speed": 1.0},
                sprite_positions={"ema": {"x": 0, "y": 0}},
            ),
        )
        sr.add_line(line)
        stage.line_ids.append(line.id)
        sr2 = SessionRuntime.from_dict(sr.to_dict())
        assert sr2.script_lines[0].original_audio_path == "audio/orig.wav"
        assert sr2.script_lines[0].overlay.character_id == 1
        assert sr2.script_lines[0].overlay.ref_audio_path == "ref.wav"
        assert sr2.script_lines[0].overlay.gsv_params == {"speed": 1.0}
        assert sr2.script_lines[0].overlay.sprite_positions == {"ema": {"x": 0, "y": 0}}

    def test_performance_1000_lines(self):
        """AC-3: 1000 lines + 10 stages serialization < 100ms, deserialization < 200ms."""
        sr = make_sr()
        for s_idx in range(10):
            sr.stages.append(Stage(title=f"stage_{s_idx}", order=s_idx))
        for i in range(1000):
            line = ScriptLine(speaker="ema", display_text=f"line_{i}", stage_id=sr.stages[i % 10].id)
            sr.add_line(line)
            sr.stages[i % 10].line_ids.append(line.id)
        start = time.time()
        data = sr.to_dict()
        serialize_ms = (time.time() - start) * 1000
        start = time.time()
        SessionRuntime.from_dict(data)
        deserialize_ms = (time.time() - start) * 1000
        assert serialize_ms < 100, f"Serialization took {serialize_ms:.1f}ms"
        assert deserialize_ms < 200, f"Deserialization took {deserialize_ms:.1f}ms"


class TestEditCleanup:
    """AC-1.1: _apply_edits() must clean up dangling stage.line_ids."""
    def test_apply_edits_cleans_stage_line_ids(self):
        sr = make_sr()
        stage = Stage(title="test")
        sr.stages.append(stage)
        for i in range(5):
            line = ScriptLine(speaker="ema", display_text=f"line_{i}", stage_id=stage.id)
            sr.add_line(line)
            stage.line_ids.append(line.id)
        assert len(stage.line_ids) == 5
        # Edit first existing line → truncates to index 0 + 1 edited = 1 line, stage cleaned
        sr._apply_edits([{"id": sr.script_lines[0].id, "text": "edited"}])
        assert len(sr.script_lines) == 1
        # Stage.line_ids should only contain IDs still in script_lines
        valid_ids = {l.id for l in sr.script_lines}
        for lid in stage.line_ids:
            assert lid in valid_ids, f"Stage has dangling ref {lid}"


class TestStageAssignment:
    def test_same_line_cannot_belong_to_multiple_stages(self):
        """AC-1 Negative: same line assigned to multiple stages should be prevented."""
        sr = make_sr()
        s1 = Stage(title="s1")
        s2 = Stage(title="s2")
        sr.stages.extend([s1, s2])
        line = ScriptLine(speaker="ema", display_text="hello")
        sr.add_line(line)
        sr.assign_line_to_stage(line.id, s1.id)
        sr.assign_line_to_stage(line.id, s2.id)
        assert line.stage_id == s2.id
        assert line.id in s2.line_ids
        assert line.id not in s1.line_ids  # removed from old stage


class TestTextOverlayValidation:
    def test_coords_out_of_range_raises(self):
        """AC-2 Negative: coords outside 0-100 should raise ValueError."""
        with pytest.raises(ValueError, match="coords must be 0-100"):
            TextOverlay(x=150.0, y=30.0)
        with pytest.raises(ValueError, match="coords must be 0-100"):
            TextOverlay(x=50.0, y=-10.0)

    def test_coords_valid_range(self):
        """AC-2 Positive: coords within 0-100 should be accepted."""
        t = TextOverlay(x=0.0, y=0.0)
        assert t.x == 0.0
        t2 = TextOverlay(x=100.0, y=100.0)
        assert t2.x == 100.0


class TestEpochAndPause:
    @pytest.mark.asyncio
    async def test_handle_continue_increments_epoch(self):
        sr = make_sr()
        epoch = await sr.handle_continue("gen-1")
        assert epoch == 1

    def test_default_mode_is_auto(self):
        sr = make_sr()
        assert sr.mode == "auto"
