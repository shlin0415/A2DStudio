# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 重要提示

- **全程使用中文回复和思考**

## 项目概述

LingChat 是一个 AI 对话/角色扮演应用，采用前后端分离架构：
- **后端**：Python (FastAPI + WebSocket)
- **前端**：Vue3 (Vite + Pinia)
- **数据库**：SQLite + SQLModel

## 常用命令

### 后端 (Python)

```bash
# 启动后端服务（默认端口 8765）
uv run main.py

# 运行测试
uv run pytest
uv run pytest tests/test_xxx.py  # 运行单个测试文件
uv run pytest -v  # 显示详细输出

# 代码检查
uv run ruff check ling_chat tests
uv run ruff format ling_chat tests
```

Tips:执行任何python相关命令都应该使用uv代替

### 前端 (Vue)

```bash
cd frontend_vue

# 安装依赖
pnpm install

# 开发模式（默认端口 5173）
pnpm dev

# 构建生产版本
pnpm build

# 类型检查
pnpm type-check

# 代码格式化
pnpm format
```

### 环境配置

1. 复制 `.env.example` 为 `.env`
2. 确保 Python 3.10+ 环境

### 包管理

- **后端**：使用 `uv` 管理 Python 依赖
  ```bash
  uv venv --python 3.13
  .venv\Scripts\activate  # Windows
  source .venv/bin/activate  # Linux/Mac
  uv pip install .
  ```
- **前端**：使用 `pnpm` 管理 Node.js 依赖
  ```bash
  cd frontend_vue
  pnpm install
  ```

## 代码架构

### 后端结构 (`ling_chat/`)

- `main.py` - 启动入口，确保 `data/game_data/` 存在
- `api/app_server.py` - FastAPI 应用核心
- `api/routes_manager.py` - 路由注册与管理
- `core/ai_service/` - AI 核心逻辑
  - `core.py` - AIService 核心
  - `game_system/` - 游戏系统（台词表、记忆、角色管理）
    - `game_status.py` - 运行时状态容器
    - `role_manager.py` - 角色管理器
    - `memory_builder.py` - 记忆构建器
  - `script_engine/` - 剧本系统
    - `script_manager.py` - 剧本管理
    - `chapter.py` - 章节执行
    - `events/` - 事件系统
  - `message_system/` - 消息处理
    - `message_processor.py` - 用户输入处理
    - `message_generator.py` - AI 响应生成
- `game_database/` - 数据库层
  - `database.py` - 数据库初始化
  - `models.py` - 数据模型 (Role, Save, Line, RunningScript, MemoryBank)
  - `managers/` - 各表管理器 (SaveManager, RoleManager, MemoryManager)
- `core/llm_providers/` - LLM 提供商管理
- `core/messaging/broker.py` - 消息代理（WebSocket 推送）

### 前端结构 (`frontend_vue/src/`)

- `main.ts` - 前端入口
- `api/` - API 封装
  - `websocket/` - WebSocket 通信与 handlers
  - `services/` - HTTP API 服务封装
- `core/events/` - 事件队列处理
  - `event-processor.ts` - 事件处理器基类
  - `processors/` - 各类事件处理器
- `stores/` - Pinia 状态管理
  - `modules/game/` - 游戏状态
  - `modules/ui/` - UI 状态
  - `modules/config/` - 配置状态
- `components/` - Vue 组件
  - `base/widget/` - 基础组件 (Button, Input, Toggle, Slider)
  - `game/standard/` - 游戏核心组件
  - `settings/` - 设置面板组件
  - `ui/` - UI 组件 (Modal, Notification, Toast)
- `views/` - 页面视图
- `router/` - 路由配置

### 技术栈细节

- **前端**：Vue 3.5+、Vite 7、Pinia 3、TypeScript 5.9、Tailwind CSS v4、Element Plus
- **后端**：Python 3.12+、FastAPI、Uvicorn、SQLModel、PyYAML
- **数据库**：SQLite + SQLModel (ORM)

### 数据目录

- `data/` - 开发环境运行时数据
- `data/game_data/` - 游戏资源（角色、剧本等）
  - `characters/` - 角色资源文件夹
  - `scripts/` - 剧本文件夹（每个剧本需要 `story_config.yaml`）
  - `backgrounds/` - 背景图片
- `data/game_database.db` - SQLite 数据库

## 前后端通信

### HTTP API

- 基础路径：`/api/v1/`
- 常用端点：
  - `GET /api/v1/chat/info/init` - 初始化
  - `/api/v1/chat/character/*` - 角色管理
  - `/api/v1/chat/history/*` - 存档管理
  - `/api/v1/chat/script/*` - 剧本管理

