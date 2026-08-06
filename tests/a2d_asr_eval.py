"""ASR evaluation workflow — capture real-usage audio, transcribe, compute CER/WER.

Usage:
  # Prerequisites: full stack running + a dialogue already triggered (trace populated)
  PYTHONUTF8=1 .venvs/asr-env/Scripts/python tests/a2d_asr_eval.py \
      --capture trace_hook \
      --model large-v3 \
      --output tmp/asr_eval

  # With thresholds
  PYTHONUTF8=1 .venvs/asr-env/Scripts/python tests/a2d_asr_eval.py \
      --capture trace_hook --cer-warn 0.1 --cer-fail 0.2

Modes:
  trace_hook      Parse window.__a2dTrace (default, recommended)
  media_recorder  [reserved] Browser-side MediaRecorder
  backend_hook    [reserved] Backend tts_provider monkeypatch
"""

import argparse
import asyncio
import json
import os
import re
import sys
import time
import wave
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Protocol, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

FRONTEND_URL = os.environ.get("A2D_E2E_FRONTEND_URL", "http://localhost:5173")
STAGE_URL = f"{FRONTEND_URL}/stage"
DEFAULT_OUTPUT = PROJECT_ROOT / "tmp" / "asr_eval"
DEFAULT_MODEL = os.environ.get("A2D_ASR_MODEL", str(PROJECT_ROOT / ".venvs" / "asr-env" / "models" / "large-v3"))


# ═══════════════════════════════════════════════════════════════
# Data model
# ═══════════════════════════════════════════════════════════════

@dataclass
class AudioSample:
    """One (audio, target_text) pair from a real usage capture."""
    wav_path: str
    text_target: str       # ground truth: tts_text from production flow
    line_id: str           # unique script line id
    speaker: str           # character key (ema / hiro / narrator)
    capture_mode: str      # "trace_hook" / "media_recorder" / "backend_hook"
    duration_s: float = 0.0


# ═══════════════════════════════════════════════════════════════
# CaptureProvider (strategy pattern, extensible)
# ═══════════════════════════════════════════════════════════════

class CaptureProvider(Protocol):
    """Capture audio + associate target text. Returns unified AudioSample list."""
    async def capture(self) -> list[AudioSample]: ...


