"""Fanfiction-to-script pipeline orchestrator (offline, no frontend/WS).

Stands up its own LLM provider + GSV adapter + SessionRuntime outside the
web-server lifecycle (the real engineering constraint, per plan deliberation).

Round 0 scope: CLI + chunker wiring + dry-run preview.
Later rounds (M2-M4) wire generation / synthesis / evaluation into run().
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from typing import List, Optional

from ling_chat.core.fic_chunker import Chunk, Chunker


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
    # M2+: generation / synthesis / evaluation wired here.
    # For now, emit the chunk manifest as a placeholder artifact.
    manifest = {
        "input": str(input_path),
        "seed": seed,
        "chunk_count": len(chunks),
        "chunks": [
            {
                "chunk_id": c.chunk_id,
                "stage_name": c.stage_name,
                "start_line": c.start_line,
                "end_line": c.end_line,
                "char_count": len(c.text),
                "text": c.text,
            }
            for c in chunks
        ],
    }
    out = output_dir / "fic_manifest.json"
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    _preview_chunks(chunks)
    print(f"Wrote manifest: {out}")
    print("(M2 generation / M3 evaluation not yet wired — coming in later rounds.)")
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
    args = p.parse_args(argv)

    if args.chunk_max_chars <= 0:
        p.error("--chunk-max-chars must be positive")

    return run(
        input_path=args.input,
        output_dir=args.output,
        seed=args.seed,
        dry_run=args.dry_run,
        chunk_max_chars=args.chunk_max_chars,
        respect_stage_markers=not args.no_stage_markers,
    )


if __name__ == "__main__":
    sys.exit(main())
