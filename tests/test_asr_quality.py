"""ASR quality regression guard (opt-in via -m slow).

Requires:
  - Full stack running (backend + frontend + GSV)
  - A dialogue already triggered (window.__a2dTrace populated)
  - asr-env venv with faster-whisper installed

Threshold: env A2D_ASR_CER_THRESHOLD (default 0.1).

Usage:
  A2D_ASR_CER_THRESHOLD=0.15 uv run pytest tests/test_asr_quality.py -m slow -v
"""

import os
import sys

import pytest

# Skip entire module if faster-whisper not available
pytest.importorskip("faster_whisper")
pytest.importorskip("jiwer")


@pytest.mark.slow
@pytest.mark.e2e
@pytest.mark.asyncio
async def test_asr_cer_under_threshold():
    """TraceHook mode: average CER must be under threshold."""
    from tests.a2d_asr_eval import run_asr_eval

    threshold = float(os.environ.get("A2D_ASR_CER_THRESHOLD", "0.1"))
    result = await run_asr_eval(
        capture="trace_hook",
        use_cache=True,
        batch_size=int(os.environ.get("A2D_ASR_BATCH_SIZE", "10")),
    )

    avg_cer = result["avg_cer"]
    assert avg_cer < threshold, (
        f"Average CER {avg_cer:.2%} >= threshold {threshold:.2%}. "
        f"Check {os.environ.get('A2D_ASR_OUTPUT', 'tmp/asr_eval')}/report.md for details."
    )


@pytest.mark.slow
@pytest.mark.e2e
@pytest.mark.asyncio
async def test_asr_no_empty_transcriptions():
    """All samples should produce non-empty ASR output (no silent/failed audio)."""
    from tests.a2d_asr_eval import TraceHookCapture, DEFAULT_OUTPUT
    import json

    output = DEFAULT_OUTPUT
    capturer = TraceHookCapture(output_dir=output)
    samples = await capturer.capture(use_cache=True)

    if not samples:
        pytest.skip("No trace data — run a dialogue first")

    # Check per-sample results exist and have non-empty asr
    failures = []
    for s in samples:
        json_path = output / "samples" / f"{s.line_id}.json"
        if not json_path.exists():
            failures.append(f"{s.line_id}: missing json")
            continue
        data = json.loads(json_path.read_text(encoding="utf-8"))
        if not data.get("text_asr"):
            failures.append(f"{s.line_id}: empty transcription")

    assert not failures, f"Empty/missing transcriptions: {failures}"
