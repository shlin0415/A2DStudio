Now I have everything I need. Let me write the review.

---

## Plan Review

### AGREE

**AC diagnoses 1-5 are all verified correct against the codebase.** The bugs and gaps exist exactly as described.

- **Edit Protocol broken**: `handle_continue` (session_runtime.py:62) signature is `edits: dict | None`, guard is `if edits and "modified_lines" in edits:`. Frontend sends `[{id, text}]` (ReviewPanel.vue:77, useA2DWebSocket.ts:88). Python `in` on a list checks membership, so `"modified_lines" in [{id:..., text:...}]` is always `False`. `_apply_edits` is dead code. Verified.
- **Tab Persistence**: ScriptPanel.vue uses `<ReviewPanel v-if="activeTab === 'review'" />` / `<EventTrack v-else />`. Component state destroyed on switch. Verified.
- **Emotion pipeline gaps**: `_a2d_parse_script_line` strips with `re.sub(r"^【.*?】", "", text)` — no capture group (core.py:787). ScriptLine dataclass has no `emotion` field (script_overlay.py:33). ScriptLinePayload has no `emotion` (script_overlay.py:119). WS dict in `a2d_generate_next` omits emotion (core.py:547-554). `script_line` handler in useA2DWebSocket.ts never touches gameStore emotion. Verified.
- **Missing emotions**: System prompt (core.py:611) tells LLM to output "无语" and "尴尬" as valid emotions. Neither exists in `EMOTION_CONFIG_EMO` (config.ts:19). "无语" audio is used by AI思考 entry; "尴尬" audio is used by 紧张 entry. Confirmed gap.
- **EventTrack**: No `@click` on `.line-item`, `cursor: default`, no auto-scroll. Verified.

**Task dependency graph is sound.** The dependency chain T1→T2, T4→T5→T6, T4+T5→T7, T8→T9, T9+T10→T11, T1+T2→T12 is correct.

**KeepAlive is the right call.** Vue `<KeepAlive>` with `v-if/v-else` is idiomatic and avoids the lifecycle destruction. `v-show` would keep both components mounted simultaneously, wasting resources.

---

### DISAGREE

**1. M4 targets the wrong file for the WS payload fix.**

The plan says: `a2d_message_handler.py (include emotion in WS payload)`.

The `script_line` WS payload is built as a plain dict in `core.py`'s `a2d_generate_next` (line 547-554), not in `a2d_message_handler.py`. The handler's `_handle_continue` and `_generate_and_synthesize` just pass through the result. The actual fix location is:
- `core.py:787` — extract emotion before stripping
- `core.py:547-554` — add `emotion` to the WS dict

The message handler doesn't need modification for emotion.

**2. M1 LOC estimate is too low.**

The plan says "~15 LOC." The actual fix requires:
- Change `handle_continue` signature from `dict | None` to `list[dict] | None` (1 LOC)
- Replace the guard from `if edits and "modified_lines" in edits:` to `if edits:` (1 LOC)
- Rewrite `_apply_edits` to accept `{id, text}` format: look up speaker from original line by ID, use `text` as `display_text`, set `tts_text = text`, handle missing line ID gracefully (15-20 LOC)
- New unit test for the fix (15+ LOC)

More like 30-40 LOC total.

**3. M5 `handleContinue` sends only one edit, not the accumulated map.**

Current `handleContinue` in ReviewPanel.vue:77:
```js
const edits = editingText.value !== store.currentLine.display_text
  ? [{ id: store.currentLine.id, text: editingText.value }]
  : []
```

This sends only the current line's edit. If M5 introduces an `editedText` map to preserve per-line edits across navigation, `handleContinue` must collect ALL dirty entries from the map and send them. The plan doesn't mention this change. Either `handleContinue` needs updating, or the `sendContinue` function needs to pull from the store.

---

### REQUIRED_CHANGES

**RC-1: Fix M4 target file.** Change `a2d_message_handler.py` to `ling_chat/core/ai_service/core.py` in the M4 milestone description. The handler is a pass-through; the payload is built in `a2d_generate_next`.

**RC-2: Define the `editedText` → `sendContinue` data flow for M5.** The plan must specify:
- Does `handleContinue` iterate the `editedText` map and send all dirty entries?
- Or does it only send the current line's edit (making M5 purely cosmetic)?
- What happens if the user edits line 2 (non-latest) and clicks continue? The current `_apply_edits` truncates everything after the first modified line — this is a destructive fork. The plan's AC-5 negative case ("click continue → edits committed, map entries cleared") doesn't address this.

