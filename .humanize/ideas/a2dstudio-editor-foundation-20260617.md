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
