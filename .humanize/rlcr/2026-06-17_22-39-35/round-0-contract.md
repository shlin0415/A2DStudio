# Round 0 Contract

## Mainline Objective
Fix the broken edit protocol (AC-1) and severed emotion pipeline (AC-3) — the two highest-priority bugs that block editor functionality.

## Target ACs
- AC-1: Edit Protocol — user text edits are applied before next LLM call
- AC-3: Emotion-to-Avatar — LLM emotion tags drive character sprite changes

## Tasks in Scope
- T1-T3: Edit protocol fix (backend — session_runtime.py)
- T4-T8: Emotion pipeline end-to-end (backend + frontend)
- T13: Verify backend tests pass
- T14: Verify frontend build passes

## Blocking Side Issues
None known.

## Queued Side Issues (out of scope this round)
- AC-2, AC-4, AC-5 (T9-T12): Tab persistence, clickable EventTrack, store editing state — deferred to round completion or next round
- DEC-1: Selectable line retention on non-latest edit — deferred per plan

## Round Success Criteria
1. `uv run pytest tests/ -v --tb=short` returns 100+ passed with no regressions
2. `cd frontend_vue && pnpm run type-check` returns no errors
3. `cd frontend_vue && pnpm run build-only` succeeds
4. Edit protocol: backend correctly applies `{id, text}` edits to script_lines
5. Emotion pipeline: emotion flows from LLM output tag → WS → frontend store → GameRoleAvatar
