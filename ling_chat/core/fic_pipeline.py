"""Fanfiction-to-script pipeline orchestrator (offline, no frontend/WS).

Stands up its own LLM provider + GSV adapter + SessionRuntime outside the
web-server lifecycle (the real engineering constraint, per plan deliberation).

Round 0 scope: CLI + chunker wiring + dry-run preview.
Later rounds (M2-M4) wire generation / synthesis / evaluation into run().
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
from pathlib import Path
from typing import List, Optional

from ling_chat.core.fic_chunker import Chunk, Chunker

_ASYNC_LOOP: Optional[asyncio.AbstractEventLoop] = None


def _run(coro):
    """Run a coroutine in a persistent event loop (GSV model loading needs a live loop)."""
    global _ASYNC_LOOP
    if _ASYNC_LOOP is None or _ASYNC_LOOP.is_closed():
        _ASYNC_LOOP = asyncio.new_event_loop()
    return _ASYNC_LOOP.run_until_complete(coro)


def _load_text(input_path: Path) -> str:
    if not input_path.exists():
        print(f"error: input not found: {input_path}", file=sys.stderr)
        sys.exit(1)
    return input_path.read_text(encoding="utf-8")


def _preview_chunks(chunks: List[Chunk]) -> None:
    print(f"\n=== Chunk preview ({len(chunks)} chunks) ===\n")
    for ch in chunks:
        stage = f" [{ch.stage_name}]" if ch.stage_name else ""
        head = ch.text.replace("\n", " ")[:60]
        print(
            f"  chunk {ch.chunk_id}{stage}  "
            f"lines {ch.start_line}-{ch.end_line}  "
            f"({len(ch.text)} chars)  | {head}..."
        )
    print()


def run(
    input_path: Path,
    output_dir: Path,
    seed: int,
    dry_run: bool,
    chunk_max_chars: int = 3000,
    respect_stage_markers: bool = True,
    batch_size: int = 1,
) -> int:
    """Run the fanfiction-to-script pipeline. Returns exit code."""
    random.seed(seed)

    text = _load_text(input_path)
    chunks = Chunker(
        chunk_max_chars=chunk_max_chars,
        respect_stage_markers=respect_stage_markers,
    ).split(text)

    if dry_run:
        _preview_chunks(chunks)
        print("[dry-run] No LLM call made. Exiting.")
        return 0

    output_dir.mkdir(parents=True, exist_ok=True)
    return _run(_execute(chunks, output_dir, input_path, seed, batch_size))


async def _execute(
    chunks: List[Chunk],
    output_dir: Path,
    input_path: Path,
    seed: int,
    batch_size: int,
) -> int:
    """Real generation + synthesis loop (M2)."""
    from ling_chat.core.fic_runtime import FicRuntime

    rt = await FicRuntime.create(batch_size=batch_size)
    results = []

    for chunk in chunks:
        # AC-2: inject reference_material with 同人演绎 style.
        rt.session.update_scene(
            description="同人演绎", style="同人演绎", material=chunk.text
        )
        # AC-3: generate batch_size lines per chunk.
        for _ in range(batch_size):
            line = await rt.generate_one(chunk.text)
            if line is None:
                break
            # AC-4: synthesize voice.
            audio = await rt.synthesize(line) if line.tts_text.strip() else ""
            results.append(
                {
                    "chunk_id": chunk.chunk_id,
                    "speaker": line.speaker,
                    "emotion": line.emotion,
                    "display_text": line.display_text,
                    "tts_text": line.tts_text,
                    "action": line.action,
                    "audio": audio,
                }
            )

    # AC-5: fidelity scoring + report.
    from ling_chat.core.fic_scorer import score_chunks

    report = score_chunks(chunks, results)

    manifest = {
        "input": str(input_path),
        "seed": seed,
        "chunk_count": len(chunks),
        "line_count": len(results),
        "lines": results,
        "report": report,
    }
    out = output_dir / "fic_manifest.json"
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Generated {len(results)} lines from {len(chunks)} chunks.")
    print(f"Fidelity overall: {report['overall']}")
    print(f"Wrote manifest: {out}")
    return 0


def run_demo(output_dir: Path, seed: int) -> int:
    """AC-6 end-to-end demo on the annotated excerpt with accuracy eval."""
    from ling_chat.core.fic_demo import (
        emit_playable,
        evaluate_accuracy,
        load_ground_truth,
    )

    random.seed(seed)

    base = Path(__file__).resolve().parents[2]
    gt_path = base / "tmp/ref-article/ema-hiro-heart-groundtruth.json"
    fic_path = base / "tmp/ref-article/ema-hiro-heart.md"

    output_dir.mkdir(parents=True, exist_ok=True)

    # Ground-truth excerpt: read the source span lines.
    gt = load_ground_truth(gt_path)
    span = gt["source_span"]
    fic_lines = _load_text(fic_path).split("\n")
    excerpt = "\n".join(fic_lines[span["start_line"] - 1 : span["end_line"]])

    # Run the pipeline on the excerpt (single chunk, one line per ground-truth line).
    from ling_chat.core.fic_chunker import Chunker

    chunks = Chunker(chunk_max_chars=3000).split(excerpt)
    rc, results = _run(_execute(chunks, output_dir, fic_path, seed, batch_size=1))
    if rc != 0:
        return rc

    # Evaluate accuracy vs ground truth (AC-6).
    accuracy = evaluate_accuracy(results, gt)
    print(f"Speaker accuracy: {accuracy['speaker_accuracy']:.1%}")
    print(f"Narration/dialogue accuracy: {accuracy['type_accuracy']:.1%}")

    # Emit playable.json (AC-6 artifact).
    playable_path = output_dir / "playable.json"
    emit_playable(results, playable_path, topic="ema-hiro-heart-demo")
    print(f"Wrote playable: {playable_path}")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description="Fanfiction -> A2DStudio script pipeline (offline)."
    )
    p.add_argument("--input", type=Path, required=True, help="path to fanfiction .md")
    p.add_argument("--output", type=Path, required=True, help="output directory")
    p.add_argument("--seed", type=int, default=42, help="random seed (reproducibility)")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="show chunk preview without calling the LLM",
    )
    p.add_argument(
        "--chunk-max-chars",
        type=int,
        default=3000,
        help="max chars per chunk (paragraph split); default 3000",
    )
    p.add_argument(
        "--no-stage-markers",
        action="store_true",
        help="ignore |<===Stage_N===>| markers and split by paragraph only",
    )
    p.add_argument(
        "--batch-size",
        type=int,
        default=1,
        help="lines to generate per chunk; default 1",
    )
    p.add_argument(
        "--demo",
        action="store_true",
        help="run the AC-6 end-to-end demo on the annotated excerpt with accuracy eval",
    )
    args = p.parse_args(argv)

    if args.chunk_max_chars <= 0:
        p.error("--chunk-max-chars must be positive")

    if args.demo:
        return run_demo(args.output, args.seed)

    return run(
        input_path=args.input,
        output_dir=args.output,
        seed=args.seed,
        dry_run=args.dry_run,
        chunk_max_chars=args.chunk_max_chars,
        respect_stage_markers=not args.no_stage_markers,
        batch_size=args.batch_size,
    )


if __name__ == "__main__":
    sys.exit(main())
