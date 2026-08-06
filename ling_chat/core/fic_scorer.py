"""Fidelity scorers for the fanfiction-to-script pipeline (AC-5).

Measures how faithfully the generated script matches the source passage.
Deliberately does NOT use CER/WER (those measure transcription accuracy,
which is negatively correlated with adaptation quality — a good paraphrase
scores high CER but is a good adaptation).

Scorer backends:
- EmbeddingScorer: character n-gram TF vectors + cosine similarity (numpy,
  deterministic, no heavy deps, language-agnostic). DEFAULT OFFLINE.
- MultilingualEmbedderScorer: sentence-transformers paraphrase-multilingual-
  MiniLM-L12-v2 (the plan-specified embedder) — used when the dep is
  importable. Falls back to EmbeddingScorer otherwise.
- LLMJudgeScorer: structured 1-5 rubric score + rationale via LLM.
"""

from __future__ import annotations

import json
import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional

import numpy as np

from ling_chat.core.fic_chunker import Chunk


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Normalization (reuse the ASR eval discipline)
# ---------------------------------------------------------------------------
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
# Embedding scorer (character n-gram TF + cosine) — default offline
# ---------------------------------------------------------------------------
class EmbeddingScorer(BaseScorer):
    """Deterministic character n-gram cosine similarity."""

    def __init__(self, ngram_sizes: tuple = (2, 3), normalize: bool = True) -> None:
        self.ngram_sizes = ngram_sizes
        self.normalize = normalize

    def _ngrams(self, text: str) -> dict[str, float]:
        if self.normalize:
            text = _normalize(text)
        else:
            text = _WHITESPACE.sub(" ", text).strip()
        vec: dict[str, float] = {}
        for n in self.ngram_sizes:
            if len(text) < n:
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
        s = _normalize(source)
        g = _normalize(generated)
        if not s or not g:
            return 0.0
        return max(0.0, min(1.0, self._cosine(self._ngrams(s), self._ngrams(g))))


# ---------------------------------------------------------------------------
# Multilingual embedder scorer (plan-specified) with graceful fallback
# ---------------------------------------------------------------------------
class MultilingualEmbedderScorer(BaseScorer):
    """Plan-specified multilingual embedder (sentence-transformers).

    Falls back to EmbeddingScorer if the dep is unavailable.
    """

    def __init__(self, model_name: str = "paraphrase-multilingual-MiniLM-L12-v2") -> None:
        self.model_name = model_name
        self._model = None
        self._fallback = EmbeddingScorer()
        try:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(model_name)
        except ImportError:
            logger.warning(
                "sentence-transformers unavailable — falling back to "
                "character-n-gram EmbeddingScorer"
            )

    def score(self, source: str, generated: str) -> float:
        if self._model is None:
            return self._fallback.score(source, generated)
        try:
            from sklearn.metrics.pairwise import cosine_similarity
        except ImportError:
            return self._fallback.score(source, generated)
        emb = self._model.encode([_normalize(source), _normalize(generated)])
        return float(cosine_similarity([emb[0]], [emb[1]])[0][0])


def _default_scorer() -> BaseScorer:
    """Prefer the plan embedder; fall back to n-gram when dep unavailable."""
    try:
        import sentence_transformers  # noqa: F401

        return MultilingualEmbedderScorer()
    except ImportError:
        return EmbeddingScorer()


# ---------------------------------------------------------------------------
# LLM-judge scorer (AC-5 positive)
# ---------------------------------------------------------------------------
@dataclass
class JudgeScore:
    score: int  # 1-5
    rationale: str

    def __post_init__(self) -> None:
        self.score = max(1, min(5, int(self.score)))


class LLMJudgeScorer:
    """Structured 1-5 rubric score + rationale via LLM."""

    RUBRIC = """Evaluate how faithfully the generated script matches the source.
Rate 1-5 on EACH axis (then give overall):
- dialogue fidelity: are original lines preserved or naturally adapted?
- style preservation: is the tone/voice of the source maintained?
- character voice: do characters speak consistently with their persona?

Respond in EXACT JSON: {"score": <1-5>, "rationale": "<one sentence>"}"""

    def __init__(self, llm=None) -> None:
        self._llm = llm

    async def score(self, source: str, generated: str) -> JudgeScore:
        from ling_chat.core.llm_providers.manager import LLMManager

        llm = self._llm or LLMManager()
        prompt = (
            f"{self.RUBRIC}\n\n"
            f"SOURCE:\n{_normalize(source)}\n\n"
            f"GENERATED:\n{_normalize(generated)}\n"
        )
        messages = [{"role": "user", "content": prompt}]
        try:
            full_text = ""
            async for chunk in llm.process_message_stream(messages):
                if isinstance(chunk, str):
                    full_text += chunk
                elif hasattr(chunk, "content"):
                    full_text += chunk.content or ""
                else:
                    full_text += str(chunk)
            data = json.loads(full_text.strip())
            return JudgeScore(score=int(data.get("score", 3)), rationale=str(data.get("rationale", "")))
        except Exception as exc:  # malformed → coerce, don't crash
            logger.warning(f"LLM judge parse failed ({exc}); coercing to neutral")
            return JudgeScore(score=3, rationale=f"parse failed: {exc}")


# ---------------------------------------------------------------------------
# Per-chunk + aggregate scoring over a pipeline run
# ---------------------------------------------------------------------------
def score_chunks(
    chunks: List[Chunk],
    generated_lines: List[dict],
    scorer: Optional[BaseScorer] = None,
    judge: Optional[LLMJudgeScorer] = None,
) -> dict:
    """Score generated lines against their source chunks.

    generated_lines: list of dicts with at least {"chunk_id", "display_text"}.
    Returns per-chunk + overall aggregate. Chunks with no source span are
    skipped with a warning (AC-5 negative).
    """
    scorer = scorer or _default_scorer()

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

    def _chunk_info(cid: int) -> tuple[dict, str]:
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

    result = {
        "scorer": scorer.__class__.__name__,
        "overall": overall,
        "chunk_count": len(by_chunk),
        "line_count": len(all_scores),
        "per_chunk": per_chunk,
    }
    return result
