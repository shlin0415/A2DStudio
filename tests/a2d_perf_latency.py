"""Pipeline latency profiler — Playwright-based, batch_size=5, measures per-stage timing.

Usage:
  PYTHONUTF8=1 uv run python tests/a2d_perf_latency.py
  PYTHONUTF8=1 uv run python tests/a2d_perf_latency.py --batch-size 3 --headed

Requires: full stack running (backend + frontend + GSV), Playwright installed.
"""

import argparse
import os
import time
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

FRONTEND_URL = os.environ.get("A2D_E2E_FRONTEND_URL", "http://localhost:5173")
STAGE_URL = f"{FRONTEND_URL}/stage"
BATCH_SIZE = int(os.environ.get("A2D_PERF_BATCH_SIZE", "5"))
ROUND_TIMEOUT = int(os.environ.get("A2D_PERF_ROUND_TIMEOUT", "300"))


# ── Trace parsing ─────────────────────────────────────────────────


def parse_traces(traces: list[dict]) -> list[dict]:
    """Group trace events into per-line segments for timing analysis.

    Returns list of dicts:
      {line_id, line_idx, t_ws_script_line, t_ws_tts_ready, t_audio_queued,
       t_preroll_start, t_preroll_end, t_audio_start, t_audio_end,
       llm_ms, tts_ms, queue_ms, preroll_ms, audio_ms}
    """
    segments: dict[str, dict] = {}  # lineId -> partial segment

    def get_seg(lid: str) -> dict:
        if lid not in segments:
            segments[lid] = {"line_id": lid}
        return segments[lid]

    for i, e in enumerate(traces):
        evt = e.get("event", "")
        ts = e.get("ts", 0)
        data = e.get("data", {})
        lid = data.get("lineId") or data.get("id") or ""

        if evt == "ws_script_line":
            seg = get_seg(lid)
            seg["t_ws_script_line"] = ts
        elif evt == "script_line":
            lid2 = data.get("lineId", "")
            seg = get_seg(lid2)
            seg["t_script_line"] = ts
            seg["speaker"] = data.get("speaker", "?")
        elif evt == "ws_tts_ready":
            seg = get_seg(lid)
            seg["t_ws_tts_ready"] = ts
        elif evt == "audio_queued":
            seg = get_seg(lid)
            seg["t_audio_queued"] = ts
        elif evt == "preroll_start":
            seg = get_seg(lid)
            seg["t_preroll_start"] = ts
            seg["first_play"] = data.get("firstPlay", False)
        elif evt == "preroll_end":
            seg = get_seg(lid)
            seg["t_preroll_end"] = ts
        elif evt == "audio_start":
            seg = get_seg(lid)
            seg["t_audio_start"] = ts
        elif evt == "audio_end":
            seg = get_seg(lid)
            seg["t_audio_end"] = ts

    # Compute durations, filter incomplete segments
    result = []
    for lid, seg in segments.items():
        if seg.get("t_ws_script_line") is None or seg.get("t_audio_end") is None:
            continue  # incomplete

        t_ws_sl = seg["t_ws_script_line"]
        t_ws_tts = seg.get("t_ws_tts_ready")
        t_q = seg.get("t_audio_queued", t_ws_tts)
        t_ps = seg.get("t_preroll_start")
        t_pe = seg.get("t_preroll_end")
        t_as = seg.get("t_audio_start", t_pe)
        t_ae = seg["t_audio_end"]

        # LLM: from script_line WS receipt to tts_ready WS receipt (backend TTS done)
        llm_ms = (t_ws_tts - t_ws_sl) if t_ws_tts else 0

        # Queue wait: from audio_queued to preroll_start
        queue_ms = (t_ps - t_q) if t_ps else 0

        # Pre-Roll: preroll_start to preroll_end
        preroll_ms = (t_pe - t_ps) if t_ps and t_pe else 0

        # Audio playback: audio_start to audio_end
        audio_ms = t_ae - t_as if t_as else 0

        # Total: ws_script_line to audio_end
        total_ms = t_ae - t_ws_sl

        seg["llm_ms"] = llm_ms
        seg["tts_ms"] = t_ws_tts - t_q if t_ws_tts else 0  # TTS synthesis (ws_tts_ready - audio_queued ≈ same)
        seg["queue_ms"] = queue_ms
        seg["preroll_ms"] = preroll_ms
        seg["audio_ms"] = audio_ms
        seg["total_ms"] = total_ms

        result.append(seg)

    result.sort(key=lambda s: s.get("t_ws_script_line", 0))
    return result


