# A2D Studio MVP 计划 — Stage 14 之后

> 2026-06-22 | 与 Codex 讨论后定稿

## 当前状态

Stage 12-14 完成了核心管线：

| 已完成 | 说明 |
|--------|------|
| LLM 对话生成 | 迭代 batch_size，流式 LLM→TTS，格式稳定 |
| TTS 语音合成 | GSV 双角色，翻译管线 |
| 前端舞台 | StageView + GameRolesStage + ReviewPanel |
| 逐句编辑 | ReviewPanel textarea + 重生成语音 |
| Audio pipeline | 单例 Audio + Muted Pre-Roll + BGM |
| 性能测试 | `tests/a2d_perf_latency.py` — Gantt + 冷启动/播放/空闲指标 |
| E2E 测试 | `test_a2d_stage_e2e_full.py` — 2 tests, ~90s |

## 十个关键决策

| # | 问题 | 决策 |
|---|------|------|
| Q1 | 脚本格式 | **自定义 JSON schema**，导出时可转换 WebGAL DSL |
| Q2 | 播放器 | **先内置预览**（StageView 播放模式），导出 WebGAL 后置 |
| Q3 | 阶段粒度 | **混合**：默认 batch=阶段，可手动合并/拆分。用 `stage_id` 扁平字段 |
| Q4 | 屏幕元素 | **MVP 最小集**：背景 + 立绘(已有) + 图片覆盖 |
| Q5 | LLM 舞台指令 | **LLM 不生成舞台指令**。由剧本家手动设置。保持 LLM 只输出对话 |
| Q6 | 手写模式 | **简单手写界面**：选 speaker + 写文本 + 选 emotion |
| Q7 | 导入导出 | **三层导出**：L1 JSON(存进度) → L2 zip(完整备份) → L3 WebGAL(分发) |
| Q8 | 重播 | **可暂停编辑**：从任意 index 开始播，只用已有音频+舞台元素 |
| Q9 | ASMR | **配置驱动**：`SceneConfig.dialogue_style` 切换，不改代码 |
| Q10 | 时间 | **3-5 天** 确定数据模型后开工 |

## MVP 优先级

```
P0 ████████████████████  数据模型设计 (ScriptLine扩展 + Stage + Overlay)
P1 ████████████████      纯前端重播模式 (任意index启动，无LLM无TTS)
P2 ████████████          L1 JSON 导出/导入 (保存/加载编辑进度)
P3 ██████████            手写模式 (新建行 + 手动选speaker/emotion)
P4 ████████              舞台元素编辑UI (背景/屏幕文字框/图片覆盖 增删改拖)
P5 ██████                L2 完整zip导出 (脚本+音频+图片)
P6 ████                  阶段管理UI (合并/拆分stage)
P7 ██                    L3 WebGAL 导出
```

## P0: 数据模型

### ScriptLine 扩展

```python
@dataclass
class ScriptLine:
    id: str
    index: int
    generation_epoch: int
    stage_id: str = ""          # NEW: 所属阶段
    speaker: str
    emotion: str
    display_text: str
    tts_text: str
    action: str
    raw_text: str
    state: str                  # draft/approved/tts_ready/played
    audio_path: str | None
    overlay: LineOverlay | None # 已有，需完善
```

### Stage

```python
@dataclass
class Stage:
    id: str
    title: str = ""
    line_ids: list[str]         # 引用 ScriptLine.id
    default_background: str = "" # 阶段默认背景
```

### LineOverlay 完善

```python
@dataclass
class TextOverlay:
    id: str
    text: str                     # 文本内容
    x: float; y: float            # 位置 (%相对画布)
    width: float = 0              # 宽度 (0=auto)
    font_size: int = 24
    color: str = "#ffffff"
    opacity: float = 1.0

@dataclass
class LineOverlay:
    background: str = ""           # 背景图路径
    sprite_positions: dict = {}    # {speaker: {x, y, scale}}
    image_overlays: list = []      # [{path, x, y, w, h, opacity}]
    text_overlays: list = []       # [TextOverlay]  ← NEW: 屏幕文字
    bgm: str = ""                  # BGM 路径
```

前端实现：可拖拽的 `<div contenteditable>` 覆盖在舞台上，剧本家直接打字、拖位置、调样式，保存到 `text_overlays` 数组。

### 导出格式 (L1 JSON)

```json
{
  "version": 1,
  "meta": { "title": "", "created": "", "characters": {} },
  "stages": [
    {
      "id": "s1", "title": "",
      "default_background": "bg_night.png",
      "lines": ["l1", "l2", "l3"]
    }
  ],
  "lines": [
    {
      "id": "l1", "stage_id": "s1", "index": 0,
      "speaker": "ema", "emotion": "害羞",
      "display_text": "...", "tts_text": "...", "action": "...",
      "audio_path": "audio/l1.wav",
      "overlay": { "background": "", "image_overlays": [] }
    }
  ]
}
```

## P1: 重播模式

核心需求：从任意 index 开始播放，不调 LLM/TTS。

实现：
1. 前端新增 `ReplayMode` 组件或 StageView 的 `mode=replay` 切换
2. 加载 JSON → 构建 ScriptLine[] → 从 index=N 开始顺序播放
3. 播放时：恢复背景/立绘/图片覆盖（从 overlay 读取），触发 audio.play()
4. 支持暂停、跳转、修改后继续

技术要点：
- 中间启动需还原舞台状态：向前扫描找到最近的 background 设置
- 音频路径可能是相对路径，需 resolve

## P2: L1 JSON 导出/导入

- 导出按钮 → 生成 JSON → 下载为 `.a2d.json`
- 导入按钮 → 选择文件 → 还原 SessionRuntime + ScriptLine[]
- 导入后可继续编辑或重播

## 不做的（明确排除）

- LLM 生成舞台指令 — 格式不稳定，编辑体验差
- 完整可视化编辑器（拖角色、设背景）— MVP 之后
- WebGAL 项目导出 — P7
- 粒子特效、视频、选择分支 — 非 MVP

## 验证标准

| 阶段 | 验证方式 |
|------|----------|
| P0 数据模型 | JSON proto 样本 + Python dataclass + TS interface 编译通过 |
| P1 重播 | 从 index=0/3/7 启动，语音+舞台状态正确 |
| P2 导出导入 | 导出 → 清空 → 导入 → 重播，结果一致 |
| P3 手写 | 新建行 → 写文本 → 出现在列表 → 可播 |
| P4 舞台元素 | 新建文字框→打字→拖位置→重播时正确显示 |

---

*与 Codex 讨论记录: `.humanize/skill/2026-06-22_21-26-27-41874-5aea9f91/output.md`*
