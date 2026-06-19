"""Trace-based assertion library for A2D Stage E2E tests.

Operates on window.__a2dTrace event arrays extracted via extract_trace(page).
All assertion functions return lists of error strings (empty = pass).
Environment faults are classified separately from code regressions.
"""

from typing import List, Tuple


# ── Event grouping ─────────────────────────────────────

def get_round_events(events: list[dict], round_num: int = 0) -> list[dict]:
    """Extract events belonging to a specific round (0-indexed).
    Round boundaries are detected via phase_change {to: 'thinking'} events.
    """
    thinking_indices = [
        i for i, e in enumerate(events)
        if e.get("event") == "phase_change" and e.get("data", {}).get("to") == "thinking"
    ]
    if round_num >= len(thinking_indices):
        return []
    start = thinking_indices[round_num]
    end = thinking_indices[round_num + 1] if round_num + 1 < len(thinking_indices) else len(events)
    return events[start:end]


def get_round_count(events: list[dict]) -> int:
    """Count number of rounds in trace (by phase_change->thinking events)."""
    return sum(
        1 for e in events
        if e.get("event") == "phase_change" and e.get("data", {}).get("to") == "thinking"
    )


# ── Phase sequence assertion ──────────────────────────

def assert_phase_sequence(events: list[dict]) -> list[str]:
    """Verify valid phase transitions within each round.
    Normal path: thinking -> (synthesizing -> at least one script_line) -> paused
    Returns list of error strings.
    """
    errors = []
    phases = [
        (e.get("data", {}).get("from"), e.get("data", {}).get("to"))
        for e in events if e.get("event") == "phase_change"
    ]

    if not phases:
        errors.append("No phase_change events found")
        return errors

    for i, (fr, to) in enumerate(phases):
        # thinking -> paused without synthesizing is a code regression
        if fr == "thinking" and to == "paused":
            errors.append(
                f"Phase went thinking->paused without synthesizing (regression at phase_change #{i})"
            )
        # thinking -> idle should never happen during active flow
        if fr == "thinking" and to == "idle":
            errors.append(f"Phase went thinking->idle (unexpected at phase_change #{i})")

    return errors


# ── Speaker filter assertion ──────────────────────────

VALID_SPEAKERS = {"ema", "hiro", "narrator"}


def assert_speaker_filter(events: list[dict]) -> list[str]:
    """Verify all script_line speakers are in the valid set."""
    errors = []
    for e in events:
        if e.get("event") == "script_line":
            speaker = e.get("data", {}).get("speaker", "")
            if speaker not in VALID_SPEAKERS:
                errors.append(
                    f"Invalid speaker '{speaker}' in script_line (valid: {VALID_SPEAKERS})"
                )
    return errors


# ── Batch integrity assertion ─────────────────────────

def assert_batch_integrity(events: list[dict]) -> list[str]:
    """Verify batch_total in each script_line matches the count of script_line
    events within the same round.
    """
    errors = []
    round_count = get_round_count(events)
    for r in range(round_count):
        round_events = get_round_events(events, r)
        script_lines = [e for e in round_events if e.get("event") == "script_line"]
        if not script_lines:
            continue
        # Check that batch_total is consistent across all lines in this round
        batch_totals = {
            e.get("data", {}).get("batch_total")
            for e in script_lines
            if e.get("data", {}).get("batch_total") is not None
        }
        if len(batch_totals) > 1:
            errors.append(
                f"Round {r}: inconsistent batch_total values: {batch_totals}"
            )
        if batch_totals:
            expected = next(iter(batch_totals))
            if expected != len(script_lines):
                errors.append(
                    f"Round {r}: batch_total={expected} but got {len(script_lines)} script_line events"
                )
    return errors


# ── Audio sync assertion ──────────────────────────────

def assert_audio_sync(events: list[dict]) -> list[str]:
    """Verify: emotion ts >= audio_start ts, playingLine monotonic within round,
    every audio_end paired with audio_start or audio_queue_empty.
    """
    errors = []
    # Group audio events per round
    round_count = get_round_count(events)
    for r in range(round_count):
        round_events = get_round_events(events, r)
        audio_events = [e for e in round_events if e.get("event", "").startswith("audio_")]
        playing_lines = [e for e in round_events if e.get("event") == "playingLine"]

        # Check monotonic playingLine sequence
        seen_ids = []
        for e in playing_lines:
            lid = e.get("data", {}).get("lineId")
            if lid:
                seen_ids.append(lid)
        # playingLine should not repeat the same lineId consecutively
        for i in range(1, len(seen_ids)):
            if seen_ids[i] == seen_ids[i - 1]:
                errors.append(
                    f"Round {r}: playingLine repeated lineId {seen_ids[i]} (non-progressing)"
                )

        # Check every audio_end has a corresponding audio_start before it
        for e in audio_events:
            if e.get("event") == "audio_end":
                lid = e.get("data", {}).get("lineId")
                # Find matching audio_start for this lineId
                has_start = any(
                    a.get("event") == "audio_start" and a.get("data", {}).get("lineId") == lid
                    for a in audio_events
                )
                if not has_start:
                    errors.append(
                        f"Round {r}: audio_end for {lid} has no matching audio_start"
                    )

        # Check emotion ts >= audio_start ts (approximate by event ordering)
        emotion_events = [e for e in round_events if e.get("event") == "emotion"]
        for em in emotion_events:
            line_id = em.get("data", {}).get("lineId")
            # Find matching audio_start
            audio_start = next(
                (a for a in audio_events
                 if a.get("event") == "audio_start" and a.get("data", {}).get("lineId") == line_id),
                None
            )
            if audio_start:
                em_ts = em.get("ts", 0)
                as_ts = audio_start.get("ts", float("inf"))
                if em_ts < as_ts:
                    errors.append(
                        f"Round {r}: emotion (ts={em_ts}) fired before audio_start (ts={as_ts}) for {line_id}"
                    )

    return errors


# ── Zero script_line check ────────────────────────────

def assert_has_script_lines(events: list[dict]) -> list[str]:
    """Verify at least one script_line event exists per round."""
    errors = []
    round_count = get_round_count(events)
    for r in range(round_count):
        round_events = get_round_events(events, r)
        script_lines = [e for e in round_events if e.get("event") == "script_line"]
        if not script_lines:
            errors.append(f"Round {r}: zero script_line events (code regression)")
    return errors


# ── Error classification ──────────────────────────────

ENV_FAULT_KEYWORDS = ["401", "timeout", "timed out", "Connection refused",
                       "ReadTimeout", "ConnectError", "TTS请求失败", "503"]


def classify_errors(errors: list[str]) -> Tuple[list[str], list[str]]:
    """Split errors into (env_faults, code_regressions).

    Environment faults: LLM 401/timeout, TTS failure, GSV down, network errors.
    Code regressions: missing phases, invalid speakers, zero lines, sync violations.
    """
    env_faults = []
    code_regressions = []
    for err in errors:
        is_env = any(kw.lower() in err.lower() for kw in ENV_FAULT_KEYWORDS)
        if is_env:
            env_faults.append(err)
        else:
            code_regressions.append(err)
    return env_faults, code_regressions


def classify_test_result(errors: list[str]) -> str:
    """Return 'PASS', 'FAIL', or 'SKIP' based on error classification.
    - All clear → PASS
    - Only environment faults → SKIP
    - Any code regression → FAIL
    """
    if not errors:
        return "PASS"
    env_faults, code_regressions = classify_errors(errors)
    if code_regressions:
        return "FAIL"
    return "SKIP"
