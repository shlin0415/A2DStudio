"""Pipeline latency profiler — batch_size=5, Gantt timeline with correct metrics.

Usage:
  PYTHONUTF8=1 uv run python tests/a2d_perf_latency.py
  PYTHONUTF8=1 uv run python tests/a2d_perf_latency.py --batch-size 3

Default: headed browser. Use --headless for headless mode.
Requires: full stack running, Playwright installed.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

FRONTEND_URL = os.environ.get("A2D_E2E_FRONTEND_URL", "http://localhost:5173")
STAGE_URL = f"{FRONTEND_URL}/stage"
BATCH_SIZE = int(os.environ.get("A2D_PERF_BATCH_SIZE", "5"))
ROUND_TIMEOUT = int(os.environ.get("A2D_PERF_ROUND_TIMEOUT", "300"))


# ═══════════════════════════════════════════════════════════════
# Timeline extraction
# ═══════════════════════════════════════════════════════════════

def build_timeline(traces: list[dict]) -> list[dict]:
    """Extract a flat ordered timeline of key events with wall-clock ms.

    Each item: {wall_s, event, line_id, speaker, detail}
    """
    items = []
    for t in traces:
        evt = t.get("event", "")
        data = t.get("data") or {}
        wall = (t.get("wall") or 0) / 1000
        lid = data.get("lineId") or data.get("id") or ""
        spk = data.get("speaker") or ""
        to_phase = data.get("to") or ""
        items.append({
            "wall_s": wall,
            "event": evt,
            "line_id": lid[:8] if lid else "",
            "speaker": spk,
            "detail": to_phase,
        })
    items.sort(key=lambda x: x["wall_s"])
    return items


# ═══════════════════════════════════════════════════════════════
# Metrics
# ═══════════════════════════════════════════════════════════════

def compute_metrics(traces: list[dict]) -> dict:
    """Compute human-meaningful latency metrics from raw traces."""
    first_audio_start = None
    last_audio_end = None
    audio_ends: list[float] = []      # wall_s of each audio_end
    audio_starts: list[float] = []    # wall_s of each audio_start
    first_think = None                # first phase_change → thinking
    backend_done = None               # last ws_tts_ready (all TTS done)
    preroll_starts: list[float] = []
    preroll_ends: list[float] = []

    for t in traces:
        evt = t.get("event", "")
        data = t.get("data") or {}
        wall = (t.get("wall") or 0) / 1000

        if evt == "phase_change" and data.get("to") == "thinking" and first_think is None:
            first_think = wall
        if evt == "audio_start":
            if first_audio_start is None:
                first_audio_start = wall
            audio_starts.append(wall)
        if evt == "audio_end":
            audio_ends.append(wall)
            last_audio_end = wall
        if evt == "ws_tts_ready":
            backend_done = wall  # last one wins
        if evt == "preroll_start":
            preroll_starts.append(wall)
        if evt == "preroll_end":
            preroll_ends.append(wall)

    if first_think is None or first_audio_start is None:
        return {}

    cold_start_s = first_audio_start - first_think
    continuous_playback_s = (last_audio_end - first_audio_start) if last_audio_end else 0

    # Idle gaps: silence > 100ms between audio_end[N] and audio_start[N+1]
    idle_gaps = []
    for i in range(len(audio_ends)):
        if i + 1 < len(audio_starts):
            gap = audio_starts[i + 1] - audio_ends[i]
            if gap > 0.1:
                idle_gaps.append((i + 1, i + 2, gap))

    total_idle_s = sum(g[2] for g in idle_gaps)

    # Pipeline lead: last backend completion vs last audio_end
    pipeline_lead_s = (last_audio_end - backend_done) if (backend_done and last_audio_end) else 0

    return {
        "cold_start_s": cold_start_s,
        "continuous_playback_s": continuous_playback_s,
        "idle_gaps": idle_gaps,
        "total_idle_s": total_idle_s,
        "pipeline_lead_s": pipeline_lead_s,
        "first_audio_start": first_audio_start,
        "last_audio_end": last_audio_end,
        "backend_done": backend_done,
        "audio_count": len(audio_starts),
    }


# ═══════════════════════════════════════════════════════════════
# Gantt chart
# ═══════════════════════════════════════════════════════════════

def print_gantt(timeline: list[dict]) -> None:
    """Print ASCII Gantt chart of pipeline events."""
    if not timeline:
        return
    t0 = timeline[0]["wall_s"]
    total = timeline[-1]["wall_s"] - t0
    width = 90

    print()
    print("  ═══ Pipeline Gantt Chart ═══")
    print(f"  time origin = {t0:.1f}s  |  total span = {total:.0f}s")
    print()

    # Group by line_id for per-line bars
    lines: dict[str, dict[str, float]] = {}
    phases: list[tuple[float, float, str]] = []  # (start, end, label)

    current_phase = None
    phase_start = 0.0
    for item in timeline:
        evt = item["event"]
        lid = item["line_id"]
        ws = item["wall_s"]

        if evt == "phase_change":
            to_p = item["detail"]
            if current_phase:
                phases.append((phase_start, ws, current_phase))
            current_phase = to_p if to_p else current_phase
            phase_start = ws

        if evt == "audio_start" and lid:
            lines.setdefault(lid, {})["play_start"] = ws
        if evt == "audio_end" and lid:
            lines.setdefault(lid, {})["play_end"] = ws
        if evt == "ws_script_line" and lid:
            lines.setdefault(lid, {})["llm_end"] = ws

    if current_phase:
        phases.append((phase_start, timeline[-1]["wall_s"], current_phase))

    # Phase bar
    def bar(start_s: float, end_s: float, label: str, width: int = width) -> str:
        offset = int((start_s - t0) / total * width)
        length = max(1, int((end_s - start_s) / total * width))
        return " " * offset + "█" * length + f"  {label}"

    # Print phase timeline
    print("  ── Phase ──")
    phase_colors = {"thinking": "░", "synthesizing": "▓", "paused": "▒"}
    for ps, pe, ph in phases:
        offset = int((ps - t0) / total * width)
        length = max(1, int((pe - ps) / total * width))
        ch = phase_colors.get(ph, " ")
        dur = pe - ps
        bar_str = " " * offset + ch * length
        pct = int(offset + length * 0.5)
        print(f"  {bar_str} {ph} ({dur:.1f}s)")

    # Print per-line audio bars
    line_order = sorted(lines.keys(), key=lambda l: lines[l].get("play_start", 9999))
    print()
    print("  ── Audio playback (per line) ──")
    for i, lid in enumerate(line_order):
        ln = lines[lid]
        ps = ln.get("play_start", 0)
        pe = ln.get("play_end", 0)
        offset = int((ps - t0) / total * width)
        length = max(1, int((pe - ps) / total * width))
        bar_str = " " * offset + "━" * length
        print(f"  {bar_str} line#{i+1} ({pe-ps:.1f}s)")

    # Time ruler
    print()
    ruler = "  "
    for i in range(0, int(total) + 1, 10):
        pos = int(i / total * width)
        ruler = ruler[:pos] + "|" + ruler[pos+1:]
    print(ruler)
    tick_labels = "  "
    for i in range(0, int(total) + 1, 10):
        pos = int(i / total * width)
        label = f"{i}s"
        tick_labels = tick_labels[:pos] + label + tick_labels[pos+len(label):]
    print(tick_labels)
    print()


# ═══════════════════════════════════════════════════════════════
# Report
# ═══════════════════════════════════════════════════════════════

def print_report(metrics: dict) -> None:
    print()
    print("=" * 70)
    print("  A2D Pipeline Performance Report")
    print("=" * 70)
    cs = metrics["cold_start_s"]
    cp = metrics["continuous_playback_s"]
    ti = metrics["total_idle_s"]
    pl = metrics["pipeline_lead_s"]
    n = metrics["audio_count"]

    print(f"  Audio lines:            {n}")
    print(f"  ─────────────────────────────────────────")
    print(f"  Cold start wait:        {cs:>6.1f}s   (click → first sound)")
    print(f"  Continuous playback:    {cp:>6.1f}s   (first → last audio_end)")
    print(f"  ─   idle gaps within:   {ti:>6.1f}s   (silence > 100ms)")
    print(f"  Pipeline lead:          {pl:>6.1f}s   (backend done ahead of last audio)")
    print(f"  ─────────────────────────────────────────")
    print(f"  Total wall time:        {cs+cp:>6.1f}s   (cold start + playback)")
    print()

    gaps = metrics["idle_gaps"]
    if gaps:
        print(f"  ⚠ Idle gaps (silence between lines):")
        for a, b, gap in gaps:
            print(f"    line#{a} → line#{b}: {gap:.2f}s gap")
    else:
        print(f"  ✓ No idle gaps — seamless audio transitions")

    print("=" * 70)
    print()


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="A2D Pipeline Latency Profiler")
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    parser.add_argument("--headless", action="store_true", help="Run headless (default: headed)")
    parser.add_argument("--round-timeout", type=int, default=ROUND_TIMEOUT)
    args = parser.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("ERROR: Playwright not installed. Run: uv run playwright install chromium")
        sys.exit(1)

    print(f"Opening {STAGE_URL} (headed={not args.headless}) ...")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=args.headless)
        page = browser.new_page(viewport={"width": 1280, "height": 720})

        console_msgs: list[str] = []
        page.on("console", lambda msg: console_msgs.append(msg.text))

        page.goto(STAGE_URL)
        page.wait_for_load_state("networkidle")

        # Wait for WS
        try:
            page.wait_for_function("() => window.__a2d_ws_connected === true", timeout=15000)
        except Exception:
            if not any("[A2D] WebSocket connected" in m for m in console_msgs):
                print("ERROR: WebSocket not connected within 15s")
                browser.close()
                sys.exit(1)

        print("WS connected ✓")

        # Set batch size
        batch_input = page.locator(".batch-input")
        if batch_input.is_visible(timeout=5000):
            batch_input.fill(str(args.batch_size))
            print(f"Batch size = {args.batch_size} ✓")

        # Click start
        start_btn = page.locator("button:has-text('开始对话')")
        if not start_btn.is_visible(timeout=5000):
            print("ERROR: start button not visible")
            browser.close()
            sys.exit(1)

        t_click = time.time()
        start_btn.click()
        print("Started — waiting for completion...")

        # Wait for paused + audio drain
        deadline = time.time() + args.round_timeout
        phase = "?"
        while time.time() < deadline:
            page.wait_for_timeout(1000)
            try:
                s = page.evaluate("""
                    () => { const p = document.querySelector('#app').__vue_app__
                        .config.globalProperties.$pinia._s.get('script');
                        return p ? { phase: p.phase, lines: p.lines?.length||0 } : null; }
                """)
                if s:
                    phase = s["phase"]
                    elapsed = int(time.time() - t_click)
                    print(f"  [{elapsed}s] phase={phase} lines={s['lines']}", end="\r")
                    if phase in ("paused", "error"):
                        break
            except Exception:
                pass

        print()
        if phase == "error":
            print("ERROR: backend error — check backend-monitor.log")
            browser.close()
            sys.exit(1)
        if phase not in ("paused", "error"):
            print(f"ERROR: timeout at phase={phase}")
            browser.close()
            sys.exit(1)

        print("Waiting for audio drain...")
        deadline2 = time.time() + 60
        drained = False
        while time.time() < deadline2:
            page.wait_for_timeout(1000)
            try:
                tr = page.evaluate("() => window.__a2dTrace || []")
                if any(t.get("event") == "audio_queue_empty" for t in tr):
                    drained = True
                    break
            except Exception:
                pass
        if not drained:
            print("WARNING: audio_queue_empty not seen in 60s")
        page.wait_for_timeout(3000)

        traces = page.evaluate("() => window.__a2dTrace || []")
        browser.close()

    # Compute metrics
    metrics = compute_metrics(traces)
    if not metrics:
        print("ERROR: No complete trace data")
        sys.exit(1)

    timeline = build_timeline(traces)

    print_gantt(timeline)
    print_report(metrics)

    # Save raw data
    out = PROJECT_ROOT / "tmp" / "perf-trace.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(traces, f, ensure_ascii=False, indent=2)
    print(f"Raw trace: {out}")


if __name__ == "__main__":
    main()