class TraceHookCapture:
    """Parse window.__a2dTrace to get (audio_url, tts_text) pairs.

    Requires frontend instrumentation:
      - ws_script_line event must include tts_text
      - ws_tts_ready event must include audio_url
    """

    def __init__(self, stage_url: str = STAGE_URL, output_dir: Path = DEFAULT_OUTPUT):
        self.stage_url = stage_url
        self.output_dir = output_dir
        self.samples_dir = output_dir / "samples"

    async def capture(self, use_cache: bool = True, batch_size: int = 10) -> list[AudioSample]:
        """Full flow: open page → trigger dialogue → wait → read trace → download audio.

        Self-contained: does NOT require a prior perf_latency run.
        """
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            raise ImportError("playwright not installed: uv pip install playwright && playwright install chromium")

        self.samples_dir.mkdir(parents=True, exist_ok=True)
        samples: list[AudioSample] = []

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            try:
                await page.goto(self.stage_url)
                await page.wait_for_load_state("networkidle", timeout=15000)

                # Wait for WebSocket connected
                try:
                    await page.wait_for_function(
                        "() => window.__a2d_ws_connected === true", timeout=15000
                    )
                except Exception:
                    console_msgs = await page.evaluate("() => window.__a2dTrace || []")
                    if not any("connected" in str(m) for m in console_msgs):
                        raise ConnectionError(f"WebSocket not connected at {self.stage_url}")

                # Set batch size
                batch_input = page.locator(".batch-input")
                if await batch_input.is_visible(timeout=5000):
                    await batch_input.fill(str(batch_size))

                # Click start
                start_btn = page.locator("button:has-text('开始对话')")
                if not await start_btn.is_visible(timeout=5000):
                    raise RuntimeError("Start button not visible — is the stage loaded?")
                await start_btn.click()

                # Wait for dialogue to complete (phase = paused)
                deadline = time.time() + 300
                phase = "?"
                while time.time() < deadline:
                    await page.wait_for_timeout(1500)
                    phase = await page.evaluate("""
                        () => {
                            try {
                                const p = document.querySelector('#app').__vue_app__
                                    .config.globalProperties.$pinia._s.get('script');
                                return p ? p.phase : 'unknown';
                            } catch { return 'unknown'; }
                        }
                    """)
                    if phase in ("paused", "error"):
                        break

                if phase == "error":
                    raise RuntimeError("Backend error during dialogue — check backend-monitor.log")
                if phase != "paused":
                    raise RuntimeError(f"Dialogue did not complete (phase={phase})")

                # Wait for audio drain
                drain_deadline = time.time() + 60
                while time.time() < drain_deadline:
                    drained = await page.evaluate(
                        "() => (window.__a2dTrace || []).some(t => t.event === 'audio_queue_empty')"
                    )
                    if drained:
                        break
                    await page.wait_for_timeout(1000)

                trace = await page.evaluate("() => window.__a2dTrace || []")
            finally:
                await browser.close()

        if not trace:
            raise ValueError("No trace data captured. Check frontend is running and dialogue completed.")

        # Build lookup maps keyed by lineId
        text_by_id: dict[str, dict] = {}   # lineId -> {tts_text, speaker}
        audio_by_id: dict[str, str] = {}   # lineId -> audio_url

        for entry in trace:
            evt = entry.get("event", "")
            data = entry.get("data") or {}
            lid = data.get("lineId") or ""
            if not lid:
                continue
            if evt == "ws_script_line":
                text_by_id[lid] = {
                    "tts_text": data.get("tts_text", ""),
                    "speaker": data.get("speaker", ""),
                }
            elif evt == "ws_tts_ready":
                audio_by_id[lid] = data.get("audio_url", "")

        # Associate by lineId
        linked = set(text_by_id.keys()) & set(audio_by_id.keys())
        if not linked:
            print(f"  ws_script_line: {len(text_by_id)} entries")
            print(f"  ws_tts_ready:   {len(audio_by_id)} entries")
            print(f"  linked by lineId: {len(linked)}")
            raise ValueError("No (tts_text, audio_url) pairs linked. Check frontend instrumentation.")

        # Download audio + build samples
        import httpx
        async with httpx.AsyncClient(timeout=30.0) as client:
            for i, lid in enumerate(sorted(linked)):
                info = text_by_id[lid]
                audio_url = audio_by_id[lid]
                tts_text = info["tts_text"]
                speaker = info["speaker"]

                wav_path = str(self.samples_dir / f"{lid}.wav")

                # Cache hit
                if use_cache and os.path.exists(wav_path):
                    duration = _wav_duration(wav_path)
                    samples.append(AudioSample(
                        wav_path=wav_path, text_target=tts_text, line_id=lid,
                        speaker=speaker, capture_mode="trace_hook", duration_s=duration,
                    ))
                    print(f"  [{i+1}/{len(linked)}] cache hit  {lid}")
                    continue

                # Download
                try:
                    resp = await client.get(audio_url)
                    resp.raise_for_status()
                except Exception as e:
                    print(f"  [{i+1}/{len(linked)}] SKIP download failed {lid}: {e}")
                    continue

                with open(wav_path, "wb") as f:
                    f.write(resp.content)

                duration = _wav_duration(wav_path)
                if duration < 0.3:
                    print(f"  [{i+1}/{len(linked)}] SKIP too short {lid}: {duration:.2f}s")
                    continue

                samples.append(AudioSample(
                    wav_path=wav_path, text_target=tts_text, line_id=lid,
                    speaker=speaker, capture_mode="trace_hook", duration_s=duration,
                ))
                print(f"  [{i+1}/{len(linked)}] OK {lid} ({duration:.1f}s) {tts_text[:30]}...")

        return samples


def _wav_duration(wav_path: str) -> float:
    """Read wav duration in seconds."""
    try:
        with wave.open(wav_path, "rb") as wf:
            frames = wf.getnframes()
            rate = wf.getframerate()
            return frames / rate if rate > 0 else 0.0
    except Exception:
        return 0.0


# ═══════════════════════════════════════════════════════════════
# ASR Engine (strategy pattern)
# ═══════════════════════════════════════════════════════════════

class AsrEngine(Protocol):
    def transcribe(self, wav_path: str, language: Optional[str] = None) -> str: ...


