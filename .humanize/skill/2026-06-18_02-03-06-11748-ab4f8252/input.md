# Ask Codex Input

## Question

A2D Studio Stage 10 RLCR round 0 status report. Please review and give recommendations for next steps.

TODAY ACCOMPLISHED:
1. Plan generated (gen-plan → gen-idea → gen-plan) — 14 tasks, 5 ACs
2. Plan executed — all 14 tasks completed:
   - AC-1: Fixed edit protocol (handle_continue type mismatch — list vs dict)
   - AC-2: KeepAlive tab persistence in ScriptPanel
   - AC-3: Emotion-to-avatar pipeline end-to-end (backend parse → WS → frontend store)
   - AC-4: Clickable EventTrack with navigation + auto-scroll
   - AC-5: Store-level editing state (selectedLineId, editedText map, activeTab)
3. Post-test bugs found + fixed via headed Playwright + log analysis:
   - BUG 1: `LLMManager.process_message()` sync call was awaited → crash. Fixed: removed await
   - BUG 2: Translation fail guard — Chinese sent to GSV. Fixed: skip TTS if translation empty
   - BUG 3: Missing LLM prompt visibility. Fixed: full message dump to debug log
   - BUG 4: Thinking showed wrong/empty character name. Fixed: generic "思考中..."
   - BUG 5: Avatar 404 on missing emotion. Fixed: universal fallback to "正常" + warning
   - BUG 6: LLM format degradation after edit. Fixed: always include <TTS> in history
   - BUG 7: GSV no log capture. Fixed: _log.bat files with timestamped output
   - BUG 8: Anti-clipping `，，` broke audio. Reverted.
4. Commits: 7 commits on local-develop

REMAINING BUGS (found in latest test, NOT yet fixed):
1. P0: `_a2d_translate_for_tts` is `async def` but called WITHOUT await → returns coroutine object → stored as tts_text → sent to GSV as JSON → "coroutine is not JSON serializable". Also leaks into LLM history via target_line.tts_text = coroutine.
2. P0: `batch_size` setting exists in SessionRuntime but is dead code — never used in prompt or LLM call. LLM generates multiple lines anyway because max_tokens=8192.
3. P1: `a2d_generate_next` stores ALL parsed lines in session.script_lines but only sends first to frontend. User doesn't see extra lines, but they enter LLM context silently.
4. P1: System prompt truncated at 300 chars in debug log — can't see format instructions at end.

DESIGN ISSUE RAISED:
- batch_size should control prompt wording + processing flow
- When LLM generates N lines (potentially != batch_size), the flow should handle all of them
- N should be discovered from actual LLM output, not hardcoded

FILES WITH UNCOMMITTED CHANGES:
- core.py: removed prompt truncation (full logging), async def → def for translate helper

Please review and suggest:
CORE_RISKS: highest-risk items to fix first
RECOMMENDED_ORDER: suggested fix order for remaining bugs
DESIGN_FEEDBACK: thoughts on the batch_size / multi-line handling design
ANYTHING_MISSED: anything we may have overlooked

## Configuration

- Model: gpt-5.5
- Effort: high
- Timeout: 3600s
- Timestamp: 2026-06-18_02-03-06
- Tool: codex
