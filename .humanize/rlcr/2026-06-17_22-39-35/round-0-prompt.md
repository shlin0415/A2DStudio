Read and execute below with ultrathink

## Goal Tracker Setup (REQUIRED FIRST STEP)

Before starting implementation, you MUST initialize the Goal Tracker:

1. Read @/d/aaa-new/setups/a2d-studio/ref/LingChat/.humanize/rlcr/2026-06-17_22-39-35/goal-tracker.md
2. If the "Ultimate Goal" section says "[To be extracted...]", extract a clear goal statement from the plan
3. If the "Acceptance Criteria" section says "[To be defined...]", define 3-7 specific, testable criteria
4. Populate the "Active Tasks" table with MAINLINE tasks from the plan, mapping each to an AC and filling Tag/Owner
5. Record any already-known side issues in either "Blocking Side Issues" or "Queued Side Issues"
6. Write the updated goal-tracker.md

## Round Contract Setup (REQUIRED BEFORE CODING)

Before starting implementation, create @/d/aaa-new/setups/a2d-studio/ref/LingChat/.humanize/rlcr/2026-06-17_22-39-35/round-0-contract.md with:

1. **One mainline objective** for this round
2. **Target ACs** (1-2 ACs only)
3. **Blocking side issues in scope** for this round
4. **Queued side issues out of scope** for this round
5. **Round success criteria**

Use this contract to keep the round focused. Do NOT let non-blocking bugs or cleanup work replace the mainline objective.

**IMPORTANT**: The IMMUTABLE SECTION can only be modified in Round 0. After this round, it becomes read-only.

---

## Implementation Plan

For all tasks that need to be completed, please use the Task system (TaskCreate, TaskUpdate, TaskList).

Every task MUST start with exactly one lane tag:
- `[mainline]` for plan-derived work that directly advances the round objective
- `[blocking]` for issues that prevent the mainline objective from succeeding safely
- `[queued]` for non-blocking bugs, cleanup, or follow-up work

Rules:
- `[mainline]` tasks are the primary success condition for the round
- `[blocking]` tasks may be resolved in the round only if they truly block mainline progress
- `[queued]` tasks must NOT become the round objective and do NOT need to be cleared before moving on
- If a new issue is not blocking the current objective, tag it `[queued]` and keep moving on the mainline

## Task Tag Routing (MUST FOLLOW)

Each task must have one routing tag from the plan: `coding` or `analyze`.

- Tag `coding`: Claude executes the task directly.
- Tag `analyze`: Claude must execute via `/humanize:ask-codex`, then integrate Codex output.
- Keep Goal Tracker "Active Tasks" columns **Tag** and **Owner** aligned with execution (`coding -> claude`, `analyze -> codex`).
- If a task has no explicit tag, default to `coding` (Claude executes directly).

# A2D Script Editor Foundation: Edit Protocol, Tab Persistence, Emotion Pipeline

## Goal Description

Fix three foundational bugs in the A2D Studio script editor that block the core editing workflow:

1. **Edit Protocol Broken**: Frontend sends `edits: [{id, text}]` but backend `handle_continue` expects `edits["modified_lines"]` — a type mismatch (`list` vs `dict`) that causes ALL user text edits to be silently discarded. The LLM never sees modified text.
2. **Tab State Loss**: `ScriptPanel.vue` uses `v-if`/`v-else` which destroys ReviewPanel on tab switch, losing `editingText`, `userEdited`, and `lastLineId`.
3. **Emotion Pipeline Severed**: LLM outputs emotion tags (【害羞】, 【认真】, etc.) that are parsed but discarded at `_a2d_parse_script_line`. No emotion data flows through the WS message layer, store, or rendering — character sprites remain stuck at default expression.

Additionally, make EventTrack lines clickable for navigation and auto-scroll to new lines.

## Acceptance Criteria

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

