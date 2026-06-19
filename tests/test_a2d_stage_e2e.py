"""A2D Stage E2E — Playwright 截图验证角色立绘 + WS 消息校验。

需后端 (8765) + 前端 (5173) 都在运行，否则自动跳过。

用法:
  uv run pytest tests/test_a2d_stage_e2e.py --e2e --headed -v --tb=short  # Playwright E2E
  uv run pytest tests/test_a2d_stage_e2e.py -v -k "not page"              # 只跑 WS 测试
  uv run pytest tests/ -v --tb=short -k "not e2e"                         # 排除 E2E
"""

import asyncio
import json
import os

import pytest
import websockets

from tests import (
    PROJECT_ROOT, BACKEND_URL, FRONTEND_URL, STAGE_URL, WS_URL,
    backend_ok, frontend_ok, wait_for_ws,
)

_SCREENSHOT_DIR = PROJECT_ROOT / "tmp"


# ═══════════════════════════════════════════════════════════════
# WS message tests (no browser needed)
# ═══════════════════════════════════════════════════════════════

@pytest.mark.skipif(not backend_ok(), reason="Backend not running on :8765")
@pytest.mark.asyncio
async def test_a2d_characters_sent_on_start():
    """a2d.start 必须返回 a2d.characters 消息，且只含 .env 配置的角色。"""
    async with websockets.connect(WS_URL) as ws:
        await asyncio.wait_for(ws.recv(), timeout=10)  # connection_established
        await ws.send(json.dumps({"type": "a2d.start", "payload": {"topic": "e2e测试"}}))

        characters = None
        for _ in range(30):
            try:
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=30))
            except asyncio.TimeoutError:
                break
            t = msg.get("type", "")
            if t == "a2d.characters":
                characters = msg["payload"]["characters"]
                break
            elif t == "tts_ready":
                break  # stop after first TTS
            elif t == "error":
                break  # non-fatal for character test

        assert characters is not None, "No a2d.characters message received"
        assert len(characters) >= 1, "Expected at least 1 character"

        # Every character must have the required fields
        for c in characters:
            assert isinstance(c["roleId"], int)
            assert len(c["roleName"]) > 0
            assert len(c["character_folder"]) > 0
            assert isinstance(c["scale"], (int, float))

        # If A2D_STAGE_CHARACTERS is set, count must match
        expected = os.environ.get("A2D_STAGE_CHARACTERS", "")
        if expected.strip():
            expected_keys = {k.strip() for k in expected.split(",") if k.strip()}
            assert len(characters) == len(expected_keys), (
                f"Expected {expected_keys}, got {len(characters)} characters"
            )


@pytest.mark.skipif(not backend_ok(), reason="Backend not running on :8765")
@pytest.mark.asyncio
async def test_a2d_characters_respects_env_filter():
    """当 A2D_STAGE_CHARACTERS 设置时，只发送配置的角色。"""
    expected = os.environ.get("A2D_STAGE_CHARACTERS", "")
    if not expected.strip():
        pytest.skip("A2D_STAGE_CHARACTERS not set — nothing to filter")

    expected_keys = {k.strip() for k in expected.split(",") if k.strip()}

    async with websockets.connect(WS_URL) as ws:
        await asyncio.wait_for(ws.recv(), timeout=10)
        await ws.send(json.dumps({"type": "a2d.start", "payload": {"topic": "filter测试"}}))

        characters = None
        for _ in range(30):
            try:
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=30))
            except asyncio.TimeoutError:
                break
            t = msg.get("type", "")
            if t == "a2d.characters":
                characters = msg["payload"]["characters"]
                break
            elif t == "tts_ready" or t == "error":
                break

        assert characters is not None, "No a2d.characters message received"
        actual_keys = {c.get("script_role_key", "") for c in characters}
        assert actual_keys == expected_keys, (
            f"Stage characters mismatch: expected {expected_keys}, got {actual_keys}"
        )


# ═══════════════════════════════════════════════════════════════
# Playwright browser tests (require --e2e or A2D_E2E_FULLSTACK=1)
# ═══════════════════════════════════════════════════════════════

def test_stage_page_loads_and_ws_connects(page):
    """Stage 页面加载后，composable 应自动连接 WS。"""
    assert wait_for_ws(page), "WebSocket not connected within timeout"


def test_stage_renders_characters_after_start(page):
    """点击 '开始对话' 后，gameStore.presentRoleIds 应非空，立绘区域应有内容。"""
    assert wait_for_ws(page), "WebSocket not connected"

    # Click "开始对话" button
    start_btn = page.locator("button:has-text('开始对话')")
    if not start_btn.is_visible():
        page.wait_for_timeout(3000)
    assert start_btn.is_visible(), "'开始对话' button not found"

    start_btn.click()
    page.wait_for_timeout(5000)

    # ── Assert 1: gameStore populated ──────────────────
    store = page.evaluate("""
        () => {
            const pinia = document.querySelector('#app').__vue_app__.config.globalProperties.$pinia;
            const gs = pinia.state.value.game;
            return {
                presentRoleIds: gs.presentRoleIds || [],
                roleCount: Object.keys(gs.gameRoles || {}).length,
            };
        }
    """)
    assert store["presentRoleIds"], f"presentRoleIds empty! Store: {store}"
    assert store["roleCount"] >= 1, f"No roles in gameStore! Store: {store}"

    # ── Assert 2: characters loaded console message ────
    chars_loaded = any("characters loaded" in m for m in page._console_msgs)
    assert chars_loaded, f"No 'characters loaded' in console"

    # ── Assert 3: screenshot contains rendered content ─
    screenshot_path = _SCREENSHOT_DIR / "test_stage_characters.png"
    page.screenshot(path=str(screenshot_path))

    # Verify screenshot isn't blank (at least 10% non-white pixels)
    from PIL import Image
    img = Image.open(screenshot_path)
    colors = img.getcolors(maxcolors=100000)
    if colors:
        non_white = sum(c for c, rgb in colors if rgb != (255, 255, 255))
        total = img.width * img.height
        content_ratio = non_white / total
        assert content_ratio > 0.1, (
            f"Screenshot appears blank: {content_ratio:.1%} non-white pixels. "
            f"Saved to {screenshot_path}"
        )
