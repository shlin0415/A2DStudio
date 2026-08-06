"""M4: end-to-end demo + playable.json emitter (AC-6)."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional


logger = logging.getLogger(__name__)


def load_ground_truth(path: Path) -> dict:
    """Load + validate a ground-truth annotation file (AC-6 negative)."""
    if not path.exists():
        raise FileNotFoundError(f"ground-truth file not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if "lines" not in data or not data["lines"]:
        raise ValueError(f"ground-truth file missing 'lines': {path}")
    for i, entry in enumerate(data["lines"]):
        for key in ("speaker", "type"):
            if key not in entry:
                raise ValueError(
                    f"ground-truth line {i} missing required field '{key}': {path}"
                )
    return data


def emit_playable(
    lines: List[dict],
    output_path: Path,
    characters: Optional[List[str]] = None,
    topic: str = "fanfiction",
) -> None:
    """Emit a playable.json mirroring the A2D replay format.

    Each line dict needs: speaker/emotion/display_text/tts_text/action/audio.
    """
    characters = characters or sorted(
        {ln.get("speaker", "narrator") for ln in lines}
    )
    header = {
        "characters": characters,
        "character_count": len(characters),
        "topic": topic,
        "language": "zh",
        "emotion_count": 18,
        "line_count": len(lines),
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "format_version": "2.0",
        "format_description": "fanfiction-to-script pipeline output",
    }
    out_lines = []
    for i, ln in enumerate(lines):
        speaker = ln.get("speaker", "narrator")
        emotion = ln.get("emotion", "")
        caption = ln.get("display_text", "")
        voice = ln.get("tts_text", "")
        action = ln.get("action", "")
        audio = ln.get("audio", "")
        out_lines.append(
            {
                "index": i,
                "character": speaker,
                "emotion": emotion,
                "text": caption,
                "caption_text": caption,
                "voice_text": voice,
                "action": action,
                "fig_rel_path": f"figs/{speaker}/{emotion or 'default'}.png",
                "voice_rel_path": audio if audio else None,
            }
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(
            {"header": header, "lines": out_lines},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def evaluate_accuracy(
    generated_lines: List[dict],
    ground_truth: dict,
) -> dict:
    """Compare generated speaker/narration labels vs ground truth (AC-6).

    Returns per-axis accuracy. A generated line matches a ground-truth line by
    position index (1:1 alignment expected for the demo excerpt).
    """
    gt_lines = ground_truth["lines"]
    n = min(len(generated_lines), len(gt_lines))
    if n == 0:
        return {"speaker_accuracy": 0.0, "type_accuracy": 0.0, "matched": 0, "total": 0}

    speaker_ok = 0
    type_ok = 0
    for i in range(n):
        gen = generated_lines[i]
        gt = gt_lines[i]
        if (gen.get("speaker") or "").lower() == (gt.get("speaker") or "").lower():
            speaker_ok += 1
        # type: narration vs dialogue inferred from speaker == narrator.
        gen_type = "narration" if (gen.get("speaker") == "narrator") else "dialogue"
        if gen_type == gt.get("type", ""):
            type_ok += 1

    return {
        "speaker_accuracy": speaker_ok / n,
        "type_accuracy": type_ok / n,
        "matched": n,
        "total": len(gt_lines),
    }
