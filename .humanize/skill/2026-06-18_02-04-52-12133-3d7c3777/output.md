I've read all three files. Here's the grounded review.

---

**CORE_RISKS**

**1. Silent line loss (existing bug, severity: high).**
`a2d_generate_next` parses all lines from LLM output and adds them all to `session.script_lines` via `session.add_line(line)` in the loop, but only returns `lines[0]`. If the LLM ever outputs N>1 lines today, lines 2..N are added to history (affecting future message construction) but never sent to the frontend for display or TTS. They become phantom history lines. If batch_size stays 1 and the prompt enforces single-line output, this is dormant. The moment you relax the prompt, it becomes the primary bug.

**2. Sync `_a2d_translate_for_tts` called from async `_generate_and_synthesize`.**
The recent `async def -> def` fix is correct — `translator.process_message` is synchronous. But if you move to multi-line generation, each translated line blocks the event loop for the full LLM translation round-trip. For a batch of 3 lines needing translation, that's 3 serial blocking calls. Consider `asyncio.to_thread` or batching translations.

**3. Prompt token cost scales with batch relaxation.**
The system prompt currently says "每次只生成一句对话" (one line only). Removing this constraint means the LLM may output variable-length responses, making token budget less predictable. `BudgetStatus` exists in `SessionRuntime` but is never checked during generation.

---

**RECOMMENDED_ORDER**

1. **Fix `a2d_generate_next` to return all lines.** Change the return from `lines[0]` to a list. `_generate_and_synthesize` should loop over the returned list, sending each `script_line` + TTS pair sequentially. This is the structural prerequisite — nothing else works cleanly without it.

2. **Prompt wording driven by batch_size.** In `_a2d_build_system_prompt`, replace the hardcoded "每次只生成一句对话" with something like:
   ```
   if batch_size == 1:
       "每次只生成一句对话"
   else:
       f"每次生成1到{batch_size}句对话"
   ```
   Keep it a soft hint, not a hard instruction. The actual N is always `len(lines)` from parsed output.

3. **Loop in `_generate_and_synthesize`.** The current function handles one result. Refactor to accept a list:
   ```python
   results = await ai_service.a2d_generate_next(...)
   for result in results:
       await send(result)
       # translate + synthesize TTS per line
   ```
   Each line gets its own `status(synthesizing)` -> `tts_ready` -> sequence, so the frontend sees them arrive incrementally.

4. **Test with batch_size=1 first.** After the refactor, verify single-line behavior is byte-identical before testing batch_size=2+. This catches regressions in the return-shape change.

---

**DESIGN_FEEDBACK**

- **batch_size should stay a prompt hint, not a pipeline cap.** Your instinct (item 3: "N should be len(lines)") is right. Don't add a hard `lines[:batch_size]` slice. The LLM decides the natural break point; batch_size just tells it how much it's allowed to produce. If the LLM returns 1 line when batch_size=3, that's fine.

- **Consider emitting a single `batch_start`/`batch_end` envelope.** Right now each line is a standalone `script_line` WS message. For multi-line batches, the frontend needs to know "these N lines belong to one generation." A lightweight wrapper avoids ambiguity about when to re-enable the continue button. For example: `{type: "batch_start", payload: {count: N}}` before the loop, `{type: "batch_end"}` after.

- **The current `_a2d_build_messages` history format includes speaker markers** (`{"speaker":"ema"}`) only in assistant messages. When multiple lines are generated in one turn, they appear as consecutive assistant messages with the same speaker marker pattern. This should work, but verify the LLM doesn't interpret consecutive same-speaker assistant messages as a signal to keep using that speaker.

- **`session.add_line` sets index and epoch inside the method.** If you generate N lines in one call, they'll get sequential indices (correct) and the same epoch (correct). No change needed here.

---

**ANYTHING_MISSED**

- The `handle_continue` path calls `_apply_edits` then `_generate_and_synthesize`. With multi-line generation, if the user edits line 5 of a batch and hits continue, `_apply_edits` truncates from that index. Lines 6..N from the original batch are discarded. This is correct behavior, but worth confirming with a test.

- `_a2d_call_llm_with_retry` retries the full LLM call on failure. If the LLM returns partial output (e.g., 2 of 3 lines before a timeout), all lines are lost. This is acceptable for now but worth noting for later — partial-result recovery would add significant complexity.

- The `invalidate_downstream` method exists in `SessionRuntime` but is never called from any handler. It's dead code. Not urgent, but if you build undo/revert later, it's the intended mechanism.

- `a2d.start` hardcodes `session.batch_size = 1`. This should eventually read from frontend config or environment, but for round 1, hardcoding is fine since you'll test with 1 first.
