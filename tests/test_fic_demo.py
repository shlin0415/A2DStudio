"""Tests for M4 demo + playable emitter (AC-6)."""

import asyncio
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from ling_chat.core.fic_demo import (
    emit_playable,
    evaluate_accuracy,
    load_ground_truth,
)


GROUND_TRUTH = Path("tmp/ref-article/ema-hiro-heart-groundtruth.json")
FIC = Path("tmp/ref-article/ema-hiro-heart.md")


# ---------------------------------------------------------------------------
# Ground-truth loader
# ---------------------------------------------------------------------------


class TestGroundTruth:
    def test_load_valid(self):
        if not GROUND_TRUTH.exists():
            pytest.skip("ground-truth fixture missing")
        gt = load_ground_truth(GROUND_TRUTH)
        assert "lines" in gt
        assert gt["lines"][0]["speaker"]

    def test_missing_required_field_errors(self, tmp_path: Path):
        """AC-6 negative: ground-truth line missing 'speaker' -> clear error."""
        bad = tmp_path / "bad.json"
        bad.write_text(
            json.dumps({"lines": [{"type": "dialogue"}]}), encoding="utf-8"
        )
        with pytest.raises(ValueError, match="missing required field"):
            load_ground_truth(bad)

    def test_missing_file_errors(self):
        with pytest.raises(FileNotFoundError):
            load_ground_truth(Path("tmp/does_not_exist.json"))


# ---------------------------------------------------------------------------
# playable emitter
# ---------------------------------------------------------------------------


class TestPlayable:
    def test_emit_schema(self, tmp_path: Path):
        lines = [
            {
                "speaker": "ema",
                "emotion": "高兴",
                "display_text": "你好",
                "tts_text": "こんにちは",
                "action": "笑う",
                "audio": "/audio/a2d_x.wav",
            },
            {
                "speaker": "narrator",
                "emotion": "",
                "display_text": "夕阳落下。",
                "tts_text": "夕阳落下。",
                "action": "",
                "audio": "",
            },
        ]
        out = tmp_path / "playable.json"
        emit_playable(lines, out, characters=["ema", "hiro"], topic="demo")
        data = json.loads(out.read_text(encoding="utf-8"))
        assert "header" in data and "lines" in data
        assert data["header"]["line_count"] == 2
        ln = data["lines"][0]
        for key in (
            "index",
            "character",
            "emotion",
            "text",
            "caption_text",
            "voice_text",
            "action",
            "fig_rel_path",
            "voice_rel_path",
        ):
            assert key in ln, f"missing playable line key: {key}"


# ---------------------------------------------------------------------------
# accuracy evaluation
# ---------------------------------------------------------------------------


class TestAccuracy:
    def _gt(self) -> dict:
        return {
            "lines": [
                {"speaker": "ema", "type": "dialogue"},
                {"speaker": "narrator", "type": "narration"},
                {"speaker": "hiro", "type": "dialogue"},
            ]
        }

    def test_perfect_accuracy(self):
        gen = [
            {"speaker": "ema"},
            {"speaker": "narrator"},
            {"speaker": "hiro"},
        ]
        acc = evaluate_accuracy(gen, self._gt())
        assert acc["speaker_accuracy"] == 1.0
        assert acc["type_accuracy"] == 1.0

    def test_type_inferred_from_speaker(self):
        gen = [
            {"speaker": "ema"},
            {"speaker": "narrator"},
            {"speaker": "unknown"},  # not narrator -> inferred dialogue
        ]
        acc = evaluate_accuracy(gen, self._gt())
        # speaker: 2/3 correct (ema, narrator match; unknown != hiro)
        assert acc["speaker_accuracy"] == pytest.approx(2 / 3)
        # type: ema=dialogue ok, narrator=narration ok, unknown=dialogue ok
        assert acc["type_accuracy"] == 1.0


# ---------------------------------------------------------------------------
# AC-6 end-to-end demo smoke test (would have caught the B1 crash)
# ---------------------------------------------------------------------------


class TestDemoEndToEnd:
    @pytest.mark.skipif(
        not FIC.exists() or not GROUND_TRUTH.exists(),
        reason="demo fixtures missing",
    )
    def test_demo_end_to_end(self, tmp_path: Path):
        """Run run_demo with a multi-line scripted mock (F2).

        The mock emits a sequence matching the ground-truth's alternating
        narrator/ema/hiro lines, so the >=80% thresholds are meaningful
        (not trivially 100% from a single line).
        """
        from ling_chat.core.fic_pipeline import run_demo

        # Match the ground-truth sequence exactly (10 lines):
        # [narrator, narrator, narrator, ema, hiro, ema, hiro, narrator, hiro, ema]
        # so the >=80% accuracy thresholds are meaningful and pass.
        RESPONSES = [
            "旁白：那是一个平凡的早晨。",  # narrator/narration (GT line 0)
            "旁白：二阶堂希罗最近感觉自己有一些奇怪的变化。",  # narrator (GT line 1)
            "旁白：那是一个平凡的早晨，两个人约好一起去上学。",  # narrator (GT line 2)
            '{"speaker":"ema"}\n【高兴】希罗，久等了！<久等了！>（跑来）',  # ema (GT line 3)
            '{"speaker":"hiro"}\n【害羞】艾玛，今天还算早。<今日は早いね。>',  # hiro (GT line 4)
            '{"speaker":"ema"}\n【开心】嘿嘿，不能让希罗酱久等啊。<待たせないね。>',  # ema (GT line 5)
            '{"speaker":"hiro"}\n【认真】走吧。<行こう。>（伸手）',  # hiro (GT line 6)
            "旁白：希罗伸手抓住了艾玛的左手。",  # narrator (GT line 7)
            '{"speaker":"hiro"}\n【疑惑】你刚才说什么？<何？>',  # hiro (GT line 8)
            '{"speaker":"ema"}\n【慌张】啊？我没说话呀。<ううん、何も。>',  # ema (GT line 9)
        ]
        counter = {"i": 0}

        async def _fake_call(self, messages):
            idx = counter["i"] % len(RESPONSES)
            counter["i"] += 1
            return RESPONSES[idx]

        with patch(
            "ling_chat.core.fic_runtime.FicRuntime._call_llm", _fake_call
        ):
            rc = run_demo(tmp_path, seed=42)

        assert rc == 0, f"run_demo exited with rc={rc}"
        assert (tmp_path / "playable.json").exists()
        manifest = json.loads(
            (tmp_path / "fic_manifest.json").read_text(encoding="utf-8")
        )
        assert manifest["line_count"] >= 10, (
            f"AC-6 requires >=10 alternating lines, got {manifest['line_count']}"
        )
