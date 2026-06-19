"""Shared test constants and helpers for A2D Stage E2E tests.

Importable by both conftest.py (pytest auto-loaded) and regular test files.
"""

import json
from pathlib import Path
from typing import Any

import httpx

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND_URL = "http://localhost:8765"
FRONTEND_URL = "http://localhost:5173"
STAGE_URL = f"{FRONTEND_URL}/stage"
WS_URL = "ws://localhost:8765/ws"


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


# ── Trace / Store extraction helpers (used by E2E tests) ──

def extract_trace(page) -> list[dict]:
    """Copy all window.__a2dTrace entries without draining. Returns parsed list."""
    try:
        raw = page.evaluate("() => window.__a2dTrace ? window.__a2dTrace.slice(0) : []")
        if isinstance(raw, list):
            return [dict(e) if isinstance(e, dict) else e for e in raw]
        return []
    except Exception:
        return []


def drain_trace(page) -> list[dict]:
    """Extract and DRAIN window.__a2dTrace entries (use for periodic polling)."""
    try:
        raw = page.evaluate("() => window.__a2dTrace ? window.__a2dTrace.splice(0) : []")
        if isinstance(raw, list):
            return [dict(e) if isinstance(e, dict) else e for e in raw]
        return []
    except Exception:
        return []


def extract_store(page) -> dict:
    """Snapshot the Pinia script store."""
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
                  error: store.error ? {
                    error_type: store.error.error_type,
                    message: store.error.message,
                  } : null,
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