def print_report(segments: list[dict], wall_sec: float) -> None:
    """Print latency breakdown table."""
    print()
    print("=" * 95)
    print("  A2D Pipeline Latency Report  (batch_size=5)")
    print(f"  Total wall time: {wall_sec:.1f}s")
    print("=" * 95)
    print(f"  {'#':>2} {'Spk':>4}  {'LLM':>6}  {'TTS':>6}  {'Queue':>6}  {'PreRoll':>8}  {'Audio':>6}  {'Total':>7}  {'Overlap':>8}")
    print(f"  {'':->2} {'':->4}  {'':->6}  {'':->6}  {'':->6}  {'':->8}  {'':->6}  {'':->7}  {'':->8}")

    prev_ae = 0
    for i, seg in enumerate(segments):
        # Overlap: how much of this line's pipeline was hidden by previous line's playback
        t_ws_sl = seg.get("t_ws_script_line", 0)
        overlap_ms = max(0, prev_ae - t_ws_sl) if prev_ae > 0 else 0
        overlap_s = f"{overlap_ms:.0f}ms" if overlap_ms < 1000 else f"{overlap_ms/1000:.1f}s"

        print(
            f"  {i+1:>2} {seg.get('speaker', '?'):>4}  "
            f"{seg['llm_ms']:>5.0f}ms  {seg['tts_ms']:>5.0f}ms  "
            f"{seg['queue_ms']:>5.0f}ms  {seg['preroll_ms']:>7.0f}ms  "
            f"{seg['audio_ms']:>5.0f}ms  {seg['total_ms']:>6.0f}ms  {overlap_s:>8}"
        )
        prev_ae = seg.get("t_audio_end", 0)

    # Summary row
    if segments:
        avg_llm = sum(s["llm_ms"] for s in segments) / len(segments)
        avg_tts = sum(s["tts_ms"] for s in segments) / len(segments)
        avg_queue = sum(s["queue_ms"] for s in segments) / len(segments)
        avg_preroll = sum(s["preroll_ms"] for s in segments) / len(segments)
        avg_audio = sum(s["audio_ms"] for s in segments) / len(segments)
        total_wall_ms = wall_sec * 1000
        hidden = sum(max(0, segments[i-1].get("t_audio_end", 0) - s.get("t_ws_script_line", 0))
                     for i, s in enumerate(segments) if i > 0)
        print(f"  {'':->2} {'':->4}  {'':->6}  {'':->6}  {'':->6}  {'':->8}  {'':->6}  {'':->7}  {'':->8}")
        print(
            f"  {'AVG':>2} {'':>4}  "
            f"{avg_llm:>5.0f}ms  {avg_tts:>5.0f}ms  "
            f"{avg_queue:>5.0f}ms  {avg_preroll:>7.0f}ms  "
            f"{avg_audio:>5.0f}ms  "
        )
        print()
        print(f"  Pipeline efficiency: {hidden/1000:.1f}s hidden by audio overlap "
              f"({hidden/wall_ms*100:.0f}% of {wall_sec:.1f}s wall time)")

    print("=" * 95)
    print()


