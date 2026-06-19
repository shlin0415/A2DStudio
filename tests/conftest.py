"""Shared pytest fixtures for A2D Stage E2E tests.

Provides:
  CLI flags:      --headed (headed browser), --e2e (enable E2E tests)
  Health checks:  backend_ok, frontend_ok, ws_ok (for pytest.mark.skipif)
  Lifecycle:      full_stack (session-scoped: start/stop backend+frontend)
  Playwright:     page (function-scoped Playwright page with console capture)
  Helpers:        extract_trace(page), extract_store(page), wait_for_ws(page)
  Constants:      BACKEND_URL, FRONTEND_URL, STAGE_URL, WS_URL, PROJECT_ROOT

Usage:
  uv run pytest tests/ --headed              # headed browser
  uv run pytest tests/ -k "not e2e"          # skip E2E tests
  uv run pytest tests/ --e2e                 # run E2E tests only
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
import httpx

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCREENSHOT_DIR = PROJECT_ROOT / "tmp"

# ── URLs ──────────────────────────────────────────────
BACKEND_URL = "http://localhost:8765"
FRONTEND_URL = "http://localhost:5173"
STAGE_URL = f"{FRONTEND_URL}/stage"
WS_URL = "ws://localhost:8765/ws"
BACKEND_LOG = PROJECT_ROOT / "tmp" / "backend-monitor.log"


# ── CLI flags ─────────────────────────────────────────
def pytest_addoption(parser):
    parser.addoption("--headed", action="store_true", default=False,
                     help="Run Playwright tests with headed browser")
    parser.addoption("--e2e", action="store_true", default=False,
                     help="Run full E2E tests (requires backend+frontend+GSV)")


def pytest_configure(config):
    config.addinivalue_line("markers", "e2e: full end-to-end test (requires full stack)")
    config.addinivalue_line("markers", "slow: test that takes >60s")


# ── Load .env ─────────────────────────────────────────
try:
    from ling_chat.utils.load_env import load_env
    load_env(PROJECT_ROOT / ".env")
except Exception:
    pass


# ── Health checks ─────────────────────────────────────
def backend_ok() -> bool:
    """Backend HTTP server reachable (any response = up)."""
    try:
        httpx.get(BACKEND_URL, timeout=3)
        return True
    except Exception:
        return False


def frontend_ok() -> bool:
    """Frontend dev server reachable with HTTP 200."""
    try:
        r = httpx.get(FRONTEND_URL, timeout=3)
        return r.status_code == 200
    except Exception:
        return False


def gsv_ok(port: int = 31801) -> bool:
    """GSV instance reachable on given port."""
    try:
        r = httpx.get(f"http://localhost:{port}", timeout=3)
        return True  # any response = running
    except Exception:
        return False


# ── Health-check fixtures (usable with skipif) ────────
@pytest.fixture(scope="session")
def backend_running():
    return backend_ok()


@pytest.fixture(scope="session")
def frontend_running():
    return frontend_ok()


# ── Process management ────────────────────────────────
def _kill_port(port: int) -> None:
    """Kill any process listening on the given port (Windows)."""
    try:
        import subprocess
        result = subprocess.run(
            ["cmd", "/c", f"netstat -ano | findstr :{port} | findstr LISTENING"],
            capture_output=True, text=True, timeout=5,
        )
        for line in result.stdout.strip().split("\n"):
            if not line.strip():
                continue
            parts = line.strip().split()
            if parts:
                pid = parts[-1]
                subprocess.run(["taskkill", "/F", "/PID", pid],
                               capture_output=True, timeout=5)
    except Exception:
        pass


def _start_backend() -> subprocess.Popen:
    """Start LingChat backend, return process handle."""
    _kill_port(8765)
    proc = subprocess.Popen(
        ["uv", "run", "python", "main.py"],
        cwd=str(PROJECT_ROOT),
        stdout=open(BACKEND_LOG, "w", encoding="utf-8"),
        stderr=subprocess.STDOUT,
        env={**os.environ, "PYTHONUTF8": "1"},
    )
    return proc


def _start_frontend() -> subprocess.Popen:
    """Start Vite dev server, return process handle."""
    frontend_dir = PROJECT_ROOT / "frontend_vue"
    _kill_port(5173)
    proc = subprocess.Popen(
        ["pnpm", "run", "dev"],
        cwd=str(frontend_dir),
        stdout=open(PROJECT_ROOT / "tmp" / "vite-monitor.log", "w", encoding="utf-8"),
        stderr=subprocess.STDOUT,
    )
    return proc


def _wait_for_health(timeout: int = 120) -> bool:
    """Poll backend + frontend until both are up or timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if backend_ok() and frontend_ok():
            return True
        time.sleep(2)
    return False


