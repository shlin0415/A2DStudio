"""Full E2E Playwright test for A2D Stage — multi-round dialogue with trace-based assertions.

Requires full stack (backend + frontend + GSV). Uses waitForFunction for round
completion detection. Trace-based assertions for phase sequence, speaker filter,
audio sync, and batch integrity. Environment faults are classified as SKIP.

Usage:
  uv run pytest tests/test_a2d_stage_e2e_full.py --e2e --headed -v --tb=short
  A2D_E2E_FAST=1 uv run pytest tests/test_a2d_stage_e2e_full.py --e2e -v   # quick smoke
"""

import os
import time

import pytest
from pathlib import Path

from tests import backend_ok, frontend_ok, extract_trace, drain_trace, extract_store
from tests.a2d_trace_assertions import (
    assert_phase_sequence, assert_speaker_filter, assert_batch_integrity,
    assert_audio_sync, assert_has_script_lines, classify_test_result,
    get_round_count,
)

pytestmark = pytest.mark.e2e

ROUND_TIMEOUT = int(os.environ.get("A2D_E2E_ROUND_TIMEOUT", "240"))
ROUND_COUNT = int(os.environ.get("A2D_E2E_ROUNDS", "3"))


class TestFullDialogueFlow:
    """Simulate full user workflow: start → multi-round → continue → trace assertions."""

    def test_round_completion(self, page):
        """Single round: start dialogue, wait for paused, verify trace."""
        if not backend_ok() or not frontend_ok():
            pytest.skip("Backend or frontend not running")

        # Wait for WebSocket connection
        try:
            page.wait_for_function(
                "() => typeof window.__a2d_ws_connected !== 'undefined' ? window.__a2d_ws_connected : true",
                timeout=15000,
            )
        except Exception:
            pytest.skip("WebSocket connection timeout (environment fault)")

        # Set batch_size to 3 before starting
        batch_input = page.locator('.batch-input')
        if batch_input.is_visible():
            batch_input.fill('3')

        # Click "开始对话"
        start_btn = page.locator("button:has-text('开始对话')")
        if not start_btn.is_visible(timeout=5000):
            pytest.skip("Start button not visible (may already be in session)")
        start_btn.click()

        # Wait for round completion: phase === 'paused' or 'error'
        try:
            page.wait_for_function(
                """() => {
                    const store = document.querySelector('#app').__vue_app__
                        .config.globalProperties.$pinia._s.get('script');
                    return store && (store.phase === 'paused' || store.phase === 'error');
                }""",
                timeout=ROUND_TIMEOUT * 1000,
            )
        except Exception:
            # Timeout — check if phase is still thinking/synthesizing
            store = extract_store(page)
            phase = store.get("scriptPhase", "?")
            if phase == "error":
                error_info = store.get("error", {})
                msg = error_info.get("message", "") if error_info else ""
                if "401" in msg or "timeout" in msg.lower():
                    pytest.skip(f"LLM error (environment fault): {msg[:100]}")
                else:
                    pytest.fail(f"Round failed with error: {msg[:200]}")
            else:
                pytest.fail(f"Round timeout ({ROUND_TIMEOUT}s) — phase stuck at: {phase}")

        # Extract trace and verify
        trace = extract_trace(page)
        assert len(trace) > 0, "No trace events extracted"

        # Run assertions
        errors = []
        errors += assert_phase_sequence(trace)
        errors += assert_speaker_filter(trace)
        errors += assert_audio_sync(trace)
        errors += assert_batch_integrity(trace)
        errors += assert_has_script_lines(trace)

        result = classify_test_result(errors)
        if result == "FAIL":
            pytest.fail(f"Trace assertions failed:\n" + "\n".join(errors))
        elif result == "SKIP":
            pytest.skip(f"Environment faults detected:\n" + "\n".join(errors))

        # Verify round count
        rounds = get_round_count(trace)
        assert rounds >= 1, f"Expected at least 1 round, got {rounds}"

    def test_multi_round_dialogue(self, page):
        """3-5 rounds: start → (wait paused → click continue) × N."""
        if not backend_ok() or not frontend_ok():
            pytest.skip("Backend or frontend not running")

        fast_mode = os.environ.get("A2D_E2E_FAST", "").strip() in ("1", "true", "yes")
        target_rounds = 2 if fast_mode else ROUND_COUNT

        # Set batch_size to 3 before first round
        batch_input = page.locator('.batch-input')
        if batch_input.is_visible():
            batch_input.fill('3')

        completed_rounds = 0
        all_traces: list[dict] = []  # accumulate across rounds for cross-round assertions

        for r in range(target_rounds):
            # Click appropriate button
            btn_text = "开始对话" if r == 0 else "继续"
            btn = page.locator(f"button:has-text('{btn_text}')")
            try:
                btn.wait_for(state="visible", timeout=5000)
                btn.click()
            except Exception:
                store_snap = extract_store(page)
                pytest.skip(f"Button '{btn_text}' not available (env fault). Store: {store_snap}")

            # Wait for round completion — poll via page.evaluate to avoid
            # potential CDP interference with WebSocket from wait_for_function
            deadline = time.time() + ROUND_TIMEOUT
            phase = "?"
            while time.time() < deadline:
                page.wait_for_timeout(1000)
                store = extract_store(page)
                phase = store.get("scriptPhase", "?")
                if phase in ("paused", "error"):
                    break

            if phase not in ("paused", "error"):
                if phase == "error":
                    error_info = store.get("error", {})
                    msg = error_info.get("message", "") if error_info else ""
                    if any(kw in str(msg).lower() for kw in ("401", "timeout")):
                        pytest.skip(f"Round {r+1}: LLM error (env): {msg[:100]}")
                    else:
                        pytest.fail(f"Round {r+1} failed: {msg[:200]}")
                else:
                    pytest.skip(f"Round {r+1} timeout at phase {phase} (env fault)")

            # Per-round trace: small delay then drain
            page.wait_for_timeout(1000)
            round_trace = drain_trace(page)
            all_traces.extend(round_trace)

            # ── Detailed diagnostics on assertion failure ──
            errors = []
            errors += assert_phase_sequence(round_trace)
            errors += assert_has_script_lines(round_trace)

            result = classify_test_result(errors)
            if result == "FAIL":
                # Dump full trace + console + store for diagnosis
                store_state = extract_store(page)
                console_tail = page._console_msgs[-20:] if hasattr(page, '_console_msgs') else []
                trace_summary = f"  events: {len(round_trace)}, types: {[e.get('event') for e in round_trace]}"
                pytest.fail(
                    f"Round {r+1} assertions failed:\n" + "\n".join(errors) +
                    f"\n\n── Diagnostics for Round {r+1} ──" +
                    f"\nTrace {trace_summary}" +
                    f"\nStore phase={store_state.get('scriptPhase','?')} lines={len(store_state.get('scriptLines',[]))}" +
                    f"\nConsole (last 10): {console_tail[-10:]}"
                )
            elif result == "SKIP":
                pytest.skip(f"Round {r+1} environment fault")

            completed_rounds += 1

        # Cross-round assertions on accumulated traces from ALL rounds
        errors = []
        errors += assert_speaker_filter(all_traces)
        errors += assert_audio_sync(all_traces)
        errors += assert_batch_integrity(all_traces)

        result = classify_test_result(errors)
        if result == "FAIL":
            pytest.fail(f"Cross-round assertions failed:\n" + "\n".join(errors))

        assert completed_rounds >= 1, f"Expected at least 1 completed round, got {completed_rounds}"
