"""Lightweight preprocessor that strips JSON speaker markers from LLM output
before passing to LingChat's StreamProducer.

LLM format:
  {"speaker":"ema"}
  【高兴】今日はいい天気だね<TTS>（動作）
  {"speaker":"hiro"}
  【微笑】本当、気持ちいいね<TTS>（うなずく）

The preprocessor strips the JSON line and records the current speaker.
StreamProducer receives only the 【情绪】 lines (unchanged LingChat format).
"""

import json
import re
from typing import AsyncGenerator

SPEAKER_MARKER_RE = re.compile(r'^\s*\{\s*"speaker"\s*:\s*"(\w+)"\s*\}\s*$')


def strip_speaker_marker(line: str) -> tuple[str | None, str]:
    """Check if a line is a speaker marker. Return (speaker, remaining_text).

    If the line IS a speaker marker → (speaker_id, "")
    If the line CONTAINS a speaker marker → (speaker_id, rest_of_line)
    If no marker → (None, line)
    """
    m = SPEAKER_MARKER_RE.match(line)
    if m:
        return m.group(1), ""

    # Check for inline marker: {"speaker":"ema"}【高兴】...
    inline = re.match(
        r'^\s*\{\s*"speaker"\s*:\s*"(\w+)"\s*\}\s*(.+)$', line
    )
    if inline:
        return inline.group(1), inline.group(2)

    return None, line


async def preprocess_llm_stream(
    raw_stream: AsyncGenerator[str, None],
) -> AsyncGenerator[tuple[str | None, str], None]:
    """Async generator wrapper: strips speaker markers from LLM stream chunks.

    Yields (speaker_change, text_chunk) tuples.
    speaker_change is None unless a new speaker marker was encountered.
    """
    buffer = ""
    current_speaker: str | None = None

    async for chunk in raw_stream:
        buffer += chunk

        # Process complete lines
        while "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            speaker, clean = strip_speaker_marker(line)
            if speaker:
                current_speaker = speaker
            elif clean.strip():
                yield (current_speaker, clean + "\n")

    # Flush remaining buffer
    if buffer.strip():
        speaker, clean = strip_speaker_marker(buffer)
        if speaker:
            current_speaker = speaker
            if clean.strip():
                yield (current_speaker, clean)
        else:
            yield (current_speaker, buffer)
