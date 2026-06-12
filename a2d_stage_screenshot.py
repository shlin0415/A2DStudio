"""Playwright screenshot — A2D Stage page verification.

Usage:
  cd D:/aaa-new/setups/a2d-studio/ref/LingChat
  uv run python a2d_stage_screenshot.py
"""

import asyncio
import json
import os
import websockets
from playwright.sync_api import sync_playwright

STAGE_URL = "http://localhost:5173/stage"
SCREENSHOT_DIR = "tmp"
WS_URL = "ws://localhost:8765/ws"


async def check_ws_characters():
    """Connect to backend WS, send a2d.start, verify a2d.characters message."""
    async with websockets.connect(WS_URL) as ws:
        await asyncio.wait_for(ws.recv(), timeout=10)  # connection_established
        await ws.send(json.dumps({"type": "a2d.start", "payload": {"topic": "测试截图"}}))

        result = {"characters": None, "lines": [], "errors": []}
        for _ in range(20):
            try:
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=60))
            except asyncio.TimeoutError:
                break
            t = msg.get("type", "")
            if t == "a2d.characters":
                result["characters"] = msg["payload"]["characters"]
            elif t == "script_line":
                result["lines"].append(msg["payload"])
            elif t == "error":
                result["errors"].append(msg["payload"])
                break
            elif t == "tts_ready":
                break
        return result


def main():
    # ── Step 1: Verify a2d.characters via WS ────────────────
    print("[1] Checking a2d.characters via WS...")
    ws_result = asyncio.run(check_ws_characters())

    if ws_result["characters"]:
        print(f"    ✅ {len(ws_result['characters'])} characters received:")
        for c in ws_result["characters"]:
            print(f"       roleId={c['roleId']}  name={c['roleName']}  folder={c['character_folder']}")
    else:
        print("    ❌ No characters in response!")

    if ws_result["errors"]:
        for e in ws_result["errors"]:
            print(f"    ❌ ERROR: {(e.get('message', ''))[:150]}")

    # ── Step 2: Screenshot the stage page ───────────────────
    print("[2] Taking screenshots of stage page...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page(viewport={"width": 1280, "height": 720})

        # Collect console messages
        console_msgs = []
        page.on("console", lambda msg: console_msgs.append(msg.text))

        # Navigate
        page.goto(STAGE_URL, wait_until="networkidle")
        page.wait_for_timeout(3000)
        page.screenshot(path=f"{SCREENSHOT_DIR}/a2d-stage-01-loaded.png")
        print(f"    Saved: {SCREENSHOT_DIR}/a2d-stage-01-loaded.png")

        # Check WS connection from page's own composable
        ws_connected = any("[A2D] WebSocket connected" in m for m in console_msgs)
        print(f"    WS via composable: {'✅ connected' if ws_connected else '❌ NOT connected'}")

        # Click the "开始对话" button (triggers composable's sendStart())
        try:
            start_btn = page.locator("button:has-text('开始对话')")
            if start_btn.is_visible():
                print("    Clicking '开始对话'...")
                start_btn.click()
                page.wait_for_timeout(5000)
            else:
                print("    '开始对话' button not found — trying page.evaluate fallback")
                page.evaluate("""
                    () => {
                        const buttons = [...document.querySelectorAll('button')];
                        const btn = buttons.find(b => b.textContent.includes('开始对话'));
                        if (btn) btn.click();
                    }
                """)
                page.wait_for_timeout(5000)
        except Exception as e:
            print(f"    Button click error: {e}")

        page.screenshot(path=f"{SCREENSHOT_DIR}/a2d-stage-02-after-click.png", full_page=True)
        print(f"    [1] After click -> a2d-stage-02-after-click.png")

        # Wait for characters to fade in
        page.wait_for_timeout(3000)
        page.screenshot(path=f"{SCREENSHOT_DIR}/a2d-stage-03-wait.png", full_page=True)
        print(f"    [2] After wait -> a2d-stage-03-wait.png")

        # Dump A2D console + check gameStore
        a2d_console = [m for m in console_msgs if "[A2D]" in m or "characters" in m.lower() or "error" in m.lower()]
        if a2d_console:
            print("    [3] Console [A2D]:")
            for m in a2d_console:
                print(f"      {m[:150]}")

        store_state = page.evaluate("""
            () => {
                try {
                    const pinia = document.querySelector('#app').__vue_app__.config.globalProperties.$pinia;
                    const gs = pinia.state.value.game;
                    return {
                        presentRoleIds: gs.presentRoleIds || [],
                        roleNames: Object.values(gs.gameRoles || {}).map(r => r.roleName),
                    };
                } catch(e) {
                    return {error: e.message};
                }
            }
        """)
        print(f"    [4] gameStore: {store_state}")

        browser.close()

    print("[3] Done. You can open the screenshots to verify character rendering.")


if __name__ == "__main__":
    main()
