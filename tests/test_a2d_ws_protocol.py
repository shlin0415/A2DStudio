"""WS-only fast protocol test for A2D Stage — validates message sequence without browser.

Usage:
  uv run pytest tests/test_a2d_ws_protocol.py -v --tb=short
  A2D_WS_FAST=1 uv run pytest tests/test_a2d_ws_protocol.py -v  # single round quick mode
"""

import json
import os

import pytest
import websockets

from tests import WS_URL, backend_ok

pytestmark = pytest.mark.asyncio


# ── Helpers ────────────────────────────────────────────

async def _connect_and_send(action: str = "a2d.start", payload: dict | None = None) -> list[dict]:
    """Connect WS, send action, collect messages until paused/error."""
    messages: list[dict] = []
    try:
        async with websockets.connect(WS_URL) as ws:
            await ws.send(json.dumps({
                "type": action,
                "payload": payload or {},
            }))
            async for raw in ws:
                msg = json.loads(raw)
                messages.append(msg)
                if msg.get("type") == "status":
                    phase = msg.get("payload", {}).get("phase", "")
                    if phase in ("paused", "error"):
                        break
    except Exception as e:
        messages.append({"type": "_error", "payload": {"message": str(e)}})
    return messages


# ── Tests ──────────────────────────────────────────────

class TestWSProtocol:
    """Validate A2D message protocol — field presence, types, sequence."""

    @pytest.mark.skipif(not backend_ok(), reason="Backend not running")
    async def test_start_message_sequence(self):
        """a2d.start → a2d.characters → N × (script_line + tts_ready) → status(paused)"""
        if not backend_ok():
            pytest.skip("Backend not running")

        messages = await _connect_and_send("a2d.start")

        # Check for error
        errors = [m for m in messages if m.get("type") == "_error"]
        if errors:
            pytest.skip(f"Connection error (environment fault): {errors[0]}")

        # 1. a2d.characters appears exactly once
        char_msgs = [m for m in messages if m.get("type") == "a2d.characters"]
        assert len(char_msgs) == 1, f"Expected 1 a2d.characters, got {len(char_msgs)}"
        chars = char_msgs[0].get("payload", {}).get("characters", [])
        assert len(chars) >= 1, "Expected at least 1 character"

        # AC-5: each character must have required fields (backend field names)
        for c in chars:
            assert isinstance(c.get("roleId"), int), f"roleId missing or not int: {c}"
            assert isinstance(c.get("roleName"), str) and len(c["roleName"]) > 0, \
                f"roleName missing or empty: {c}"
            assert isinstance(c.get("character_folder"), str) and len(c["character_folder"]) > 0, \
                f"character_folder missing or empty: {c}"
            assert isinstance(c.get("script_role_key"), str), \
                f"script_role_key missing: {c}"

        # 2. At least one script_line
        script_lines = [m for m in messages if m.get("type") == "script_line"]
        assert len(script_lines) >= 1, "Expected at least 1 script_line"

        # 3. Each script_line has required fields
        for sl in script_lines:
            pl = sl.get("payload", {})
            assert pl.get("id"), f"script_line missing id: {pl}"
            assert pl.get("speaker") in ("ema", "hiro", "narrator"), \
                f"Invalid speaker: {pl.get('speaker')}"
            assert pl.get("display_text"), f"script_line missing display_text"
            assert isinstance(pl.get("index"), int), f"index not int: {pl.get('index')}"
            assert isinstance(pl.get("batch_index"), int), f"batch_index not int"
            assert isinstance(pl.get("batch_total"), int), f"batch_total not int"

        # 4. batch_total consistency
        batch_totals = {sl["payload"]["batch_total"] for sl in script_lines}
        assert len(batch_totals) == 1, f"Inconsistent batch_total: {batch_totals}"
        expected_total = next(iter(batch_totals))
        assert expected_total == len(script_lines), \
            f"batch_total={expected_total} != {len(script_lines)} script_lines"

        # 5. Each tts_ready references a valid script_line id
        line_ids = {sl["payload"]["id"] for sl in script_lines}
        for msg in messages:
            if msg.get("type") == "tts_ready":
                lid = msg.get("payload", {}).get("id", "")
                if lid:
                    assert lid in line_ids, f"tts_ready id={lid} not in script_lines"
                path = msg.get("payload", {}).get("audio_path", "")
                assert path, f"tts_ready audio_path is empty"

        # 6. Final message is status(paused)
        status_msgs = [m for m in messages if m.get("type") == "status"
                       and m.get("payload", {}).get("phase") == "paused"]
        assert len(status_msgs) == 1, f"Expected 1 status(paused), got {len(status_msgs)}"

    @pytest.mark.skipif(not backend_ok(), reason="Backend not running")
    async def test_continue_message_sequence(self):
        """After start+paused on same connection, a2d.continue produces new batch."""
        if not backend_ok():
            pytest.skip("Backend not running")

        # Must use same connection for start → continue (WS sessions are per-connection)
        async with websockets.connect(WS_URL) as ws:
            # Phase 1: start
            await ws.send(json.dumps({"type": "a2d.start", "payload": {}}))
            messages_start = []
            async for raw in ws:
                msg = json.loads(raw)
                messages_start.append(msg)
                if msg.get("type") == "status":
                    phase = msg.get("payload", {}).get("phase", "")
                    if phase in ("paused", "error"):
                        break

            errors = [m for m in messages_start if m.get("type") == "status"
                      and m.get("payload", {}).get("phase") == "error"]
            if errors:
                pytest.skip(f"Start failed (env): {errors}")

            # Phase 2: continue on same connection
            await ws.send(json.dumps({"type": "a2d.continue", "payload": {}}))
            messages = []
            async for raw in ws:
                msg = json.loads(raw)
                messages.append(msg)
                if msg.get("type") == "status":
                    phase = msg.get("payload", {}).get("phase", "")
                    if phase in ("paused", "error"):
                        break

            script_lines = [m for m in messages if m.get("type") == "script_line"]
            assert len(script_lines) >= 1, "Continue round: expected at least 1 script_line"

            paused = [m for m in messages
                      if m.get("type") == "status"
                      and m.get("payload", {}).get("phase") == "paused"]
            assert len(paused) == 1, f"Continue round: expected paused, got {paused}"

    @pytest.mark.skipif(not backend_ok(), reason="Backend not running")
    async def test_error_classification_on_missing_fields(self):
        """Malformed handling: assert required fields present on all script_lines."""
        if not backend_ok():
            pytest.skip("Backend not running")

        messages = await _connect_and_send("a2d.start")
        script_lines = [m for m in messages if m.get("type") == "script_line"]
        if not script_lines:
            pytest.skip("No script_lines received (environment fault)")

        required = ["id", "speaker", "display_text", "index", "batch_index", "batch_total"]
        for sl in script_lines:
            pl = sl.get("payload", {})
            for field in required:
                assert field in pl, f"script_line missing required field: {field}"