# ── Main ──────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="A2D Pipeline Latency Profiler")
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE, help="Batch size (default: 5)")
    parser.add_argument("--headed", action="store_true", help="Show browser window")
    parser.add_argument("--round-timeout", type=int, default=ROUND_TIMEOUT, help="Round timeout in seconds")
    args = parser.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("ERROR: Playwright not installed. Run: uv run playwright install chromium")
        sys.exit(1)

    print(f"Opening {STAGE_URL} ...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.headed)
        page = browser.new_page(viewport={"width": 1280, "height": 720})

        # Collect all console for debugging
        console_msgs: list[str] = []
        page.on("console", lambda msg: console_msgs.append(msg.text))

        page.goto(STAGE_URL)
        page.wait_for_load_state("networkidle")

        # Wait for WS connection
        try:
            page.wait_for_function(
                "() => window.__a2d_ws_connected === true",
                timeout=15000,
            )
        except Exception:
            # Fallback: check console for [A2D] WebSocket connected
            ws_ok = any("[A2D] WebSocket connected" in m for m in console_msgs)
            if not ws_ok:
                print("ERROR: WebSocket not connected within 15s")
                browser.close()
                sys.exit(1)

        print("WebSocket connected ✓")

        # Set batch_size via the number input
        batch_input = page.locator(".batch-input")
        if batch_input.is_visible(timeout=5000):
            batch_input.fill(str(args.batch_size))
            print(f"Batch size set to {args.batch_size} ✓")
        else:
            print("WARNING: batch input not found, using default")

        # Click start
        start_btn = page.locator("button:has-text('开始对话')")
        if not start_btn.is_visible(timeout=5000):
            print("ERROR: start button not visible")
            browser.close()
            sys.exit(1)
        start_btn.click()
        print("Started dialogue — waiting for all audio to finish...")

        # Wait for paused phase then audio drain
        deadline = time.time() + args.round_timeout
        phase = "?"
        while time.time() < deadline:
            page.wait_for_timeout(1000)
            try:
                store = page.evaluate("""
                    () => {
                        const pinia = document.querySelector('#app').__vue_app__
                            .config.globalProperties.$pinia;
                        const s = pinia._s.get('script');
                        return s ? { phase: s.phase, lines: s.lines?.length || 0 } : null;
                    }
                """)
                if store:
                    phase = store["phase"]
                    elapsed = int(time.time() - (deadline - args.round_timeout))
                    print(f"  [{elapsed}s] phase={phase} lines={store['lines']}", end="\r")
                    if phase in ("paused", "error"):
                        break
            except Exception:
                pass

        print()
        if phase not in ("paused", "error"):
            print(f"ERROR: timeout at phase={phase}")
            browser.close()
            sys.exit(1)
        if phase == "error":
            print("ERROR: backend reported error — check backend log")
            browser.close()
            sys.exit(1)

        print("Phase=paused — waiting for audio queue to empty...")
        # Wait for audio_queue_empty
        deadline2 = time.time() + 60
        drained = False
        while time.time() < deadline2:
            page.wait_for_timeout(1000)
            try:
                traces = page.evaluate("() => window.__a2dTrace || []")
                if any(t.get("event") == "audio_queue_empty" for t in traces):
                    drained = True
                    break
            except Exception:
                pass
        if not drained:
            print("WARNING: audio_queue_empty not detected within 60s")
        # Extra grace period
        page.wait_for_timeout(3000)

        # Extract all traces
        traces = page.evaluate("() => window.__a2dTrace || []")

        # Find wall start from first phase_change to thinking
        t0 = next((t.get("wall") for t in traces
                   if t.get("event") == "phase_change" and t.get("data", {}).get("to") == "thinking"), 0)
        t_end = next((t.get("wall") for t in reversed(traces)
                      if t.get("event") == "audio_queue_empty"), t0)
        wall_sec = (t_end - t0) / 1000 if t0 and t_end else 0

        browser.close()

    # Parse and report
    segments = parse_traces(traces)
    if not segments:
        print("ERROR: No complete audio segments found in trace")
        print(f"Trace event types: {[t.get('event') for t in traces]}")
        sys.exit(1)

    print_report(segments, wall_sec)

    # Save raw trace for debugging
    import json
    out = PROJECT_ROOT / "tmp" / "perf-trace.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(traces, f, ensure_ascii=False, indent=2)
    print(f"Raw trace saved to {out}")


if __name__ == "__main__":
    main()
