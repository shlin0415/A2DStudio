"""Shared pytest fixtures for A2D Stage E2E tests.

Provides:
  CLI flags:      --headed (headed browser), --e2e (enable E2E tests)
  Health checks:  backend_ok, frontend_ok (from tests.__init__)
  Lifecycle:      full_stack (session-scoped: start/stop backend+frontend)
  Playwright:     page (function-scoped Playwright page with console capture)
  Helpers:        extract_trace, extract_store (from tests.__init__)

Usage:
  uv run pytest tests/ --headed              # headed browser
  uv run pytest tests/ -k "not e2e"          # skip E2E tests
  uv run pytest tests/ --e2e                 # run E2E tests only
"""

import os
import subprocess
import time

import pytest

from tests import (
    PROJECT_ROOT, BACKEND_URL, FRONTEND_URL, STAGE_URL, WS_URL,
    backend_ok, frontend_ok, extract_trace, drain_trace, extract_store, wait_for_ws,
)

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


# ── Health-check fixtures ─────────────────────────────
@pytest.fixture(scope="session")
def backend_running():
    return backend_ok()


@pytest.fixture(scope="session")
def frontend_running():
    return frontend_ok()


# ── Process management ────────────────────────────────
def _kill_port(port: int) -> None:
    """Kill any process listening on the given port, including child processes (Windows)."""
    try:
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
                # /T kills child processes too (prevents orphaned Vite/esbuild)
                subprocess.run(["taskkill", "/T", "/F", "/PID", pid],
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
        env={**os.environ},
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

    If services are already running, reuse them — don't kill and restart.
    """
    if not request.config.getoption("--e2e"):
        env_enabled = os.environ.get("A2D_E2E_FULLSTACK", "").strip() in ("1", "true", "yes")
        if not env_enabled:
            pytest.skip("Full stack not requested (use --e2e or A2D_E2E_FULLSTACK=1)")

    backend_already_up = backend_ok()
    frontend_already_up = frontend_ok()

    backend_proc = None if backend_already_up else _start_backend()
    frontend_proc = None if frontend_already_up else _start_frontend()

    if not _wait_for_health():
        for proc in (backend_proc, frontend_proc):
            if proc:
                proc.terminate()
        pytest.skip("Backend or frontend failed to start within timeout")

    yield

    # Only terminate processes we started (don't kill manually-started services)
    for proc in (backend_proc, frontend_proc):
        if proc:
            try:
                proc.terminate()
                proc.wait(timeout=10)
            except Exception:
                pass


# ── Playwright page fixture ───────────────────────────
@pytest.fixture
def page(full_stack, request):
    """Playwright page with console capture and A2D trace extraction support."""
    pytest.importorskip("playwright")
    from playwright.sync_api import sync_playwright

    headed = request.config.getoption("--headed", False)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed)
        ctx_page = browser.new_page(viewport={"width": 1280, "height": 720})

        ctx_page._console_msgs = []
        ctx_page.on("console", lambda msg: ctx_page._console_msgs.append(msg.text))

        ctx_page.goto(STAGE_URL)
        ctx_page.wait_for_load_state("networkidle")

        yield ctx_page

        browser.close()