class FasterWhisperEngine:
    """faster-whisper backend. Lazy-loads model on first transcribe()."""

    def __init__(self, model_size_or_path: str = DEFAULT_MODEL, device: str = "auto",
                 compute_type: str = "int8"):
        self.model_path = model_size_or_path
        self.device = device
        self.compute_type = compute_type
        self._model = None

    def _load(self):
        if self._model is not None:
            return
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            raise ImportError(
                "faster-whisper not installed. In asr-env: "
                "uv pip install faster-whisper"
            )
        device = self.device
        if device == "auto":
            device = "cuda" if _has_cuda() else "cpu"
        print(f"Loading Whisper model: {self.model_path} ({device}, {self.compute_type})")
        self._model = WhisperModel(self.model_path, device=device, compute_type=self.compute_type)

    def transcribe(self, wav_path: str, language: Optional[str] = None, vad: bool = True) -> str:
        self._load()
        # VAD filter: removes silence, breath sounds, and non-speech segments
        segments, info = self._model.transcribe(
            wav_path, language=language, beam_size=5,
            vad_filter=vad, vad_parameters=dict(min_silence_duration_ms=200),
        )
        text = " ".join(seg.text for seg in segments)
        return text.strip()


def _has_cuda() -> bool:
    """Check CUDA availability without importing torch globally."""
    try:
        import torch
        return torch.cuda.is_available()
    except ImportError:
        return False


# ═══════════════════════════════════════════════════════════════
# Metrics (CER / WER)
# ═══════════════════════════════════════════════════════════════

# Punctuation normalization: full-width → half-width, unify variants
# Keep punctuation (short Japanese utterances get distorted if stripped entirely)
_PUNCT_MAP = {
    "。": ".", "．": ".", "、": ",", "，": ",", "！": "!", "？": "?",
    "：": ":", "；": ";", "…": "..", "‥": "..", "―": "-", "―": "-",
    "「": "'", "」": "'", "『": "'", "』": "'", "（": "(", "）": ")",
    "〔": "(", "〕": ")", "【": "(", "】": ")", "《": "(", "》": ")",
    "〈": "(", "〉": ")", "　": " ",
}


def _normalize(text: str) -> str:
    """Normalize punctuation forms for fair comparison.

    Strategy: keep punctuation but unify full-width → half-width so ASR
    output matches target format. Collapse repeated dots (…… → ..).
    """
    for fw, hw in _PUNCT_MAP.items():
        text = text.replace(fw, hw)
    # Collapse 3+ dots → ..
    while "..." in text:
        text = text.replace("...", "..")
    return text.strip()


def _strip_artifacts(text: str) -> str:
    """Strip leading/trailing non-voiced symbols from an eval string.

    GSV does not voice leading/trailing ellipsis (……), so ASR drops them too —
    keeping them inflates WER artifactually (e.g. ……おやすみ → target keeps ".."
    as a fugashi token while ASR omits it → first token wrong → WER cascades).

    Also strips leading/trailing commas: the multi-segment join separator
    (TTS_JOIN_SEP "、") becomes "," after _normalize and appears at segment
    boundaries. Internal commas/punctuation are voiced and MUST stay.

    Applied to BOTH target and ASR so the comparison stays symmetric.
    """
    text = re.sub(r'^[.。·・…]+', '', text)   # leading ellipsis
    text = re.sub(r'[.。·・…]+$', '', text)   # trailing ellipsis
    text = re.sub(r'^[,]+', '', text)          # leading commas (join-sep artifact)
    text = re.sub(r'[,]+$', '', text)          # trailing commas (join-sep artifact)
    return text.strip()


