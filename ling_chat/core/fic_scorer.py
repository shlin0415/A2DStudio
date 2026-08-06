"""Fidelity scorers for the fanfiction-to-script pipeline (AC-5).

Measures how faithfully the generated script matches the source passage.
Deliberately does NOT use CER/WER (those measure transcription accuracy,
which is negatively correlated with adaptation quality — a good paraphrase
scores high CER but is a good adaptation).

Two scorer backends:
- EmbeddingScorer: character n-gram TF vectors + cosine similarity (numpy,
  deterministic, no heavy deps, language-agnostic).
- LLMJudgeScorer: structured 1-5 rubric score via LLM (optional, heavier).
"""

from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from typing import List, Optional

import numpy as np

from ling_chat.core.fic_chunker import Chunk


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Normalization (reuse the ASR eval discipline)
# ---------------------------------------------------------------------------
# Strip leading/trailing non-voiced punctuation + normalize whitespace so the
# similarity is on content, not artifacts. Mirrors a2d_asr_eval._strip_artifacts.
_ARTIFACT_LEADING = re.compile(r"^[.。·・…]+")
_ARTIFACT_TRAILING = re.compile(r"[.。·・…]+$")
_WHITESPACE = re.compile(r"\s+")


def _normalize(text: str) -> str:
    """Light normalization for fair similarity comparison."""
    text = _ARTIFACT_LEADING.sub("", text)
    text = _ARTIFACT_TRAILING.sub("", text)
    text = _WHITESPACE.sub(" ", text)
    return text.strip()


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------
class BaseScorer(ABC):
    @abstractmethod
    def score(self, source: str, generated: str) -> float:
        """Return a similarity/quality score. Higher = more faithful."""


# ---------------------------------------------------------------------------
# Embedding scorer (character n-gram TF + cosine)
# ---------------------------------------------------------------------------
class EmbeddingScorer(BaseScorer):
    """Deterministic character n-gram cosine similarity.

    Language-agnostic (works on zh/ja/en without tokenization), reproducible
    (no randomness), zero heavy deps (numpy only).
    """

    def __init__(self, ngram_sizes: tuple = (2, 3), normalize: bool = True) -> None:
        self.ngram_sizes = ngram_sizes
        self.normalize = normalize

    def _ngrams(self, text: str) -> dict[str, float]:
        """Character n-gram term-frequency vector as a dict."""
        if self.normalize:
            text = _normalize(text)
        else:
            text = _WHITESPACE.sub(" ", text).strip()
        vec: dict[str, float] = {}
        for n in self.ngram_sizes:
            if len(text) < n:
                # Whole-text unigram fallback for very short strings.
                vec[text] = vec.get(text, 0.0) + 1.0
                continue
            for i in range(len(text) - n + 1):
                gram = text[i : i + n]
                vec[gram] = vec.get(gram, 0.0) + 1.0
        return vec

    def _cosine(self, a: dict[str, float], b: dict[str, float]) -> float:
        if not a or not b:
            return 0.0
        keys = set(a) | set(b)
        va = np.array([a.get(k, 0.0) for k in keys], dtype=np.float64)
        vb = np.array([b.get(k, 0.0) for k in keys], dtype=np.float64)
        na = np.linalg.norm(va)
        nb = np.linalg.norm(vb)
        if na == 0 or nb == 0:
            return 0.0
        return float(np.dot(va, vb) / (na * nb))

    def score(self, source: str, generated: str) -> float:
        """Cosine similarity in [0, 1] between source and generated n-gram vectors."""
        s = _normalize(source)
        g = _normalize(generated)
        if not s or not g:
            return 0.0
        return max(0.0, min(1.0, self._cosine(self._ngrams(s), self._ngrams(g))))


# ---------------------------------------------------------------------------
# Per-chunk + aggregate scoring over a pipeline run
# ---------------------------------------------------------------------------
def score_chunks(
    chunks: List[Chunk],
    generated_lines: List[dict],
    scorer: Optional[BaseScorer] = None,
) -> dict:
    """Score generated lines against their source chunks.

    generated_lines: list of dicts with at least {"chunk_id", "display_text"}.
    Returns per-chunk + overall aggregate. Chunks with no source span are
    skipped with a warning (AC-5 negative).
    """
    scorer = scorer or EmbeddingScorer()

    by_chunk: dict[int, list[float]] = {}
    for line in generated_lines:
        cid = line.get("chunk_id")
        gen_text = line.get("display_text") or line.get("tts_text") or ""
        if cid is None or not gen_text:
            continue
        chunk = next((c for c in chunks if c.chunk_id == cid), None)
        if chunk is None or not chunk.text.strip():
            logger.warning(
                f"chunk {cid}: missing source span — skipping (not fabricating score)"
            )
            continue
        score = scorer.score(chunk.text, gen_text)
        by_chunk.setdefault(cid, []).append(score)

    def _chunk_info(cid: int) -> dict:
        c = next((c for c in chunks if c.chunk_id == cid), None)
        return (
            {"start_line": c.start_line, "end_line": c.end_line},
            c.text if c else "",
        )

    per_chunk = []
    for cid, scores in sorted(by_chunk.items()):
        span, text = _chunk_info(cid)
        per_chunk.append(
            {
                "chunk_id": cid,
                "source_span": span,
                "source_text": text,
                "generated_count": len(scores),
                "mean_score": round(sum(scores) / len(scores), 4),
            }
        )

    all_scores = [s for scores in by_chunk.values() for s in scores]
    overall = round(sum(all_scores) / len(all_scores), 4) if all_scores else 0.0

    return {
        "scorer": scorer.__class__.__name__,
        "overall": overall,
        "chunk_count": len(by_chunk),
        "line_count": len(all_scores),
        "per_chunk": per_chunk,
    }