- AC-4: EventTrack Click Navigation — clicking any line loads it for review
  - Positive Tests:
    - Click line index 3 in EventTrack → ScriptPanel switches to ReviewPanel tab, shows line 3 content
    - Click line index 1 → highlight moves to line 1, previous line highlight removed
  - Negative Tests:
    - Click line during thinking/synthesizing phase → line highlighted in timeline, ReviewPanel continues showing preview (edit area hidden)
    - EventTrack has zero lines → empty state shown, no clickable elements

- AC-5: Store-Level Edit Persistence — per-line edited text survives tab switches
  - Positive Tests:
    - Edit line 2 text → click line 3 → click back to line 2 → edited text still displayed
    - Edit line, click Continue → edit submitted, map entry cleared for that line
  - Negative Tests:
    - Edit text that equals original display_text → no dirty entry created, handleContinue sends empty edits
    - store.reset() called → editedText map cleared

## Path Boundaries

### Upper Bound (Maximum Acceptable Scope)

All five ACs are met with `<KeepAlive>` for tab persistence, end-to-end emotion pipeline (backend parse → WS → frontend store → avatar), clickable EventTrack with auto-scroll and visual highlight, store-level `editedText` map with proper lifecycle management, and the edit protocol fixed on both `handle_continue` signature and `_apply_edits` field mapping. Edit of non-latest lines shows a confirmation dialog warning about truncation but does not block the edit. Missing emotions (无语, 尴尬) are added to EMOTION_CONFIG_EMO. `_a2d_build_messages` includes emotion in LLM history reconstruction.

### Lower Bound (Minimum Acceptable Scope)

AC-1 (edit protocol fix) is the non-negotiable minimum — without it all editing is silently broken. AC-3 (emotion pipeline) is a close second as it's the most visible UX gap. If scope must be reduced, AC-2 (keep-alive) can be deferred by telling users not to switch tabs during editing, and AC-4 (clickable EventTrack) can be deferred since lines are viewable (just not clickable). AC-5 (store editing state) can be deferred if AC-2 is deferred since there's no cross-tab editing to persist.

### Allowed Choices

- Can use: Vue `<KeepAlive>` with `v-if`/`v-else` (idiomatic Vue tab switching); `onActivated`/`onDeactivated` lifecycle hooks; Pinia store for shared state; Pydantic `Optional[str]` for new dataclass fields; regex capture groups for emotion extraction; `speakerToRoleId: Record<string, number>` mapping in composable
- Cannot use: `v-show` for tab persistence (both watchers running, wasteful); overloading `currentLine` for both "latest generated" and "user selected" (breaks state machine); separate WS message type for emotion (add to existing `script_line` payload)

## Feasibility Hints and Suggestions

### Conceptual Approach

**M1 — Edit Protocol Fix (Milestone 1, backend-first):**

The root cause is in `session_runtime.py:62`:
```python
async def handle_continue(self, generation_id: str, edits: dict | None = None):
    if edits and "modified_lines" in edits:  # list-membership test: always False
        self._apply_edits(edits["modified_lines"])
```

Fix: Change signature to `list[dict] | None`, guard to `if edits:`, and update `_apply_edits` to read `{id, text}` dicts — look up speaker from `self.script_lines` by ID, map `text` → both `display_text` and `tts_text`. Add unit test.

**M2 — Tab Persistence (frontend):**

Replace bare `v-if`/`v-else` in `ScriptPanel.vue` with `<KeepAlive>` wrapper. Add `selectedLineId: string | null` to script store for EventTrack click tracking (NOT overloading `currentLine`).

**M3 — Clickable EventTrack (frontend, depends on M2):**

Add `@click` on `.line-item` → set `store.selectedLineId`, switch `activeTab` to review. Add `.line-item--active` CSS class. Watch `store.lines.length` for auto-scroll to bottom (conditional: only if user is near bottom).

**M4 — Emotion Pipeline (backend + frontend, parallelizable with M1):**

Backend (8 steps): add `emotion: str = ""` to ScriptLine dataclass and ScriptLinePayload → extract emotion in `_a2d_parse_script_line` via regex capture group → include in WS dict at `a2d_generate_next` → include in `_a2d_build_messages` history reconstruction.

