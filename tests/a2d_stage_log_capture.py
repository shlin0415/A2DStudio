"""Capture A2D Stage frontend console + WS traffic into a log file.

Usage:
  cd D:/aaa-new/setups/a2d-studio/ref/LingChat
  PYTHONUTF8=1 uv run python tests/a2d_stage_log_capture.py
"""

import os
import json
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_LOG_DIR = _PROJECT_ROOT / "tmp"

STAGE_URL = "http://localhost:5173/stage"
_HEADED = os.environ.get("A2D_E2E_HEADLESS", "").strip() not in ("1", "true", "yes")


def main():
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_path = _LOG_DIR / f"a2d-stage-log-{timestamp}.md"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not _HEADED)
        page = browser.new_page(viewport={"width": 1280, "height": 720})

        console_lines = []

        def on_console(msg):
            console_lines.append(f"[{msg.type}] {msg.text}")

        page.on("console", on_console)

        # Navigate to stage
        print(f"[1] Opening {STAGE_URL} ...")
        page.goto(STAGE_URL, wait_until="networkidle")
        page.wait_for_timeout(3000)

        # Check WS connection
        ws_ok = any("WebSocket connected" in m for m in console_lines)
        chars_ok = any("characters loaded" in m for m in console_lines)
        print(f"    WS connected: {ws_ok}, characters loaded: {chars_ok}")

        # Click "开始对话"
        try:
            btn = page.locator("button:has-text('开始对话')")
            if btn.is_visible():
                print("[2] Clicking '开始对话' ...")
                btn.click()
                # Wait for generation + TTS (up to 30s)
                page.wait_for_timeout(10000)
            else:
                print("[2] '开始对话' button not found")
        except Exception as e:
            print(f"[2] Error: {e}")

        # Wait more for TTS
        page.wait_for_timeout(5000)

        # Check gameStore state
        store = page.evaluate("""
            () => {
                try {
                    const pinia = document.querySelector('#app').__vue_app__.config.globalProperties.$pinia;
                    const gs = pinia.state.value.game;
                    const ss = pinia.state.value.script;
                    return {
                        presentRoleIds: gs.presentRoleIds || [],
                        roleNames: Object.values(gs.gameRoles || {}).map(r => r.roleName),
                        scriptLines: (ss.lines || []).map(l => ({speaker: l.speaker, text: l.display_text?.slice(0,60)})),
                        currentLine: ss.currentLine ? {speaker: ss.currentLine.speaker, text: ss.currentLine.display_text?.slice(0,60)} : null,
                        phase: ss.phase,
                    };
                } catch(e) {
                    return {error: e.message};
                }
            }
        """)

        # Take screenshot
        screenshot_path = _LOG_DIR / f"a2d-stage-log-{timestamp}.png"
        page.screenshot(path=str(screenshot_path), full_page=True)

        browser.close()

    # ── Write log ──
    a2d_lines = [l for l in console_lines if "A2D" in l or "error" in l.lower() or "characters" in l.lower()]

    with open(log_path, "w", encoding="utf-8") as f:
        f.write(f"# A2D Stage Log — {timestamp}\n\n")
        f.write(f"## Store State\n\n```json\n{json.dumps(store, ensure_ascii=False, indent=2)}\n```\n\n")
        f.write(f"## A2D Console\n\n")
        for line in a2d_lines:
            f.write(f"- {line}\n")
        f.write(f"\n## Full Console ({len(console_lines)} lines)\n\n")
        for line in console_lines:
            f.write(f"- {line}\n")
        f.write(f"\n## Screenshot\n\n![]({screenshot_path.name})\n")

    print(f"\n[Done] Log: {log_path}")
    print(f"       Screenshot: {screenshot_path}")
    print(f"       Store: {json.dumps(store, ensure_ascii=False)}")


if __name__ == "__main__":
    main()
