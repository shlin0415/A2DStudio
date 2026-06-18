# Ask Codex Input

## Question

You are reviewing a candidate implementation plan for A2D Studio (CP dialogue script editor on LingChat Python/Vue stack).

CONTEXT: Three subagent explorations confirmed:

1. EDIT PROTOCOL BROKEN: `handle_continue(generation_id, edits: dict | None)` at session_runtime.py:62 receives a LIST `[{id, text}]` from the frontend, but the guard `if edits and "modified_lines" in edits:` performs list-membership testing. The string "modified_lines" is never an element of the list, so `_apply_edits` is never reached. ALL USER EDITS ARE SILENTLY DISCARDED.

2. ScriptPanel.vue uses v-if/v-else (no KeepAlive) — component state destroyed on tab switch. KeepAlive is the idiomatic Vue fix, better than v-show (pauses watchers, frees DOM).

3. EMOTION PIPELINE: 8+ break points from LLM output to avatar rendering. `_a2d_parse_script_line` strips emotion with `re.sub(r"^【.*?】", "", text)` without capturing. ScriptLine dataclass lacks emotion field. ScriptLinePayload lacks emotion. WS dict omits emotion. Frontend has no speaker→roleId mapping. `useA2DWebSocket.ts:44` hardcodes emotion to "正常". GameRoleAvatar watcher works but never receives emotion changes. Two emotions (无语, 尴尬) missing from EMOTION_CONFIG_EMO.

4. Additional gaps: EventTrack no auto-scroll, no `editTargetLineId` separation from `currentLine` (overloading causes state machine conflicts), no edit-scope disclosure when editing old lines (subsequent lines discarded without warning).

CANDIDATE PLAN:

## Goal: Fix three foundational issues blocking the A2D script editor

### AC-1: Edit Protocol — user text edits are applied to script_lines before next LLM call
- Positive: User edits text, clicks Continue → LLM receives modified context
- Negative: Unmodified continue → no edits applied, LLM generates normally

### AC-2: Tab Persistence — editing state survives tab switches
- Positive: Edit text, switch to EventTrack, switch back → text preserved
- Negative: No edits made → ReviewPanel resets to currentLine.display_text on new line arrival

### AC-3: Emotion-to-Avatar — LLM emotion tags drive character sprite changes
- Positive: LLM outputs 【害羞】→ Emma avatar changes to shy expression
- Negative: LLM outputs no emotion tag → avatar stays at previous emotion (not reverts to default)

### AC-4: EventTrack Click Navigation — clicking any line loads it for review
- Positive: Click line 3 in timeline → ReviewPanel shows line 3 content
- Negative: Click during thinking phase → edit area remains hidden, line highlighted in timeline

### AC-5: Store-Level Edit Persistence — per-line edited text survives tab switches
- Positive: Edit line 2, click line 3, click back to line 2 → edit preserved
- Negative: Click continue → edits committed, map entries cleared

### Milestones (in dependency order):

M1 — Fix Broken Edit Protocol (backend, ~15 LOC)
- session_runtime.py: Change edits param type to list[dict] | None, remove "modified_lines" guard, update _apply_edits to read "text" field and look up speaker from original line by ID
- Verify with existing test: test_session_runtime.py

M2 — Tab Persistence + KeepAlive (frontend, ~10 LOC)
- ScriptPanel.vue: Wrap content with <KeepAlive>, add onActivated/onDeactivated hooks
- Store: add selectedLineId field to script store for EventTrack click tracking

M3 — Clickable EventTrack (frontend, ~40 LOC)
- EventTrack.vue: add @click on .line-item, emit selectedLineId to store, visual highlight, auto-scroll to bottom on new lines
- ReviewPanel.vue: support displaying selectedLine when not in paused phase

M4 — Emotion Pipeline End-to-End (backend + frontend, ~60 LOC)
- Backend: script_overlay.py (emotion field in ScriptLine + ScriptLinePayload), core.py (extract+transmit emotion), a2d_message_handler.py (include emotion in WS payload)
- Frontend: script.ts (emotion in interface), useA2DWebSocket.ts (speaker→roleId mapping, set emotion on gameStore)

M5 — Store-Level Editing State (frontend, ~25 LOC)
- script.ts: editedText map, setEdited/clearEdited/commitEdits helpers
- ReviewPanel.vue: read/write from store instead of local ref

### Task Breakdown (12 tasks):

| ID | Description | Target AC | Tag | Depends |
|----|-------------|-----------|-----|---------|
| T1 | Fix handle_continue type and _apply_edits field mapping | AC-1 | coding | - |
| T2 | Verify edit protocol with unit test | AC-1 | coding | T1 |
| T3 | Add KeepAlive wrapper to ScriptPanel | AC-2 | coding | - |
| T4 | Add selectedLineId to script store | AC-2, AC-4 | coding | - |
| T5 | Add click handler + highlight to EventTrack | AC-4 | coding | T4 |
| T6 | Add auto-scroll to EventTrack on new lines | AC-4 | coding | T5 |
| T7 | Update ReviewPanel to support selectedLine display | AC-4 | coding | T4, T5 |
| T8 | Add emotion field to ScriptLine + ScriptLinePayload | AC-3 | coding | - |
| T9 | Extract emotion in _a2d_parse_script_line + transmit | AC-3 | coding | T8 |
| T10 | Build speaker→roleId mapping in frontend WS handler | AC-3 | coding | - |
| T11 | Set gameStore.gameRoles[roleId].emotion in script_line handler | AC-3 | coding | T9, T10 |
| T12 | Add editedText map to store + update ReviewPanel | AC-5 | coding | T1, T2 |

### Known Risks:
- Emotion field must be added simultaneously to both ScriptLine (backend dataclass) and ScriptLine (frontend interface) — WS schema validation will fail if one side is missing
- session_runtime tests may need updating for the new edit format
- 无语 and 尴尬 emotions have no avatar config — silent fallback to default

Review this plan. Output format:
AGREE: points accepted
DISAGREE: points rejected and why
REQUIRED_CHANGES: must-fix items
OPTIONAL_IMPROVEMENTS: non-blocking
UNRESOLVED: items needing user decision

## Configuration

- Model: gpt-5.5
- Effort: high
- Timeout: 3600s
- Timestamp: 2026-06-17_22-15-14
- Tool: codex