Frontend (4 steps): add `emotion` to ScriptLine TS interface → capture `script_role_key` in `a2d.characters` handler to build `speakerToRoleId` map → in `script_line` handler, set `gameStore.gameRoles[roleId].emotion = payload.emotion` → add 无语/尴尬 to EMOTION_CONFIG_EMO.

**M5 — Store-Level Edit State (frontend, depends on M1, M2):**

Add `editedText: Record<string, string>` to script store with `setEdited(id, text)`, `clearEdited(id)`, `commitEdits()` helpers. ReviewPanel reads/writes from store. `handleContinue` sends only the current line's edit (user decision: single-line edit only).

### Relevant References

- `ling_chat/core/session_runtime.py:62-121` — `handle_continue` + `_apply_edits` (edit protocol fix location)
- `ling_chat/core/ai_service/core.py:731-805` — `_a2d_parse_script_line` (emotion extraction location)
- `ling_chat/core/ai_service/core.py:547-561` — WS dict construction in `a2d_generate_next` (emotion field location)
- `ling_chat/schemas/script_overlay.py:30-47` — `ScriptLine` dataclass (add emotion field)
- `ling_chat/schemas/script_overlay.py:131-137` — `ScriptLinePayload` (add emotion field)
- `frontend_vue/src/components/game/ScriptPanel.vue:18-19` — `v-if`/`v-else` (add KeepAlive wrapper)
- `frontend_vue/src/components/game/EventTrack.vue:10-17` — `.line-item` rendering (add @click)
- `frontend_vue/src/components/game/ReviewPanel.vue:84-100` — watch on currentLine (add selectedLine handling)
- `frontend_vue/src/stores/modules/script.ts:6-74` — Pinia store (add selectedLineId, editedText, emotion)
- `frontend_vue/src/composables/useA2DWebSocket.ts:30-72` — WS handlers (speakerToRoleId map, emotion propagation)
- `frontend_vue/src/components/game/standard/GameRoleAvatar.vue:95-155` — emotion watcher (downstream consumer)
- `frontend_vue/src/controllers/emotion/config.ts:19-41` — EMOTION_CONFIG_EMO (add missing emotions)

## Dependencies and Sequence

### Milestones

1. Milestone 1: Fix Broken Edit Protocol (backend)
   - Phase A: Change `handle_continue` signature and guard in session_runtime.py
   - Phase B: Update `_apply_edits` to accept `{id, text}` format, look up speaker by ID
   - Phase C: Write/update unit test in test_session_runtime.py

2. Milestone 2: Tab Persistence + Store Foundation (frontend)
   - Step 1: Wrap ScriptPanel content with `<KeepAlive>`
   - Step 2: Add `selectedLineId` and `editedText` fields to script store
   - Step 3: Update ReviewPanel `handleContinue` to read from store-level editedText

3. Milestone 3: Clickable EventTrack (frontend, depends on M2)
   - Step 1: Add `@click` handler + `.line-item--active` highlight
   - Step 2: Add auto-scroll watcher on `store.lines.length`
   - Step 3: Update ReviewPanel to display `selectedLineId` content when not in paused phase

4. Milestone 4: Emotion Pipeline End-to-End (backend + frontend)
   - Step 1: Backend — add `emotion` field to ScriptLine, ScriptLinePayload, WS dict, LLM history
   - Step 2: Backend — extract emotion via regex capture group in `_a2d_parse_script_line`
   - Step 3: Frontend — add `emotion` to ScriptLine interface, build speakerToRoleId map
   - Step 4: Frontend — set gameStore.gameRoles[roleId].emotion in script_line handler
   - Step 5: Frontend — add 无语 and 尴尬 to EMOTION_CONFIG_EMO

Milestone 1 and Milestone 4 (backend portions) can run in parallel. Milestone 2 blocks Milestone 3. Milestone 5 is integrated into M2.

## Task Breakdown