**RC-3: Specify the speaker→roleId mapping strategy for M4.** When `script_line` arrives, the frontend must map `speaker` (e.g., "ema") to a `roleId`. Options:
- Store `script_role_key` on `GameRole` (the backend already sends it in the `a2d.characters` payload but the frontend discards it)
- Build a `speakerToRoleId: Record<string, number>` map in the script store or composable
- The `a2d.characters` handler in useA2DWebSocket.ts has access to both `c.script_role_key` and `c.roleId` — building the map there is cleanest.

**RC-4: Update `ScriptLinePayload` dataclass AND the plain dict in `a2d_generate_next`.** The plan mentions ScriptLinePayload but the actual WS dict is a plain `dict` literal at core.py:547. Both need the `emotion` field. The frontend `ScriptLine` interface in script.ts:6 also needs `emotion?: string`.

**RC-5: `_apply_edits` field mapping.** The plan says "read 'text' field" but doesn't specify the mapping:
- `speaker` → look up from `self.script_lines` by `id`, fallback to `"ema"` if not found
- `display_text` → the `text` field from the edit
- `tts_text` → same as `text` (the user editing display text implies TTS should match; no separate TTS editing in the UI)
- `id` → preserve the original line's ID if replacing, or generate a new one if forking

The current `_apply_edits` generates new ScriptLine instances (new UUIDs), which means edited lines lose their original IDs. If EventTrack uses line IDs for navigation (AC-4), this matters.

---

### OPTIONAL_IMPROVEMENTS

**OI-1: Add 无语 and 尴尬 to `EMOTION_CONFIG_EMO`.** The system prompt explicitly teaches the LLM these emotions (core.py:611). Without entries, `targetAvatarUrl` in GameRoleAvatar.vue falls through to `EMOTION_CONFIG_EMO[emotion] || '正常'` — the character silently reverts to 正常. Adding the two missing keys with aliases to existing emotions (无语→无奈, 尴尬→紧张 or similar) is ~2 LOC and prevents a confusing silent fallback. Not blocking because the fallback is non-crashing.

**OI-2: `_a2d_build_messages` discards emotion context.** The history reconstruction at core.py:703 uses `【】` (empty emotion tag):
```python
f"【】{line.display_text}"
```
This means the LLM has no emotion context from previous turns. If emotion continuity matters (e.g., the LLM should know the character was just 害羞), this line should include the captured emotion: `【害羞】{line.display_text}`. Not blocking M4, but affects generation quality.

**OI-3: Auto-scroll in EventTrack (T6) is low risk but important for UX.** The implementation is straightforward — watch `store.lines.length`, `nextTick`, `scrollTo({ top: el.scrollHeight })`. Mentioning only because it's easy to forget during implementation.

**OI-4: Consider making `KeepAlive` selective.** `KeepAlive` caches component instances including their reactive state. If the user switches between tabs many times, stale `ReviewPanel` state could cause subtle bugs. Adding an `onActivated` hook that re-syncs `editingText` from `store.currentLine` would be defensive.

---

### UNRESOLVED

**U-1: Edit-scope semantics for non-latest line edits.** The current `_apply_edits` truncates all lines after the first modified line (a "dialogue fork"). If the user navigates to line 2 of 5, edits it, and clicks continue, lines 3-5 are discarded. The plan mentions this as an "additional gap" but doesn't specify the desired behavior:
- (a) Fork as-is (current design, destructive, no warning)
- (b) Block editing of non-latest lines during paused phase
- (c) Allow editing but show a warning modal listing lines that will be discarded

This is a product decision that affects both M3 and M5 implementation.

**U-2: Multi-edit accumulation scope.** If the user edits line 2, navigates to line 4, edits it, then clicks continue — should both edits be sent? If yes, `_apply_edits` receives edits at different indices. The current logic truncates from the minimum index and appends all edits sequentially. This means line 3 (between the two edits) is discarded and the edited line 4 gets re-indexed. Is this the intended behavior, or should only the current/last-edited line be sent?

**U-3: `editedText` map lifecycle.** When should the map be cleared?
- On "continue" click (as the plan's AC-5 negative case implies)
- On new line arrival (since the map is about user-initiated edits, not LLM-generated content)
- On session reset

The plan says "Click continue → edits committed, map entries cleared" which answers this partially, but doesn't address what happens if the user edits line 3, a new line 4 arrives from the LLM, and then the user navigates back to line 3. Should the edit persist?
