I've now read all the key files. Here is the plan review.

---

## CORE_RISKS

**R1 — Edit protocol is broken (existing bug, not mentioned in draft).** Frontend `sendContinue` sends `{ generation_id, edits: [{id, text}] }`. Backend `handle_continue` checks `edits["modified_lines"]` — a dict key that never exists in the frontend payload. The `edits` parameter is always silently ignored. The draft's Fix 4 (store-level editing state) doesn't address this. Any "edit a line then continue" workflow will lose the edits. This must be fixed before or alongside Fix 2, otherwise clicking an old line and editing it has no effect.

**R2 — Emotion is parsed then discarded (the draft's core Fix 3 claim is correct but incomplete).** `_a2d_parse_script_line` in [core.py](/D:/aaa-new/setups/a2d-studio/ref/LingChat/ling_chat/core/ai_service/core.py:731) does `re.sub(r"^\【.*?】", "", text)` to strip the emotion tag from `display_text`, but never captures the match or assigns it to the ScriptLine dataclass. The draft correctly identifies this. However, the draft doesn't mention that the regex is also too greedy — if the LLM outputs `【害羞】你好<TTS><动作>`, the regex works fine, but edge cases like `【害羞】【认真】text` would lose the first tag. More importantly, the frontend's `gameStore.gameRoles[roleId].emotion` assignment requires knowing which `roleId` maps to which `speaker` — the `script_line` handler needs a speaker-to-roleId mapping that doesn't currently exist in the WS message.

**R3 — Fix 2 (clickable EventTrack) is incomplete without Fix 4 dependency.** The draft proposes them as independent fixes, but clicking an EventTrack line to edit it requires ReviewPanel to be able to display arbitrary lines, not just `currentLine`. The existing `watch(() => store.currentLine, ...)` in ReviewPanel only reacts to `currentLine` updates. If you add `activeEditLineId` to the store but don't rewrite ReviewPanel's watcher and binding, the textarea will still only show `currentLine`.

**R4 — `v-show` alone doesn't solve tab persistence correctly.** The draft says "1 line change" for v-if/v-else to v-show. This keeps ReviewPanel mounted, preserving the local `editingText` ref. But the watch on `store.currentLine` will still fire when a new line arrives (from a `sendContinue` you triggered from the EventTrack tab), potentially overwriting the user's in-progress edit. The `userEdited` guard partially protects this, but the interaction between tab switching and new-line generation is under-designed.

---

## MISSING_REQUIREMENTS

**M1 — Invalidated-line UX.** After a user edits line N and clicks continue, the backend truncates lines N+1 onward. The frontend `lines[]` array still shows the old lines until the new ones arrive. There's no "invalidated" visual state in EventTrack, no spinner, no indication that those lines are being regenerated. For a script editor, this is a core UX gap.

**M2 — Edit scope: what can be edited?** The draft assumes users can edit any old line. But the backend `_apply_edits` truncates all lines after the first modified one. If a user edits line 3 of 10, lines 4-10 are discarded and regenerated. This is correct behavior for a script editor, but the UI must communicate this consequence to the user before they click "continue." The draft doesn't address this disclosure.

**M3 — Multi-line editing workflow.** The draft's Fix 4 moves `editingText` to a store-level `Record<string, string>`, but `sendContinue` only sends edits for one line. There's no batch-edit flow. If a user wants to edit lines 5 and 7 before continuing, the current design can't express this. Not critical for MVP, but the store design should be future-compatible.

**M4 — No auto-scroll on new line.** EventTrack has `max-height: 200px; overflow-y: auto` but no scroll-to-bottom behavior when new lines arrive. Users will need to manually scroll to see the latest line.

---

## TECHNICAL_GAPS

**T1 — Speaker-to-roleId mapping absent from `script_line` WS message.** The `ScriptLinePayload` has `speaker` ("ema"/"hiro") and the character init message `a2d.characters` has `roleId` + `script_role_key`. To set `gameStore.gameRoles[roleId].emotion = emotion` on the frontend, the `script_line` handler needs to look up `roleId` from `script_role_key`. This lookup table exists in the composable (`a2d.characters` handler) but isn't stored anywhere reusable. The draft's Fix 3 mentions this assignment but doesn't describe how to resolve the mapping.

**T2 — `ScriptLine` backend dataclass has no `emotion` field.** Adding `emotion: Optional[str] = None` to the dataclass in [script_overlay.py](/D:/aaa-new/setups/a2d-studio/ref/LingChat/ling_chat/schemas/script_overlay.py:51) is trivial, but the draft doesn't mention it also needs to be added to `ScriptLinePayload` (the WS message schema) — the draft does mention this, good. But it also needs to be serialized in `_generate_and_synthesize` where the result dict is built from `a2d_generate_next`.

**T3 — `handle_continue` edit format requires coordinated frontend+backend change.** The backend expects `{ modified_lines: [...] }` but the frontend sends `[{id, text}]`. Both sides need to agree on a format. The simplest fix is to update the backend to match the frontend's current format, but this also requires `handle_continue` to look up the speaker for each edited line from `script_lines`.

**T4 — Emotion type mismatch risk.** The LLM is prompted with Chinese emotion tags (害羞, 认真, etc.). The frontend `EMOTION_CONFIG_EMO` maps Chinese strings to Chinese strings (identity mapping). The `EMOTION_CONFIG` keys are also Chinese. This works, but if the LLM outputs a variant like `害羞性` or an English tag, the mapping silently falls through to the default avatar. No validation or fallback is mentioned in the draft.

**T5 — `_a2d_parse_script_line` doesn't handle the speaker marker in the raw text.** The `a2d_generate_next` method strips `{"speaker":"ema"}` markers before passing lines to `_a2d_parse_script_line`. But if the LLM embeds a speaker marker inline (e.g., `{"speaker":"ema"}\n【害羞】text`), only the first marker is consumed. Subsequent lines in the same LLM response would still use `current_speaker`. This is a pre-existing issue but worth noting since emotion tags sit adjacent to these markers.

---

## ALTERNATIVE_DIRECTIONS

**A1 — Fix the edit protocol mismatch FIRST, before adding store-level editing state.** The draft sequences fixes as independent tracks. But Fix 4 (store editing state) is worthless without T1/T3 (protocol fix). Recommend fixing the backend `handle_continue` to accept `[{id, text}]` and doing the speaker lookup internally. This unblocks the entire edit workflow with ~15 lines of backend change, before touching the frontend store.

**A2 — Instead of `v-show`, use `keep-alive` + `v-if`.** Vue's `<keep-alive>` is the idiomatic way to preserve component state across conditional rendering. It handles the watcher lifecycle more cleanly than `v-show` (which keeps both components in the DOM and running watchers). `v-show` will cause EventTrack watchers (if any are added) to fire even when hidden.

**A3 — Consider adding emotion to the `a2d.characters` init message as a "default emotion" field.** This way the frontend can initialize each role's emotion to the character's default rather than the hardcoded `'正常'`. Not strictly necessary for Fix 3, but it makes the emotion system more robust.

**A4 — For EventTrack click → ReviewPanel edit, consider a dedicated `editTargetLineId` in the store rather than reusing `currentLine`.** `currentLine` semantically means "the latest generated line." Overloading it with "the line the user wants to edit" creates confusion. A separate `editTargetLineId: string | null` that, when set, overrides which line ReviewPanel displays, is cleaner and doesn't break the existing `currentLine` semantics for the thinking/synthesizing/paused state machine.

---

## QUESTIONS_FOR_USER

**Q1 — When a user edits an old line and clicks "continue," should the UI show a confirmation dialog warning that subsequent lines will be discarded?** Or is the script-editor audience expected to understand this behavior?

**Q2 — Should EventTrack lines be reorderable or deletable, or is the edit-truncate-continue workflow the only expected modification path?** This affects whether Fix 2 should include drag handles or a delete button.

**Q3 — Is the emotion tag expected to always be present in LLM output, or can it be absent?** The current prompt instructs the LLM to include it, but the parser handles the no-emotion case by stripping an empty match. If emotion is optional, the frontend needs a fallback behavior (keep previous emotion vs. reset to default).

**Q4 — What should happen to the `editedText` record when `store.reset()` is called (i.e., starting a new session)?** The draft's Fix 4 proposes `editedText: Record<string, string>` but doesn't mention clearing it on reset.

---

## CANDIDATE_CRITERIA

For choosing the strongest plan direction, prioritize:

1. **Fix the broken edit protocol first.** The existing `handle_continue` silently drops all edits. Any other fix built on top of the edit workflow is dead until this is resolved.
2. **Emotion pipeline fix should be a single end-to-end vertical slice.** Backend parse → WS payload → frontend store → avatar assignment. Don't ship the backend parse without the frontend consumption, or vice versa.
3. **Tab persistence fix should use `keep-alive` rather than `v-show`** for cleaner Vue semantics and easier future extension.
4. **EventTrack click → ReviewPanel edit should use a dedicated store field (`editTargetLineId`)**, not overload `currentLine`, to avoid breaking the existing state machine.
5. **LOC estimate is low.** The draft says ~150 LOC / ~7 files. Realistic count including the protocol fix, emotion end-to-end, keep-alive, store changes, EventTrack click handler, and ReviewPanel watcher rewrite: ~200-250 LOC / ~8 files. The draft underestimates the ReviewPanel changes required to support arbitrary-line editing.