| Task ID | Description | Target AC | Tag | Depends On |
|---------|-------------|-----------|-----|------------|
| T1 | Update `handle_continue` signature: `dict` → `list[dict]`, remove `"modified_lines"` guard | AC-1 | coding | - |
| T2 | Update `_apply_edits` to read `{id, text}`, look up speaker from script_lines by ID | AC-1 | coding | T1 |
| T3 | Write unit test for edit protocol: edit submitted → line updated in script_lines | AC-1 | coding | T2 |
| T4 | Add `emotion: str` to ScriptLine dataclass and ScriptLinePayload | AC-3 | coding | - |
| T5 | Extract emotion via regex capture group in `_a2d_parse_script_line`, include in WS dict + LLM history | AC-3 | coding | T4 |
| T6 | Add `emotion` to ScriptLine TS interface, build speakerToRoleId map in a2d.characters handler | AC-3 | coding | T5 |
| T7 | Set `gameStore.gameRoles[roleId].emotion` in script_line WS handler | AC-3 | coding | T6 |
| T8 | Add 无语 and 尴尬 to EMOTION_CONFIG_EMO | AC-3 | coding | - |
| T9 | Wrap ScriptPanel content with `<KeepAlive>`, add onActivated sync | AC-2 | coding | - |
| T10 | Add `selectedLineId` + `editedText` map to script store | AC-2, AC-4, AC-5 | coding | T9 |
| T11 | Add `@click` + highlight + auto-scroll to EventTrack | AC-4 | coding | T10 |
| T12 | Update ReviewPanel: support selectedLine display, read/write editedText from store | AC-4, AC-5 | coding | T10, T11 |
| T13 | Verify backend tests pass with edit protocol changes | AC-1 | analyze | T3 |
| T14 | Verify frontend type-check + build pass with all changes | AC-2, AC-3, AC-4, AC-5 | analyze | T7, T12 |

## Claude-Codex Deliberation

### Agreements

- All AC bugs exist as diagnosed and are verified against codebase
- `<KeepAlive>` is the correct Vue pattern, not `v-show`
- `selectedLineId` must be separate from `currentLine` to avoid state machine conflicts
- Emotion pipeline needs end-to-end fix (backend dataclass → WS → frontend store → avatar) — partial fix is useless
- Edit protocol is the highest-priority fix (blocks all editing workflows)

### Resolved Disagreements

- **M4 target file**: Codex corrected Claude's listing of `a2d_message_handler.py` as needing changes. The WS payload is built in `core.py`'s `a2d_generate_next` (plain dict), not the handler. Fix: M4 targets core.py for payload construction.
- **M1 LOC estimate**: Claude estimated ~15 LOC. Codex corrected to ~30-40 LOC including unit test and `_apply_edits` rewrite. Fix: Accepted, updated estimate.
- **M5 handleContinue scope**: Claude's plan had ambiguity about whether `handleContinue` sends all accumulated edits or just current. Codex flagged this. User resolved: single-line edit only.
- **Edit of non-latest lines**: Claude proposed simple confirmation dialog. User specified: allow editing but let user choose how many subsequent lines to keep (1 ≤ n ≤ y-x). This feature (selectable retention count) is deferred to a follow-up plan (Idea B); current plan implements warning-only truncation.

### Convergence Status

- Final Status: `converged`

All REQUIRED_CHANGES accepted. All user decisions obtained. Plan is ready for implementation.

## Pending User Decisions

- DEC-1: Selectable line retention on non-latest edit
  - Claude Position: Show confirmation dialog warning about truncation, with an input to specify how many lines to retain (1 ≤ n ≤ y-x)
  - Codex Position: Block editing of non-latest lines during paused phase, or allow with warning modal
  - User Decision: Allow editing with user-specified retention count (n), defaulting to keep all lines after the edit point
  - Decision Status: Deferred to follow-up plan (Idea B: Edit Safety Net)

## Implementation Notes

### Code Style Requirements
- Implementation code and comments must NOT contain plan-specific terminology such as "AC-", "Milestone", "Step", "Phase", or similar workflow markers
- These terms are for plan documentation only, not for the resulting codebase
- Use descriptive, domain-appropriate naming in code instead