def compute_metrics(text_target: str, text_asr: str) -> dict:
    """Compute CER and WER between target and ASR output.

    Language-aware tokenization:
      - Chinese: jieba segmentation
      - Japanese: fugashi (unidic-lite) segmentation
      - English / other: whitespace tokenization

    Returns: {cer, wer, target_len, asr_len, language}
    """
    import jiwer

    if not text_target:
        return {"cer": 0.0, "wer": 0.0, "target_len": 0, "asr_len": len(text_asr), "language": "unknown"}

    if not text_asr:
        return {"cer": 1.0, "wer": 1.0, "target_len": len(text_target), "asr_len": 0, "language": "unknown"}

    # Normalize: strip punctuation + whitespace for content-only comparison
    t_norm = _normalize(text_target)
    a_norm = _normalize(text_asr)

    # Strip leading/trailing non-voiced artifacts (ellipsis + join-separator)
    # from BOTH sides. Internal punctuation is voiced by GSV and stays.
    t_norm = _strip_artifacts(t_norm)
    a_norm = _strip_artifacts(a_norm)

    if not t_norm:
        return {"cer": 0.0, "wer": 0.0, "target_len": 0, "asr_len": len(a_norm), "language": "unknown"}

    if not a_norm:
        return {"cer": 1.0, "wer": 1.0, "target_len": len(t_norm), "asr_len": 0, "language": "unknown"}

    cer = min(jiwer.cer(t_norm, a_norm), 1.0)  # Cap at 100% (insertions can exceed)
    language = _detect_language(t_norm)

    # Language-aware tokenization for WER
    if language == "zh":
        try:
            import jieba
            t_words = " ".join(jieba.lcut(t_norm))
            a_words = " ".join(jieba.lcut(a_norm))
            wer = jiwer.wer(t_words, a_words)
        except ImportError:
            wer = jiwer.wer(t_norm, a_norm)  # fallback char-level
    elif language == "ja":
        try:
            from fugashi import Tagger
            tagger = Tagger("-Owakati")
            t_words = tagger.parse(t_norm)
            a_words = tagger.parse(a_norm)
            wer = jiwer.wer(t_words, a_words)
        except ImportError:
            wer = jiwer.wer(t_norm, a_norm)  # fallback char-level
    else:
        # English / other: whitespace tokenization (jiwer default)
        wer = jiwer.wer(t_norm, a_norm)

    return {
        "cer": round(min(cer, 1.0), 4),
        "wer": round(min(wer, 1.0), 4),
        "target_len": len(t_norm),
        "asr_len": len(a_norm),
        "language": language,
    }


def _detect_language(text: str) -> str:
    """Simple language detection by character ranges.

    Priority: Japanese-specific (hiragana/katakana) > Chinese (CJK) > Latin.
    Japanese uses CJK chars too, so hiragana/katakana must be checked first.

    Returns: "zh" / "ja" / "en" / "unknown"
    """
    has_cjk = False
    has_latin = False

    for ch in text:
        # Japanese-specific ranges: hiragana, katakana, katakana phonetic extensions
        if "぀" <= ch <= "ゟ" or "゠" <= ch <= "ヿ" or "ㇰ" <= ch <= "ㇿ":
            return "ja"  # Immediate return — unambiguous Japanese marker
        # CJK unified ideographs (used in both Chinese and Japanese)
        if "一" <= ch <= "鿿":
            has_cjk = True
        elif "A" <= ch <= "Z" or "a" <= ch <= "z":
            has_latin = True

    if has_cjk:
        return "zh"
    if has_latin:
        return "en"
    return "unknown"


# ═══════════════════════════════════════════════════════════════
# Report generation
# ═══════════════════════════════════════════════════════════════

