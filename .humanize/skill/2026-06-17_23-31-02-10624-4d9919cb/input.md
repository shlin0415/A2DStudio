# Ask Codex Input

## Question

A2D Studio Stage 10 implementation is partially complete (AC-1 through AC-5 code changes done, 103 backend tests pass, frontend builds). However, a headed Playwright interactive test + backend log analysis revealed 4 bugs:

BUG 1 [P0]: regenerate_tts sends Chinese text directly to GSV with text_lang="ja"
- User edits display_text (Chinese), clicks "重生成语音"
- Backend a2d_synthesize receives Chinese, sends to GSV as text_lang="ja"
- GSV uses Japanese phonemes on Chinese → garbled output
- Corrupts GSV model state, subsequent Japanese TTS also degraded
- Root: no translation step between user edit and TTS synthesis
- Existing infrastructure: llm_config.py has [translator] section, .env has TRANSLATE_LLM_PROVIDER, translator.py has translate_ai_response(), LLMManager accepts llm_job="translator"

BUG 2 [P0]: After user edits, LLM generates 2-3 speakers per response again
- Stage 9 fixed this by changing prompt to "每次只生成一句对话"
- But after _apply_edits creates history with edited Chinese text (no <TTS> tag), LLM format drifts
- History messages use: fspeaker:{speaker}n【{emotion}】{display_text}
- No <TTS> tag in history → LLM forgets the format → multi-speaker regression

BUG 3 [P1]: LLM generates Chinese TTS text with action descriptions after edit
- Normal: "ヒロちゃん、あの…話したいことがあるの" (clean Japanese)
- After edit: "我...我想让你陪我去一个地方。（手指不安地绞在一起）" (Chinese + actions)
- Root: _apply_edits maps user edit text to both display_text AND tts_text, then history shows no TTS separation

BUG 4 [P2]: Thinking message shows wrong/empty character name
- Before any lines: thinking shows empty name (currentLine is null)
- After line 1 (Ema): thinking shows "艾玛思考中" but next speaker is Hiro
- Root: currentSpeakerName computed uses store.lines[last-1].speaker (previous speaker), not generic "思考中..."

PROPOSED FIX PLAN:
Fix 1+3: _apply_edits sets tts_text="" instead of text; add translation step in regenerate_tts and a2d_synthesize for voice_language != display_language
Fix 2: Include <TTS> tag in _a2d_build_messages history when tts_text is non-empty
Fix 4: Change thinking message to generic "思考中..." without character name

Key files: session_runtime.py, core.py, a2d_message_handler.py, ReviewPanel.vue
Estimated: ~40 LOC across 4 files

Please review this diagnosis and fix plan. Output:
CORE_RISKS: highest-risk items
AGREE: points you agree with
DISAGREE: points you disagree with and why
REQUIRED_CHANGES: must-fix items
OPTIONAL_IMPROVEMENTS: non-blocking suggestions

## Configuration

- Model: gpt-5.5
- Effort: high
- Timeout: 3600s
- Timestamp: 2026-06-17_23-31-02
- Tool: codex