### Pre-Implementation Checklist
- Run `uv run pytest tests/ -v --tb=short` to confirm 100 passing baseline (Stage 9 state)
- Run `cd frontend_vue && pnpm run type-check && pnpm run build-only` to confirm clean baseline
- Commit any uncommitted changes before starting implementation

--- Original Design Draft Start ---

# Script Editor Foundation: Tab Persistence, Timeline Navigation, Emotion Fix

## Original Idea

修复剧本编辑器三个基础问题：
1. 审核台/时轴切换时审核台丢失编辑内容（变成空白）
2. 时轴上的台词不可点击，无法跳转到任意一句进行编辑
3. LLM生成的情绪标签（【害羞】【认真】等）没有驱动角色立绘变化——角色永远是默认表情

## Primary Direction: 编辑器基础修复

### Rationale

这三个问题是同一组件的三个断点，修复它们不需要新增架构概念——只需修管线：v-if 改 v-show、加 click handler、补 emotion 数据流。

### Approach Summary

**Fix 1 — 标签页持久化（1 行改动）:**
`ScriptPanel.vue` 第 18-19 行：`v-if`/`v-else` 改为 `v-show`。`v-if` 会在切换标签时销毁组件 DOM 和所有响应式状态（`editingText`、`userEdited`），`v-show` 只切换 CSS display。两个组件都保留在 DOM 中，编辑状态在标签切换后存活。

**Fix 2 — 时轴可点击导航（~30 行）:**
`EventTrack.vue` 的 `.line-item` 添加 `@click` handler。点击任一行：
- 在 script store 中设置 `activeEditLineId`
- 将 `ScriptPanel` 的 `activeTab` 切换为 `'review'`
- `ReviewPanel` 加载该行到编辑器
- 被选中的行高亮（`.line-item--active` CSS class）

**Fix 3 — 情绪立绘管线修复（~35 行）:**
修复 LLM 产出的情绪标签到角色立绘渲染的完整数据流。当前断点为：
- 后端 `_a2d_parse_script_line()` (core.py:787) 解析了 `【情绪】` 但用 `re.sub` 丢弃了
- `ScriptLine` / `ScriptLinePayload` 数据类缺少 `emotion` 字段
- WS `script_line` 消息不携带情绪
- 前端 `useA2DWebSocket.ts:44` 硬编码 `emotion: '正常'`
修复：在以上四层均添加 `emotion: str` 字段，前端接收后在 `script_line` handler 中调用 `gameStore.gameRoles[roleId].emotion = emotion`。下游 `GameRoleAvatar.vue`（line 95-104）已有完整的 emotion watcher → EMOTION_CONFIG_EMO 映射 → 头像 URL 管线，收到数据即可工作。

**Fix 4 — Store 级编辑状态（~20 行）:**
将 `editingText` 从 ReviewPanel 局部 `ref` 提升到 script store，改为 `editedText: Record<string, string>`（按 line id 索引）。切换标签或点击其他行时，之前的编辑内容保留在 store 中。

**受影响的文件（~7 个文件，~150 行）:**
- `ScriptPanel.vue` — `v-if` → `v-show`（1 行）
- `EventTrack.vue` — `@click` + 高亮样式（~30 行）
- `script.ts` store — `activeEditLineId` + `editedText` map（~20 行）
- `ReviewPanel.vue` — 读写 store 而非局部 ref（~15 行）
- `useA2DWebSocket.ts` — emotion 传播 + `editedText` 传递（~10 行）
- `core.py` — 保存 emotion 而非丢弃 + 放入 WS payload（~10 行）
- `script_overlay.py` — `ScriptLine`/`ScriptLinePayload` 加 `emotion` 字段（~5 行）

### Objective Evidence

