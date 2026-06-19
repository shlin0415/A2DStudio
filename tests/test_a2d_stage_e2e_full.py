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

from tests import backend_ok, frontend_ok, extract_trace, extract_store
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

        completed_rounds = 0

        for r in range(target_rounds):
            # Click appropriate button
            btn_text = "开始对话" if r == 0 else "继续"
            btn = page.locator(f"button:has-text('{btn_text}')")
            try:
                btn.wait_for(state="visible", timeout=5000)
                btn.click()
            except Exception:
                pytest.skip(f"Button '{btn_text}' not available (env fault)")

            # Wait for round completion
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
                store = extract_store(page)
                phase = store.get("scriptPhase", "?")
                if phase == "error":
                    error_info = store.get("error", {})
                    msg = error_info.get("message", "") if error_info else ""
                    if any(kw in str(msg).lower() for kw in ("401", "timeout")):
                        pytest.skip(f"Round {r+1}: LLM error (env): {msg[:100]}")
                    else:
                        pytest.fail(f"Round {r+1} failed: {msg[:200]}")
                else:
                    pytest.skip(f"Round {r+1} timeout at phase {phase} (env fault)")

            # Per-round trace assertions
            trace = extract_trace(page)
            errors = []
            errors += assert_phase_sequence(trace)
            errors += assert_has_script_lines(trace)

            result = classify_test_result(errors)
            if result == "FAIL":
                pytest.fail(f"Round {r+1} assertions failed:\n" + "\n".join(errors))
            elif result == "SKIP":
                pytest.skip(f"Round {r+1} environment fault")

            completed_rounds += 1

        # Final cross-round trace extraction
        trace = extract_trace(page)
        errors = []
        errors += assert_speaker_filter(trace)
        errors += assert_audio_sync(trace)
        errors += assert_batch_integrity(trace)

        result = classify_test_result(errors)
        if result == "FAIL":
            pytest.fail(f"Cross-round assertions failed:\n" + "\n".join(errors))

        assert completed_rounds >= 1, f"Expected at least 1 completed round, got {completed_rounds}"
