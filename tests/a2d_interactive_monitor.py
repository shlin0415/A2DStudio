"""Full-stack A2D Stage monitor — GSV + backend + frontend + interactive Playwright.

Usage:
  # Step 1: Start GSV manually (background, needs separate terminal)
  cd D:/aaa-new/setups/a2d-studio/ref/third_party/GPT-SoVITS-v2pro-20250604
  cmd //c "start /B api_v2_31801.bat" &
  sleep 3
  cmd //c "start /B api_v2_31802.bat" &
  sleep 40  # wait for model loading

  # Step 2: Start backend
  cd D:/aaa-new/setups/a2d-studio/ref/LingChat
  PYTHONUTF8=1 uv run python main.py > tmp/backend-monitor.log 2>&1 &

  # Step 3: Start frontend
  cd frontend_vue
  pnpm run dev > ../tmp/vite-monitor.log 2>&1 &

  # Step 4: Run this script (interactive — opens browser, YOU click)
  cd ..
  PYTHONUTF8=1 uv run python tests/a2d_interactive_monitor.py

The browser stays open. Interact with the stage page freely.
Close the browser tab/window to stop and save all logs.
"""

import os
import json
import time
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_LOG_DIR = _PROJECT_ROOT / "tmp"

STAGE_URL = "http://localhost:5173/stage"


def main():
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_path = _LOG_DIR / f"a2d-monitor-{timestamp}.md"
    ss_path = _LOG_DIR / f"a2d-monitor-{timestamp}.png"

    console_log = []  # (type, text, timestamp)
    store_snapshots = []  # periodic pinia state dumps
    start_time = time.time()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)  # always visible
        page = browser.new_page(viewport={"width": 1280, "height": 720})

        def on_console(msg):
            elapsed = time.time() - start_time
            console_log.append({
                "t": f"{elapsed:.1f}s",
                "type": msg.type,
                "text": msg.text,
            })
            # Stream to terminal so you can see it live
            print(f"  [{msg.type}] {msg.text[:120]}")

        page.on("console", on_console)

        # Navigate
        print(f"[monitor] Opening {STAGE_URL} ...")
        page.goto(STAGE_URL, wait_until="networkidle")

        print("\n╔══════════════════════════════════════╗")
        print("║  Browser is open — GO INTERACT NOW  ║")
        print("║  Close browser tab to STOP & SAVE   ║")
        print("╚══════════════════════════════════════╝\n")

        # Poll store state every 3s while browser is open
        try:
            while True:
                page.wait_for_timeout(3000)

                # Check if page is still connected
                try:
                    _ = page.title()
                except Exception:
                    print("\n[monitor] Browser closed — saving logs...")
                    break

                # Snapshot store state
                try:
                    store = page.evaluate("""
                        () => {
                          try {
                            const pinia = document.querySelector('#app').__vue_app__.config.globalProperties.$pinia;
                            const gs = pinia.state.value.game;
                            const ss = pinia.state.value.script;
                            return {
                              elapsed: 'PAUSED',
                              presentRoleIds: gs.presentRoleIds || [],
                              scriptPhase: ss.phase || '?',
                              scriptLines: (ss.lines || []).map(l => ({
                                speaker: l.speaker, text: (l.display_text || '').slice(0, 80)
                              })),
                              currentLine: ss.currentLine ? {
                                speaker: ss.currentLine.speaker,
                                text: (ss.currentLine.display_text || '').slice(0, 80)
                              } : null,
                              error: ss.error ? ss.error.message : null,
                            };
                          } catch(e) { return {error: e.message}; }
                        }
                    """)
                    elapsed = f"{time.time() - start_time:.0f}s"
                    store["elapsed"] = elapsed
                    store_snapshots.append(store)

                    phase = store.get("scriptPhase", "?")
                    n_lines = len(store.get("scriptLines", []))
                    cur = store.get("currentLine")
                    spkr = cur["speaker"] if cur else "-"
                    txt = cur["text"][:40] if cur else "-"
                    print(f"  [{elapsed}] phase={phase} lines={n_lines} current={spkr}:{txt}")
                except Exception as e:
                    print(f"  [snapshot error] {e}")

        except KeyboardInterrupt:
            print("\n[monitor] Interrupted — saving...")

    # ── Write report ──
    a2d_console = [c for c in console_log if any(kw in c["text"] for kw in
        ("[A2D]", "WebSocket", "characters", "error", "Error", "audio", "tts", "TTS"))]

    with open(log_path, "w", encoding="utf-8") as f:
        f.write(f"# A2D Stage Monitor — {timestamp}\n\n")
        f.write(f"**Duration**: {time.time() - start_time:.0f}s\n\n")

        f.write(f"## Store Snapshots ({len(store_snapshots)})\n\n")
        for s in store_snapshots:
            f.write(f"- **[{s.get('elapsed', '?')}]** phase={s.get('scriptPhase', '?')} ")
            f.write(f"lines={len(s.get('scriptLines', []))} ")
            cur = s.get('currentLine')
            if cur:
                f.write(f"speaker={cur['speaker']} text=\"{cur['text']}\"\n")
            else:
                f.write("currentLine=null\n")

        f.write(f"\n## A2D-related Console ({len(a2d_console)} entries)\n\n")
        for c in a2d_console:
            f.write(f"- [{c['t']}] **{c['type']}** {c['text']}\n")

        f.write(f"\n## Full Console ({len(console_log)} entries)\n\n")
        for c in console_log:
            f.write(f"- [{c['t']}] [{c['type']}] {c['text']}\n")

    print(f"\n✅ Log: {log_path}")
    print(f"   Lines: {len(console_log)} console, {len(store_snapshots)} snapshots")


if __name__ == "__main__":
    main()
