# Ask Codex Input

## Question

You are doing a first-pass plan review for A2D Studio, a CP dialogue script editor built on LingChat (Python/Vue).

Repository: D:/aaa-new/setups/a2d-studio/ref/LingChat
- Python backend: ling_chat/core/ai_service/core.py (LLM generation, prompt construction, TTS)
- WS handler: ling_chat/core/a2d_message_handler.py (a2d.start/continue/retry/regenerate_tts)
- WS schemas: ling_chat/schemas/script_overlay.py (ScriptLine, ScriptLinePayload)
- Session: ling_chat/core/session_runtime.py (script_lines, generation_epoch)
- Frontend store: frontend_vue/src/stores/modules/script.ts (Pinia: lines[], currentLine, phase)
- ScriptPanel: frontend_vue/src/components/game/ScriptPanel.vue (v-if/v-else tabs)
- EventTrack: frontend_vue/src/components/game/EventTrack.vue (read-only line list)
- ReviewPanel: frontend_vue/src/components/game/ReviewPanel.vue (text editing, regenerate TTS)
- WS composable: frontend_vue/src/composables/useA2DWebSocket.ts (WS singleton, audio playback)
- Character avatar: frontend_vue/src/components/game/standard/GameRoleAvatar.vue (emotion watcher → EMOTION_CONFIG_EMO)
- Emotion config: frontend_vue/src/controllers/emotion/config.ts (21 emotion mappings)
- LLM config: ling_chat/configs/llm_config.py (translator section with separate provider)
- Translator: ling_chat/core/ai_service/translator.py (translate_ai_response)

DRAFT CONTENT:
# Script Editor Foundation: Tab Persistence, Timeline Navigation, Emotion Fix

## Original Idea
修复剧本编辑器三个基础问题：
1. 审核台/时轴切换时审核台丢失编辑内容（变成空白）
2. 时轴上的台词不可点击，无法跳转到任意一句进行编辑
3. LLM生成的情绪标签（【害羞】【认真】等）没有驱动角色立绘变化

## Primary Direction: 编辑器基础修复

Fix 1 — Tab persistence: ScriptPanel.vue line 18-19 v-if/v-else → v-show (1 line change)
Fix 2 — Clickable EventTrack: add @click handler on .line-item, set activeEditLineId in store,
 switch activeTab to review programmatically (~30 lines)
Fix 3 — Emotion pipeline fix: add emotion field to ScriptLine, ScriptLinePayload, WS message,
 and frontend handler. Backend: save emotion from _a2d_parse_script_line instead of discarding.
 Frontend: gameStore.gameRoles[roleId].emotion = emotion in script_line handler (~35 lines)
Fix 4 — Store-level editing state: move editingText from ReviewPanel local ref to script store
 as editedText: Record<string, string> (~20 lines)

Files affected: ~7 files, ~150 LOC

Critique the assumptions, identify missing requirements, propose stronger plan directions.

Output format:
CORE_RISKS: ...
MISSING_REQUIREMENTS: ...
TECHNICAL_GAPS: ...
ALTERNATIVE_DIRECTIONS: ...
QUESTIONS_FOR_USER: ...
CANDIDATE_CRITERIA: ...

## Configuration

- Model: gpt-5.5
- Effort: high
- Timeout: 3600s
- Timestamp: 2026-06-17_22-09-33
- Tool: codex