### WebSocket

- 端点：`ws://localhost:8765/ws`
- 连接后服务端先发：`{"type": "connection_established", "client_id": "client_<uuid>"}`
- 主要消息类型：
  - `reply` - AI 回复（对话）
  - `narration` - 旁白
  - `background` - 背景切换
  - `music` - 背景音乐
  - `sound` - 音效
  - `modify_character` - 角色状态修改（在场/离场）
  - `input` - 等待用户输入
  - `error` - 错误信息
  - `status_reset` - 状态重置

## 关键概念

### 0.4.0 核心系统

- **台词表 (line_list)**：`GameStatus.line_list` 保存每一句话的原子信息
  - 每句台词包含：`content`, `sender_role_id`, `display_name`, `emotion`, `tts_content`, `action_content`, `audio_file`
  - `GameLine.perceived_role_ids` 记录哪些角色感知到该台词
- **记忆构建 (MemoryBuilder)**：把台词转换为各角色的 LLM 上下文
  - 只有角色说过的话或感知到的台词才会进入该角色的 memory
  - 输出格式为标准 OpenAI `[{role: "system/user/assistant", content}, ...]`
- **在场角色 (present_roles)**：决定哪些角色能感知台词
  - 由 `ModifyCharacterEvent` 控制角色的 `show_character/hide_character`
- **当前角色 (current_character)**：决定下一次 LLM 调用的角色

### 数据库模型 (`ling_chat/game_database/models.py`)

- `Role` - 角色表（统一存储主角、NPC、旁白）
  - `role_type`: `main` | `npc` | `system`
  - `script_key + script_role_key` - 剧本角色映射
- `Save` - 存档表
  - `status` (JSON) - 预留存储背景/音乐/特效等状态
  - `running_script_id` - 关联运行中的剧本
- `Line` - 台词表
  - `perceived_by` - 通过 `LinePerception` 关联感知角色
- `RunningScript` - 剧本运行状态
  - `variable_info` (JSON) - 剧本变量
  - `current_chapter`, `event_sequence` - 进度
- `MemoryBank` - 永久记忆（按存档 + 角色）

### 剧本系统

- 剧本目录：`data/game_data/scripts/`
- 每个剧本需要 `story_config.yaml`
- 事件系统位于 `ling_chat/core/ai_service/script_engine/events/`
- 执行流程：`ScriptManager.start_script()` → `Chapter.run()` → 事件执行 → 下一章

## 开发注意事项

- **新增事件**：继承 `BaseEvent` 并实现 `can_handle()` 和 `execute()`
- **WebSocket 消息**：新增 type 需同步前后端定义与处理器
- **存档扩展**：新增可存档状态需写入 `Save.status` (JSON) 并在 load 时恢复
- **永久记忆接入**：MemoryBank 已实现 CRUD，需在 `sync_memories()` 或 `MessageGenerator` 中接入 LLM 上下文

## 开发文档参考

- `docs/develop/dev_guide.md` - 开发者入门指南（轮椅级教程）
- `docs/develop/character_guide.md` - 角色卡制作指南
- `docs/develop/story_guide.md` - 剧情创作指南
- `DEVELOPER_GUIDE.md` - 0.4.0 架构详解（存档/台词表/记忆构建/剧本系统）
- `docs/develop/project_structure.md` - 项目结构与实现

## 高频文件清单

- 后端入口：`ling_chat/main.py`
- AI 核心：`ling_chat/core/ai_service/core.py`
- 台词/记忆：`game_status.py`, `role_manager.py`, `memory_builder.py`
- 数据库：`database.py`, `models.py`
- 存档管理：`save_manager.py`, `chat_history.py`
- 永久记忆：`memory_manager.py`
- 剧本系统：`script_manager.py`, `chapter.py`, `events_handler.py`
- 前端入口：`frontend_vue/src/main.ts`
- WebSocket 处理：`frontend_vue/src/api/websocket/`
- 事件队列：`frontend_vue/src/core/events/`

# context7各仓库参考

- Tailwind CSS v4:tailwindlabs/tailwindcss.com
- onnxruntime:websites/onnxruntime_ai
- httpx:encode/httpx
- vue3:vuejs/docs
- openai:openai/openai-python
- gemini api:websites/ai_google_dev_gemini-api
- lmstudio api:websites/lmstudio_ai
- ollama api:llmstxt/ollama_llms_txt
