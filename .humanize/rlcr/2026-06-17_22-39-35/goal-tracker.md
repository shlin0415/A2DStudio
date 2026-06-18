# Goal Tracker

<!--
This file tracks the ultimate goal, acceptance criteria, and plan evolution.
It prevents goal drift by maintaining a persistent anchor across all rounds.

RULES:
- IMMUTABLE SECTION: Do not modify after initialization
- MUTABLE SECTION: Update each round, but document all changes
- Every task must be in one of: Active, Completed, or Deferred
- Deferred items require explicit justification
-->

## IMMUTABLE SECTION
<!-- Do not modify after initialization -->

### Ultimate Goal

Fix three foundational bugs in the A2D Studio script editor that block the core editing workflow:

1. **Edit Protocol Broken**: Frontend sends `edits: [{id, text}]` but backend `handle_continue` expects `edits["modified_lines"]` — a type mismatch (`list` vs `dict`) that causes ALL user text edits to be silently discarded. The LLM never sees modified text.
2. **Tab State Loss**: `ScriptPanel.vue` uses `v-if`/`v-else` which destroys ReviewPanel on tab switch, losing `editingText`, `userEdited`, and `lastLineId`.
3. **Emotion Pipeline Severed**: LLM outputs emotion tags (【害羞】, 【认真】, etc.) that are parsed but discarded at `_a2d_parse_script_line`. No emotion data flows through the WS message layer, store, or rendering — character sprites remain stuck at default expression.

Additionally, make EventTrack lines clickable for navigation and auto-scroll to new lines.

## Acceptance Criteria

### Acceptance Criteria
<!-- Each criterion must be independently verifiable -->
<!-- Claude must extract or define these in Round 0 -->


- AC-1: Edit Protocol — user text edits are applied to the dialogue before the next LLM call
  - Positive Tests:
    - User edits display_text of the current line, clicks Continue → edited text appears in LLM context and next response reflects the change
    - User clicks Continue without editing → no edits applied, LLM generates normally
  - Negative Tests:
    - Backend receives empty edits list → `_apply_edits` is skipped, generation proceeds normally without crash
    - Backend receives edit with unknown line ID → error logged, generation continues with unmodified line

- AC-2: Tab Persistence — editing state survives switching between ReviewPanel and EventTrack
  - Positive Tests:
    - User edits text in ReviewPanel, switches to EventTrack, switches back → editingText displays the edited text (not reset to original)
    - No edits made → switching tabs and returning shows currentLine.display_text
  - Negative Tests:
    - New script_line arrives (different line ID) while on EventTrack tab → switching back shows new line's display_text, not stale old line

- AC-3: Emotion-to-Avatar — LLM emotion tags drive character sprite changes on the frontend
  - Positive Tests:
    - LLM outputs `【害羞】...` → Emma's sprite changes to shy expression within one render cycle
    - LLM outputs `【认真】...` → Hiro's sprite changes to serious expression
    - LLM outputs no emotion tag → avatar keeps previous emotion (explicit decision: not reset to default)
  - Negative Tests:
    - LLM outputs an emotion not in EMOTION_CONFIG_EMO → avatar falls back to `'正常'` without crash
    - Emotion field is empty string → avatar keeps previous emotion

---

## MUTABLE SECTION
<!-- Update each round with justification for changes -->

### Plan Version: 1 (Updated: Round 0)

#### Plan Evolution Log
<!-- Document any changes to the plan with justification -->
| Round | Change | Reason | Impact on AC |
|-------|--------|--------|--------------|
| 0 | Initial plan | - | - |

#### Active Tasks
<!-- Mainline tasks only: each task must directly advance the current round objective and carry routing metadata -->
| Task | Target AC | Status | Tag | Owner | Notes |
|------|-----------|--------|-----|-------|-------|
| T1: Fix handle_continue signature | AC-1 | completed | coding | claude | dict→list[dict] type fix |
| T2: Update _apply_edits field mapping | AC-1 | completed | coding | claude | read {id, text}, lookup speaker |
| T3: Unit test for edit protocol | AC-1 | completed | coding | claude | test_session_runtime.py |
| T4: Add emotion to dataclasses | AC-3 | completed | coding | claude | ScriptLine + ScriptLinePayload |
| T5: Extract emotion in parse + WS dict | AC-3 | completed | coding | claude | core.py changes |
| T6: Frontend emotion + speakerToRoleId | AC-3 | completed | coding | claude | TS interface + WS handler |
| T7: Set emotion on gameStore | AC-3 | completed | coding | claude | script_line handler update |
| T8: Missing emotions to config | AC-3 | completed | coding | claude | 无语 + 尴尬 |
| T9: KeepAlive wrapper | AC-2 | completed | coding | claude | ScriptPanel.vue |
| T10: selectedLineId + editedText | AC-2,4,5 | completed | coding | claude | script.ts store |
| T11: EventTrack click + highlight + scroll | AC-4 | completed | coding | claude | @click + CSS + scroll watcher |
| T12: ReviewPanel selectedLine + store edit | AC-4,5 | completed | coding | claude | ReviewPanel.vue |
| T13: Verify backend tests | AC-1 | completed | analyze | codex | 103 passed, 4 skipped, 0 failed |
| T14: Verify frontend build | AC-2,3,4,5 | completed | analyze | codex | ✓ built in 9.74s |

### Blocking Side Issues
<!-- Only issues that directly block current mainline progress belong here -->
| Issue | Discovered Round | Blocking AC | Resolution Path |
|-------|-----------------|-------------|-----------------|

### Queued Side Issues
<!-- Non-blocking issues stay queued and must NOT replace the round objective -->
| Issue | Discovered Round | Why Not Blocking | Revisit Trigger |
|-------|-----------------|------------------|-----------------|

### Completed and Verified
<!-- Only move tasks here after Codex verification -->
| AC | Task | Completed Round | Verified Round | Evidence |
|----|------|-----------------|----------------|----------|
| AC-1 | T1-T3: Edit protocol fix | Round 0 | Round 0 | 103 passed / 4 skipped / 0 failed |
| AC-3 | T4-T8: Emotion pipeline | Round 0 | Round 0 | 103 passed, frontend ✓ built |
| AC-2 | T9: KeepAlive wrapper | Round 0 | Round 0 | frontend ✓ built in 9.74s |
| AC-2,4,5 | T10: selectedLineId + editedText | Round 0 | Round 0 | frontend ✓ built in 9.74s |
| AC-4 | T11: EventTrack click + scroll | Round 0 | Round 0 | frontend ✓ built in 9.74s |
| AC-4,5 | T12: ReviewPanel store editing | Round 0 | Round 0 | frontend ✓ built in 9.74s |

### Explicitly Deferred
<!-- Items here require strong justification -->
| Task | Original AC | Deferred Since | Justification | When to Reconsider |
|------|-------------|----------------|---------------|-------------------|

