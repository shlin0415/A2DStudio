Good, I now have full context on all the relevant code paths. Here's my review.

---

## CORE_RISKS

1. **Translation latency in TTS path (Fix 1+3)**: Adding an LLM translation call inside `a2d_synthesize` or `regenerate_tts` makes the TTS pipeline depend on a second LLM round-trip. If the translator LLM is slow or unavailable, TTS generation stalls or fails entirely. The existing `translator.py` uses its own `LLMManager(llm_job="translator")` with separate provider config, so timeout/retry behavior is independent of the main LLM -- but it's still a new synchronous dependency in a user-facing action.

2. **GSV model state corruption is a one-way door**: BUG 1's description says Chinese text sent with `text_lang="ja"` corrupts GSV model state and degrades subsequent Japanese TTS. If true, even a single occurrence before the fix ships poisons the session. The fix must also include a way to detect or recover from a corrupted GSV state (e.g., re-setting the GSV model weights after a language mismatch is detected), or you need to guard against this happening even once.

3. **`_a2d_build_messages` history format change (Fix 2) affects LLM behavior globally**: Adding `<TTS>` tags to history for *all* lines with non-empty `tts_text` changes the distribution of examples the LLM sees. For same-language characters where `<TTS>` is optional, this could cause the LLM to always emit `<TTS>` tags (redundant but not harmful). More importantly, if the tag content ever diverges from `display_text` in unexpected ways, it could confuse the LLM. Needs a targeted test.

4. **`_apply_edits` setting `tts_text=""` creates a persistent empty field**: After the fix, edited lines in `script_lines` will have `tts_text=""` permanently. Any code that later reads `tts_text` from these lines (not just `_a2d_build_messages`) must handle the empty case. Currently `a2d_synthesize` is called with explicit `text` arguments so it doesn't read from ScriptLine directly, but this is fragile if the contract changes.

---

## AGREE

- **BUG 1 diagnosis is correct.** Confirmed in code: `a2d_synthesize` at [core.py:817](ling_chat/core/ai_service/core.py:817) passes `text` directly to `gsv_adapter.generate_voice(text)`. The adapter's `text_lang` is set at construction (default `"ja"` per [gsv_adapter.py:18](ling_chat/core/TTS/gsv_adapter.py:18)). Chinese text + `text_lang="ja"` = garbled output. No translation step exists in this path.

- **BUG 2 diagnosis is correct.** `_a2d_build_messages` at [core.py:700](ling_chat/core/ai_service/core.py:700) constructs history as `【{emotion}】{display_text}` with no `<TTS>` tag. After `_apply_edits` creates lines where `tts_text == display_text` (Chinese), the LLM sees history without its expected output format, causing format drift including multi-speaker regression.

- **BUG 3 diagnosis is correct.** `_apply_edits` at [session_runtime.py:86](ling_chat/core/session_runtime.py:86) sets `tts_text=line_data.get("text", "")` -- identical to `display_text`. Chinese display text with action descriptions becomes the TTS text, producing garbled speech.

- **BUG 4 diagnosis is correct.** `currentSpeakerName` in [ReviewPanel.vue:79](frontend_vue/src/components/game/ReviewPanel.vue:79) reads `store.lines[store.lines.length - 1]` which is the *previous* speaker, not the next one. Before any lines exist, it returns empty string.

- **Fix 4 (generic "思考中...") is the right call.** The thinking indicator appears *before* the LLM decides who speaks next, so attributing it to any specific character is always potentially wrong. Generic is correct.

- **Fix 2 (include `<TTS>` in history) is directionally correct.** The LLM needs to see its own output format in history to maintain format consistency.

---

## DISAGREE

**1. "Fix 1+3: add translation step in `a2d_synthesize`" -- the translation should NOT live inside `a2d_synthesize`.**

`a2d_synthesize` is a TTS-only function. Mixing translation (an LLM call) into it violates single responsibility and makes the function's latency unpredictable. The translation should happen *before* `a2d_synthesize` is called, in the two call sites that need it:

- `_handle_regenerate_tts` in [a2d_message_handler.py:99](ling_chat/core/a2d_message_handler.py:99): translate `text` before calling `a2d_synthesize`
- `_generate_and_synthesize` in [a2d_message_handler.py:66](ling_chat/core/a2d_message_handler.py:66): if `tts_text` is empty, translate `display_text` before calling `a2d_synthesize`

