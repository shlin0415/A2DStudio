"""Fanfiction chunker.

Splits a fanfiction .md into narrative chunks for staged A2D script generation.
Two split strategies:
  1. Stage-marker split: |<===Start of Stage_N===>| ... |<===End of Stage_N===>|
  2. Paragraph/scene split: double-newline paragraphs, merged to respect chunk_max_chars.

Each chunk records its source span (start_line, end_line, 1-indexed, inclusive)
so generated lines can be traced back to the original text for fidelity scoring.

Lesson references:
- BL-20260806-multi-segment-tts: regex boundary respect (<[^>]+> style, never .+? across
  boundaries), span tracking, guard conditions, empty-segment drop.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List


# Stage markers use the existing DETAIL-fanfiction convention.
# Opening:  |<===Start of Stage_N===>|
# Closing:  |<===End of Stage_N===>|
_STAGE_START = re.compile(r"\|<===Start of (Stage_\d+)===>\|")
_STAGE_END = re.compile(r"\|<===End of (Stage_\d+)===>\|")

# Paragraph boundary: one or more blank lines.
_BLANK_LINE = re.compile(r"^\s*$")


@dataclass
class Chunk:
    """One narrative chunk with source traceability."""

    chunk_id: int
    text: str
    start_line: int  # 1-indexed, inclusive
    end_line: int  # 1-indexed, inclusive
    stage_name: str | None = None  # e.g. "Stage_1" if from marker split
    meta: dict = field(default_factory=dict)


class Chunker:
    """Split fanfiction text into chunks with deterministic strategy."""

    def __init__(
        self,
        chunk_max_chars: int = 3000,
        respect_stage_markers: bool = True,
    ) -> None:
        if chunk_max_chars <= 0:
            raise ValueError(
                f"chunk_max_chars must be positive, got {chunk_max_chars}"
            )
        self.chunk_max_chars = chunk_max_chars
        self.respect_stage_markers = respect_stage_markers

    def split(self, text: str) -> List[Chunk]:
        """Split text into chunks. Strategy: stage markers first, else paragraphs."""
        if text is None or text.strip() == "":
            raise ValueError("fanfiction text is empty — nothing to chunk")

        if self.respect_stage_markers and self._has_stage_markers(text):
            return self._split_by_stage_markers(text)
        return self._split_by_paragraph(text)

    # ------------------------------------------------------------------
    # Stage-marker split
    # ------------------------------------------------------------------
    @staticmethod
    def _has_stage_markers(text: str) -> bool:
        return bool(_STAGE_START.search(text))

    def _split_by_stage_markers(self, text: str) -> List[Chunk]:
        """Split on |<===Start/End of Stage_N===>| marker pairs."""
        lines = text.split("\n")
        chunks: List[Chunk] = []

        current_stage: str | None = None
        current_start: int | None = None
        current_lines: List[str] = []
        chunk_id = 0

        for idx, line in enumerate(lines, start=1):
            m_start = _STAGE_START.match(line.strip())
            if m_start:
                # Begin a new stage block. If we were mid-stage without a close,
                # flush it defensively.
                if current_stage is not None and current_lines:
                    chunks.append(self._make_chunk(chunk_id, current_lines, current_start, idx - 1, current_stage))
                    chunk_id += 1
                current_stage = m_start.group(1)
                current_start = idx
                current_lines = []
                continue

            m_end = _STAGE_END.match(line.strip())
            if m_end:
                stage = m_end.group(1)
                if current_stage == stage and current_lines:
                    chunks.append(self._make_chunk(chunk_id, current_lines, current_start, idx, stage))
                    chunk_id += 1
                # Reset regardless — handles malformed nesting defensively.
                current_stage = None
                current_start = None
                current_lines = []
                continue

            if current_stage is not None:
                current_lines.append(line)

        # Flush trailing open stage.
        if current_stage is not None and current_lines:
            chunks.append(self._make_chunk(chunk_id, current_lines, current_start, len(lines), current_stage))

        return [c for c in chunks if c.text.strip()]

    # ------------------------------------------------------------------
    # Paragraph split
    # ------------------------------------------------------------------
    def _split_by_paragraph(self, text: str) -> List[Chunk]:
        """Split on blank-line paragraph boundaries, merging to respect chunk_max_chars."""
        lines = text.split("\n")
        paragraphs = self._collect_paragraphs(lines)
        return self._merge_paragraphs(paragraphs)

    def _collect_paragraphs(self, lines: List[str]) -> List[Chunk]:
        """Group non-blank runs into paragraph chunks with line spans."""
        paragraphs: List[Chunk] = []
        run: List[str] = []
        run_start: int | None = None
        chunk_id = 0

        for idx, line in enumerate(lines, start=1):
            if _BLANK_LINE.match(line):
                if run:
                    paragraphs.append(
                        self._make_chunk(chunk_id, run, run_start, idx - 1, None)
                    )
                    chunk_id += 1
                    run = []
                    run_start = None
                continue
            if run_start is None:
                run_start = idx
            run.append(line)

        if run:
            paragraphs.append(
                self._make_chunk(chunk_id, run, run_start, len(lines), None)
            )
        return [p for p in paragraphs if p.text.strip()]

    def _merge_paragraphs(self, paragraphs: List[Chunk]) -> List[Chunk]:
        """Merge adjacent paragraphs until chunk_max_chars would be exceeded."""
        if not paragraphs:
            return []

        merged: List[Chunk] = []
        buf = paragraphs[0]

        for nxt in paragraphs[1:]:
            candidate = buf.text + "\n\n" + nxt.text
            if len(candidate) <= self.chunk_max_chars:
                buf = Chunk(
                    chunk_id=buf.chunk_id,
                    text=candidate,
                    start_line=buf.start_line,
                    end_line=nxt.end_line,
                    stage_name=buf.stage_name,
                )
            else:
                merged.append(buf)
                buf = Chunk(
                    chunk_id=nxt.chunk_id,
                    text=nxt.text,
                    start_line=nxt.start_line,
                    end_line=nxt.end_line,
                    stage_name=nxt.stage_name,
                )
        merged.append(buf)

        # Re-id sequentially after merge.
        for i, c in enumerate(merged):
            c.chunk_id = i
        return merged

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _make_chunk(
        chunk_id: int,
        lines: List[str],
        start_line: int | None,
        end_line: int,
        stage_name: str | None,
    ) -> Chunk:
        return Chunk(
            chunk_id=chunk_id,
            text="\n".join(lines).strip(),
            start_line=start_line or 1,
            end_line=end_line,
            stage_name=stage_name,
        )