- `ScriptPanel.vue:18-19` — `v-if` 根因，一行修复
- `EventTrack.vue:10-14` — `v-for` 循环已有完整行数据，仅缺 `@click`
- `core.py:787` — `re.sub(r"^【.*?】", "", text)` 丢弃情绪，保存 match group 即可
- `useA2DWebSocket.ts:44` — `emotion: '正常'` 硬编码
- `GameRoleAvatar.vue:95-104` — `targetAvatarUrl` computed 已是完整渲染管线，只缺数据
- `EMOTION_CONFIG_EMO` — 21 种情绪到头像的映射已存在且可用
- `dialogue-processor.ts:44` — LingChat 原生流程正确执行 `role.emotion = event.emotion`，A2D 可以参考

### Known Risks

- `v-show` 内存：两个组件同时挂载，ReviewPanel ~200 DOM 节点，EventTrack ~100/20 行，总额外 <1MB
- Emotion 字段需前后端同步修改：6 个文件同时加字段，遗漏一处则 WS schema 校验失败（Pydantic + TypeScript interface）
- `activeTab` 需从 ScriptPanel 本地 ref 提升为可控状态：EventTrack click → 程序化切标签

### Confidence

**high** — 三个 bug 都是精确的一行根因，修复面小且无架构变更。所有扩展点（emotion 管线、WS 消息模式、store 字段）均遵循已有 pattern。

--- Original Design Draft End ---

---

## BitLesson Selection (REQUIRED FOR EACH TASK)

Before executing each task or sub-task, you MUST:

1. Read @/d/aaa-new/setups/a2d-studio/ref/LingChat/.humanize/bitlesson.md
2. Run `bitlesson-selector` for each task/sub-task to select relevant lesson IDs
3. Follow the selected lesson IDs (or `NONE`) during implementation

Include a `## BitLesson Delta` section in your summary with:
- Action: none|add|update
- Lesson ID(s): NONE or comma-separated IDs
- Notes: what changed and why (required if action is add or update)

Reference: @/d/aaa-new/setups/a2d-studio/ref/LingChat/.humanize/bitlesson.md

---

## Goal Tracker Rules

Throughout your work, you MUST maintain the Goal Tracker:

1. **Before starting a round**: Re-anchor on the original plan and current round contract
2. **Before starting a task**: Mark the relevant mainline task as "in_progress" in Active Tasks
   - Confirm Tag/Owner routing is correct before execution
3. **Active Tasks** are MAINLINE tasks only - side issues do not belong there
4. **Blocking Side Issues** are reserved for issues that truly stop mainline progress
5. **Queued Side Issues** are non-blocking and must not take over the round
6. **After completing a mainline task**: Move it to "Completed and Verified" with evidence (but mark as "pending verification")
7. **If you discover the plan has errors**:
   - Do NOT silently change direction
   - Add entry to "Plan Evolution Log" with justification
   - Explain how the change still serves the Ultimate Goal
8. **If you need to defer a task**:
   - Move it to "Explicitly Deferred" section
   - Provide strong justification
   - Explain impact on Acceptance Criteria
9. **If you discover new issues**:
   - Add to "Blocking Side Issues" only if mainline progress is blocked
   - Otherwise add to "Queued Side Issues" or keep them as `[queued]` tasks/backlog

---

Note: You MUST NOT try to exit `start-rlcr-loop` loop by lying or edit loop state file or try to execute `cancel-rlcr-loop`

After completing the work, please:
0. If you have access to the `code-simplifier` agent, use it to review and optimize the code you just wrote
1. Finalize @/d/aaa-new/setups/a2d-studio/ref/LingChat/.humanize/rlcr/2026-06-17_22-39-35/goal-tracker.md (this is Round 0, so you are initializing it - see "Goal Tracker Setup" above)
2. Write your round contract into @/d/aaa-new/setups/a2d-studio/ref/LingChat/.humanize/rlcr/2026-06-17_22-39-35/round-0-contract.md
3. Commit your changes with a descriptive commit message
4. Write your work summary into @/d/aaa-new/setups/a2d-studio/ref/LingChat/.humanize/rlcr/2026-06-17_22-39-35/round-0-summary.md
