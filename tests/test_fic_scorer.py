"""Tests for fidelity scorers (AC-5)."""

import pytest

from ling_chat.core.fic_chunker import Chunker
from ling_chat.core.fic_scorer import EmbeddingScorer, score_chunks


# ---------------------------------------------------------------------------
# AC-5 positive
# ---------------------------------------------------------------------------


class TestEmbeddingScorer:
    def test_identical_text_scores_one(self):
        s = EmbeddingScorer()
        assert s.score("希罗听见了艾玛的心声", "希罗听见了艾玛的心声") == pytest.approx(1.0)

    def test_similar_text_scores_higher_than_dissimilar(self):
        s = EmbeddingScorer()
        similar = s.score("希罗听见了艾玛的心声。", "希罗听见了艾玛的心声！")
        different = s.score("希罗听见了艾玛的心声", "今天天气真好啊")
        assert similar > different

    def test_score_deterministic(self):
        """AC-5 positive: same input twice -> delta ≈ 0 (here exactly equal)."""
        s = EmbeddingScorer()
        a = s.score("abc", "abd")
        b = s.score("abc", "abd")
        assert a == b  # exact determinism (no randomness)

    def test_score_bounded_0_1(self):
        s = EmbeddingScorer()
        for src, gen in [("a", "b"), ("", "x"), ("x", ""), ("希罗", "艾玛")]:
            v = s.score(src, gen)
            assert 0.0 <= v <= 1.0

    def test_empty_input_returns_zero(self):
        s = EmbeddingScorer()
        assert s.score("", "something") == 0.0
        assert s.score("something", "") == 0.0


# ---------------------------------------------------------------------------
# score_chunks aggregation
# ---------------------------------------------------------------------------


class TestScoreChunks:
    def _chunks(self) -> list:
        # Two paragraphs, each long enough to be its own chunk under a small max.
        text = ("希罗听见了艾玛的心声，站在路口等她。" * 60) + "\n\n" + (
            "艾玛跑过来，笑着喊了一声希罗酱。" * 60
        )
        return Chunker(chunk_max_chars=500).split(text)

    def test_aggregate_schema(self):
        chunks = self._chunks()
        assert len(chunks) >= 2
        lines = [
            {"chunk_id": chunks[0].chunk_id, "display_text": "希罗听见了艾玛的心声"},
            {"chunk_id": chunks[1].chunk_id, "display_text": "艾玛跑过来"},
        ]
        report = score_chunks(chunks, lines)
        assert "overall" in report
        assert "per_chunk" in report
        assert report["scorer"] == "EmbeddingScorer"
        assert report["chunk_count"] == 2

    def test_missing_source_span_skips_with_warning(self, caplog):
        """AC-5 negative: chunk with no source span -> skipped, not fabricated."""
        chunks = self._chunks()
        lines = [
            {"chunk_id": 0, "display_text": "希罗听见了艾玛的心声"},
            {"chunk_id": 99, "display_text": "no source for this"},  # no such chunk
        ]
        report = score_chunks(chunks, lines)
        # chunk 99 has no matching source -> skipped.
        assert report["chunk_count"] == 1
        assert any("missing source" in m or "skipping" in m for m in caplog.messages)


# ---------------------------------------------------------------------------
# AC-5 negative: CER/WER exclusion (locked in by test, not comment)
# ---------------------------------------------------------------------------


class TestNoCerWer:
    def test_scorer_module_does_not_import_cer_wer(self):
        """AC-5 negative: fidelity scorer must not use CER/WER."""
        import inspect

        from ling_chat.core import fic_scorer

        src = inspect.getsource(fic_scorer)
        assert "jiwer" not in src, "scorer must not import jiwer"
        # compute_metrics is the CER/WER function in a2d_asr_eval — must not be used here.
        assert "compute_metrics" not in src, "scorer must not use compute_metrics (CER/WER)"