This keeps `a2d_synthesize` pure (text in, audio out) and makes translation failures easier to handle (show error to user, skip TTS, etc.).

**2. "Estimated ~40 LOC across 4 files" is optimistic.**

The translation integration alone requires: (a) a translation helper that works with A2D's single-text format (the existing `translator.py` `translate_ai_response` expects a list of segment dicts, not a plain string), (b) error handling for translation failure, (c) async coordination. Realistically this is 60-80 LOC, and that's before tests.

**3. Setting `tts_text=""` alone is insufficient as a signal for "needs translation."**

An empty string is ambiguous -- it could mean "needs translation" or "user deleted all text." Use `tts_text=""` as a trigger, but also add a guard: if `display_text` is non-empty and `voice_language != display_language` for that speaker, then translate. Don't rely solely on the empty-string signal.

---

## REQUIRED_CHANGES

1. **Translation must happen before `a2d_synthesize`, not inside it.** Create a small async helper (e.g., `_a2d_translate_for_tts(text, target_lang)`) that uses `LLMManager(llm_job="translator")` with a simple prompt. Call it from `_handle_regenerate_tts` and `_generate_and_synthesize`. Keep `a2d_synthesize` as a pure TTS function.

2. **`_handle_regenerate_tts` must also update the ScriptLine.** Currently at [a2d_message_handler.py:103](ling_chat/core/a2d_message_handler.py:103), the handler looks up the speaker but never updates `line.display_text` or `line.tts_text`. After the user edits text and regenerates TTS, the ScriptLine is stale. Fix: update the matching line's `display_text` and `tts_text` (after translation) in `script_lines`.

3. **`_a2d_build_messages` must handle empty `tts_text` gracefully.** When `tts_text` is empty (edited lines), the history message should use just `display_text` without a `<TTS>` tag -- same as current behavior. Only include `<TTS>` when `tts_text` is non-empty AND differs from `display_text`. Otherwise you'll inject empty tags like `<>` into history.

4. **Translation failure must be non-fatal with a clear fallback.** If the translator LLM fails, log a warning and either (a) skip TTS entirely (send `tts_ready` with no audio, let frontend show a warning), or (b) send `display_text` as-is to TTS with correct `text_lang`. Option (a) is safer given the GSV corruption risk. Do NOT send Chinese text to GSV with `text_lang="ja"` under any circumstances.

5. **Frontend `currentSpeakerName` fix needs to cover the "has lines but thinking" case too.** The current fix plan says "generic 思考中..." but ReviewPanel.vue has two thinking branches: one with `store.currentLine` (line 5-8) that shows `currentSpeakerName`, and one without (line 12-14). Both need the fix. Replace `{{ currentSpeakerName }}正在思考..` with just `正在思考..` in both places.

---

## OPTIONAL_IMPROVEMENTS

1. **Cache translations per line ID.** If the user clicks "重生成语音" multiple times on the same line, don't re-translate. Store the translated text on the ScriptLine's `tts_text` field after first translation.

2. **Add a `needs_translation` flag to ScriptLine.** Instead of overloading empty `tts_text`, add an explicit boolean. This makes intent clearer and avoids ambiguity with genuinely empty text. However, this changes the schema and touches more files, so it's a judgment call on whether the LOC trade-off is worth it for this stage.

3. **Consider `text_lang` override in GSV adapter.** Add an optional `text_lang` parameter to `generate_voice(text, text_lang=None)` that overrides the instance default. This lets `a2d_synthesize` pass the correct language per-call without re-creating the adapter. Defense in depth even if translation is the primary fix.

4. **Test the format drift regression with a replay test.** Create a test that: generates a line (LLM output with `<TTS>`), applies an edit (simulating `_apply_edits`), builds messages via `_a2d_build_messages`, and asserts the history contains the `<TTS>` tag. This prevents BUG 2 from regressing again.

5. **The `thinking_message` from character settings is already available.** In `_send_a2d_characters` at [a2d_message_handler.py:51](ling_chat/core/a2d_message_handler.py:51), each character has a `thinkMessage` field sent to the frontend. The frontend could use the *next* speaker's `thinkMessage` instead of computing `currentSpeakerName`. But since the next speaker is unknown during thinking, generic is still the safest default.