def generate_report(
    samples: list[AudioSample],
    results: list[dict],
    output_dir: Path,
    cer_warn: float = 0.1,
    cer_fail: float = 0.2,
) -> dict:
    """Generate manifest.json, report.json, report.md, and per-sample json."""
    output_dir.mkdir(parents=True, exist_ok=True)
    samples_dir = output_dir / "samples"
    samples_dir.mkdir(exist_ok=True)

    # Per-sample json
    for sample, result in zip(samples, results):
        sample_json = asdict(sample)
        sample_json.update(result)
        with open(samples_dir / f"{sample.line_id}.json", "w", encoding="utf-8") as f:
            json.dump(sample_json, f, ensure_ascii=False, indent=2)

    # Summary stats
    cers = [r["cer"] for r in results]
    wers = [r["wer"] for r in results]
    n = len(results)

    over_warn = sum(1 for c in cers if c > cer_warn)
    over_fail = sum(1 for c in cers if c > cer_fail)

    # Per-language breakdown
    lang_stats: dict[str, dict] = {}
    for r in results:
        lang = r.get("language", "unknown")
        if lang not in lang_stats:
            lang_stats[lang] = {"count": 0, "cers": [], "wers": []}
        lang_stats[lang]["count"] += 1
        lang_stats[lang]["cers"].append(r["cer"])
        lang_stats[lang]["wers"].append(r["wer"])

    by_language = {}
    for lang, stats in lang_stats.items():
        cn = stats["count"]
        by_language[lang] = {
            "count": cn,
            "avg_cer": round(sum(stats["cers"]) / cn, 4) if cn else 0,
            "avg_wer": round(sum(stats["wers"]) / cn, 4) if cn else 0,
        }

    summary = {
        "sample_count": n,
        "avg_cer": round(sum(cers) / n, 4) if n else 0,
        "avg_wer": round(sum(wers) / n, 4) if n else 0,
        "max_cer": round(max(cers), 4) if cers else 0,
        "max_wer": round(max(wers), 4) if wers else 0,
        "over_warn_count": over_warn,
        "over_warn_pct": round(over_warn / n * 100, 1) if n else 0,
        "over_fail_count": over_fail,
        "over_fail_pct": round(over_fail / n * 100, 1) if n else 0,
        "by_language": by_language,
    }

    report = {
        "summary": summary,
        "thresholds": {"cer_warn": cer_warn, "cer_fail": cer_fail},
        "samples": [
            {
                "line_id": s.line_id,
                "speaker": s.speaker,
                "language": r.get("language", "unknown"),
                "text_target": s.text_target,
                "text_asr": r.get("text_asr", ""),
                "cer": r["cer"],
                "wer": r["wer"],
                "duration_s": s.duration_s,
            }
            for s, r in zip(samples, results)
        ],
    }

    # manifest
    manifest = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "capture_mode": samples[0].capture_mode if samples else "",
        "model": DEFAULT_MODEL,
        "sample_count": n,
    }
    with open(output_dir / "manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    # report.json
    with open(output_dir / "report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # report.md
    md = _render_report_md(summary, report["samples"], cer_warn, cer_fail)
    with open(output_dir / "report.md", "w", encoding="utf-8") as f:
        f.write(md)

    return summary


def _render_report_md(summary: dict, samples: list[dict], cer_warn: float, cer_fail: float) -> str:
    """Render human-readable Markdown report."""
    lines = []
    lines.append("# ASR 评测报告")
    lines.append("")
    lines.append(f"时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")

    # Summary table
    lines.append("## 聚合统计")
    lines.append("")
    lines.append("| 指标 | 值 |")
    lines.append("|------|-----|")
    lines.append(f"| 样本数 | {summary['sample_count']} |")
    lines.append(f"| 平均 CER | {summary['avg_cer']:.2%} |")
    lines.append(f"| 平均 WER | {summary['avg_wer']:.2%} |")
    lines.append(f"| 最大 CER | {summary['max_cer']:.2%} |")
    lines.append(f"| 最大 WER | {summary['max_wer']:.2%} |")
    lines.append(f"| CER > {cer_warn:.0%} 的样本 | {summary['over_warn_count']} ({summary['over_warn_pct']}%) |")
    lines.append(f"| CER > {cer_fail:.0%} 的样本 | {summary['over_fail_count']} ({summary['over_fail_pct']}%) |")
    lines.append("")

    # Per-language breakdown
    if summary.get("by_language"):
        lines.append("## 按语言 breakdown")
        lines.append("")
        lines.append("| 语言 | 样本数 | 平均 CER | 平均 WER |")
        lines.append("|------|--------|----------|----------|")
        lang_labels = {"zh": "中文", "ja": "日文", "en": "英文", "unknown": "未知"}
        for lang, stats in summary["by_language"].items():
            label = lang_labels.get(lang, lang)
            lines.append(f"| {label} | {stats['count']} | {stats['avg_cer']:.2%} | {stats['avg_wer']:.2%} |")
        lines.append("")

    # Detail table
    lines.append("## 详情")
    lines.append("")
    lines.append("| line_id | lang | speaker | text_target | text_asr | CER | WER | flag |")
    lines.append("|---------|------|---------|-------------|----------|-----|-----|------|")

    for s in samples:
        cer = s["cer"]
        if cer > cer_fail:
            flag = "FAIL"
        elif cer > cer_warn:
            flag = "WARN"
        else:
            flag = "OK"
        # Truncate long text for table readability
        target = s["text_target"][:20].replace("|", "\\|") + ("…" if len(s["text_target"]) > 20 else "")
        asr = s["text_asr"][:20].replace("|", "\\|") + ("…" if len(s["text_asr"]) > 20 else "")
        lang = s.get("language", "?")
        lines.append(
            f"| {s['line_id'][:10]} | {lang} | {s['speaker']} | {target} | {asr} | "
            f"{cer:.2%} | {s['wer']:.2%} | {flag} |"
        )

    lines.append("")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# Main orchestration
# ═══════════════════════════════════════════════════════════════

async def run_asr_eval(
    capture: str = "trace_hook",
    model: str = DEFAULT_MODEL,
    device: str = "auto",
    output: Path = DEFAULT_OUTPUT,
    cer_warn: float = 0.1,
    cer_fail: float = 0.2,
    use_cache: bool = True,
    batch_size: int = 10,
    language: Optional[str] = None,
    vad: bool = True,
) -> dict:
    """End-to-end ASR evaluation. Returns summary dict."""
    # 1. Capture
    print(f"═══ Capture mode: {capture} ═══")
    if capture == "trace_hook":
        capturer = TraceHookCapture(output_dir=output)
    else:
        raise ValueError(f"Unsupported capture mode: {capture} (only trace_hook implemented)")

    samples = await capturer.capture(use_cache=use_cache, batch_size=batch_size)
    if not samples:
        raise ValueError("No audio samples captured. Check trace data.")
    print(f"Captured {len(samples)} samples")

    # 2. Transcribe
    print(f"═══ ASR engine: faster-whisper ({model}, vad={vad}, lang={language or 'auto'}) ═══")
    engine = FasterWhisperEngine(model, device=device)

    results = []
    for i, sample in enumerate(samples):
        # Use explicit language hint if provided, else per-sample auto-detect
        lang_hint = language if language else _detect_language(_normalize(sample.text_target))
        text_asr = engine.transcribe(sample.wav_path, language=lang_hint, vad=vad)
        metrics = compute_metrics(sample.text_target, text_asr)
        metrics["text_asr"] = text_asr
        results.append(metrics)
        flag = "OK " if metrics["cer"] <= cer_warn else ("WARN" if metrics["cer"] <= cer_fail else "FAIL")
        print(f"  [{i+1}/{len(samples)}] {flag} CER={metrics['cer']:.2%} [{lang_hint}] {sample.text_target[:25]}...")

    # 3. Report
    print(f"═══ Generating report ═══")
    summary = generate_report(samples, results, output, cer_warn, cer_fail)
    print(f"\nReport: {output / 'report.md'}")
    print(f"JSON:   {output / 'report.json'}")

    return summary


def main():
    parser = argparse.ArgumentParser(description="ASR evaluation workflow — CER/WER on real usage audio")
    parser.add_argument("--capture", default="trace_hook",
                        choices=["trace_hook", "media_recorder", "backend_hook"],
                        help="Capture mode (default: trace_hook)")
    parser.add_argument("--model", default=DEFAULT_MODEL,
                        help="faster-whisper model path or size (default: local large-v3)")
    parser.add_argument("--device", default="auto", choices=["auto", "cpu", "cuda"],
                        help="Device (default: auto)")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT,
                        help="Output directory (default: tmp/asr_eval)")
    parser.add_argument("--cer-warn", type=float, default=0.1,
                        help="CER warning threshold (default: 0.1)")
    parser.add_argument("--cer-fail", type=float, default=0.2,
                        help="CER failure threshold (default: 0.2)")
    parser.add_argument("--use-cache", action="store_true", default=True,
                        help="Reuse existing wav files (default: True)")
    parser.add_argument("--no-cache", dest="use_cache", action="store_false",
                        help="Force re-download audio")
    parser.add_argument("--batch-size", type=int, default=10,
                        help="Dialogue batch size for trace_hook mode (default: 10)")
    parser.add_argument("--language", default=None, choices=["ja", "zh", "en"],
                        help="Force language hint (default: auto-detect per sample)")
    parser.add_argument("--no-vad", action="store_true",
                        help="Disable VAD filtering (default: VAD on)")
    args = parser.parse_args()

    summary = asyncio.run(run_asr_eval(
        capture=args.capture,
        model=args.model,
        device=args.device,
        output=args.output,
        cer_warn=args.cer_warn,
        cer_fail=args.cer_fail,
        use_cache=args.use_cache,
        batch_size=args.batch_size,
        language=args.language,
        vad=not args.no_vad,
    ))

    # Print summary
    print()
    print("=" * 60)
    print("  ASR Evaluation Summary")
    print("=" * 60)
    print(f"  Samples:     {summary['sample_count']}")
    print(f"  Avg CER:     {summary['avg_cer']:.2%}")
    print(f"  Avg WER:     {summary['avg_wer']:.2%}")
    print(f"  Max CER:     {summary['max_cer']:.2%}")
    print(f"  Over warn:   {summary['over_warn_count']} ({summary['over_warn_pct']}%)")
    print(f"  Over fail:   {summary['over_fail_count']} ({summary['over_fail_pct']}%)")
    print("=" * 60)


if __name__ == "__main__":
    main()