# ── Full-stack session fixture ────────────────────────
@pytest.fixture(scope="session")
def full_stack(request):
    """Start backend + frontend for the test session. GSV assumed running.

    Use --e2e flag or A2D_E2E_FULLSTACK=1 env var to enable.
    """
    if not request.config.getoption("--e2e"):
        env_enabled = os.environ.get("A2D_E2E_FULLSTACK", "").strip() in ("1", "true", "yes")
        if not env_enabled:
            pytest.skip("Full stack not requested (use --e2e or A2D_E2E_FULLSTACK=1)")

    # Start services
    backend_proc = _start_backend()
    frontend_proc = _start_frontend()

    # Wait for both to be healthy
    if not _wait_for_health():
        backend_proc.terminate()
        frontend_proc.terminate()
        pytest.skip("Backend or frontend failed to start within timeout")

    yield

    # Teardown
    try:
        backend_proc.terminate()
        backend_proc.wait(timeout=10)
    except Exception:
        pass
    try:
        frontend_proc.terminate()
        frontend_proc.wait(timeout=10)
    except Exception:
        pass


# ── Playwright page fixture ───────────────────────────
@pytest.fixture
def page(full_stack, request):
    """Playwright page with console capture and A2D trace extraction support.

    Requires playwright installed. Use --headed for visible browser.
    """
    pytest.importorskip("playwright")
    from playwright.sync_api import sync_playwright

    headed = request.config.getoption("--headed", False)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed)
        ctx_page = browser.new_page(viewport={"width": 1280, "height": 720})

        # Collect console messages
        console_msgs: list[dict] = []
        ctx_page.on("console", lambda msg: console_msgs.append({
            "type": msg.type, "text": msg.text,
        }))

        # Navigate to stage
        ctx_page.goto(STAGE_URL)
        ctx_page.wait_for_load_state("networkidle")

        yield ctx_page

        browser.close()


# ── Trace / Store extraction helpers ──────────────────
def extract_trace(page) -> list[dict]:
    """Extract and drain window.__a2dTrace entries. Returns parsed list."""
    try:
        raw = page.evaluate("() => window.__a2dTrace ? window.__a2dTrace.splice(0) : []")
        # page.evaluate may return a JS array; ensure it's a Python list
        if isinstance(raw, list):
            return [dict(e) if isinstance(e, dict) else e for e in raw]
        return []
    except Exception:
        return []


def extract_store(page) -> dict:
    """Snapshot the Pinia script store. Returns dict with keys:
    scriptPhase, scriptLines, playingLineId, selectedLineId, error, etc.
    """
    try:
        return page.evaluate("""
            () => {
              try {
                const app = document.querySelector('#app').__vue_app__;
                const pinia = app.config.globalProperties.$pinia;
                const store = pinia._s.get('script');
                if (!store) return {error: 'script store not found'};
                return {
                  scriptPhase: store.phase,
                  scriptLines: store.lines.map(l => ({
                    id: l.id, speaker: l.speaker, index: l.index,
                    text: l.display_text, batch_index: l.batch_index,
                    batch_total: l.batch_total,
                  })),
                  playingLineId: store.playingLineId,
                  selectedLineId: store.selectedLineId,
                  currentLine: store.currentLine ? {
                    speaker: store.currentLine.speaker,
                    text: store.currentLine.display_text,
                  } : null,
                  error: store.error,
                };
              } catch(e) { return {error: e.message}; }
            }
        """)
    except Exception as e:
        return {"error": str(e)}


def wait_for_ws(page, timeout: int = 15000) -> bool:
    """Wait for WebSocket connection to establish."""
    try:
        page.wait_for_function(
            "() => window.__a2d_ws_connected === true",
            timeout=timeout,
        )
        return True
    except Exception:
        return False
