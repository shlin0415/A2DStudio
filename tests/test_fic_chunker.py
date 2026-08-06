"""Tests for fanfiction chunker (AC-1)."""

import pytest

from ling_chat.core.fic_chunker import Chunker


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MULTI_STAGE = """\
|<===Start of Stage_1===>|
希罗今天听见了艾玛的心声。
"希罗酱，久等了！"

艾玛跑过来。
|<===End of Stage_1===>|
|<===Start of Stage_2===>|
两人牵手走在路上。

雨下了起来。
|<===End of Stage_2===>|
"""

NO_MARKER = """\
希罗今天听见了艾玛的心声。

"希罗酱，久等了！"艾玛跑过来。

两人牵手走在路上。

雨下了起来，希罗把伞往艾玛那边倾。

"没事。"希罗说。
"""


# ---------------------------------------------------------------------------
# AC-1 Positive
# ---------------------------------------------------------------------------

class TestStageMarkerSplit:
    def test_splits_on_stage_markers(self):
        c = Chunker()
        chunks = c.split(MULTI_STAGE)
        assert len(chunks) == 2
        assert chunks[0].stage_name == "Stage_1"
        assert chunks[1].stage_name == "Stage_2"

    def test_stage_chunk_records_span(self):
        c = Chunker()
        chunks = c.split(MULTI_STAGE)
        # Stage_1 block starts at line 1 (the Start marker line).
        assert chunks[0].start_line == 1
        # Each chunk has a non-empty text payload.
        assert chunks[0].text.strip() != ""

    def test_empty_tags_dropped(self):
        """A stage block with only whitespace yields no chunk."""
        text = (
            "|<===Start of Stage_1===>|\n"
            "|<===End of Stage_1===>|\n"
        )
        c = Chunker()
        chunks = c.split(text)
        assert chunks == []


class TestParagraphSplit:
    def test_greedy_merge_fewest_chunks(self):
        """Greedy merge combines short paragraphs: huge max -> 1 chunk."""
        c = Chunker(chunk_max_chars=10_000)
        chunks = c.split(NO_MARKER)
        # All 5 short paragraphs merge into a single chunk under a huge max.
        assert len(chunks) == 1
        assert chunks[0].start_line == 1
        assert chunks[0].end_line == 9

    def test_paragraph_chunk_has_span(self):
        c = Chunker(chunk_max_chars=10_000)
        chunks = c.split(NO_MARKER)
        for ch in chunks:
            assert ch.start_line >= 1
            assert ch.end_line >= ch.start_line

    def test_merges_under_chunk_max_chars(self):
        """Smaller max -> more chunks; larger max -> fewer (greedy merge)."""
        c_small = Chunker(chunk_max_chars=40)
        c_large = Chunker(chunk_max_chars=10_000)
        small = c_small.split(NO_MARKER)
        large = c_large.split(NO_MARKER)
        assert len(small) >= len(large)
        assert len(large) == 1  # huge max merges all short paragraphs
        # tight max (40 chars) splits into 2 chunks (each ~38 chars, 2-3 paras each)
        assert len(small) == 2

    def test_respects_chunk_max_chars_hard(self):
        """No chunk exceeds chunk_max_chars."""
        c = Chunker(chunk_max_chars=30)
        chunks = c.split(NO_MARKER)
        for ch in chunks:
            assert len(ch.text) <= 30


# ---------------------------------------------------------------------------
# AC-1 Negative
# ---------------------------------------------------------------------------

class TestNegative:
    def test_empty_input_raises(self):
        c = Chunker()
        with pytest.raises(ValueError, match="empty"):
            c.split("")

    def test_whitespace_only_raises(self):
        c = Chunker()
        with pytest.raises(ValueError, match="empty"):
            c.split("   \n\n  \n")

    def test_invalid_chunk_max_chars(self):
        with pytest.raises(ValueError, match="chunk_max_chars"):
            Chunker(chunk_max_chars=0)
        with pytest.raises(ValueError, match="chunk_max_chars"):
            Chunker(chunk_max_chars=-5)
