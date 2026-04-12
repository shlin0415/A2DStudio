# LLM Tools 功能使用文档

本文档介绍如何在 LingChat 中使用 LLM 的 Tools (Function Calling) 功能。

## 概述

Tools 功能允许 LLM 调用外部函数来完成特定任务。WebLLM 提供商已支持 OpenAI 格式的 tools 参数。

## 支持的工具格式

采用 OpenAI 标准格式：

```python
tools = [
    {
        "type": "function",
        "function": {
            "name": "函数名称",
            "description": "函数描述",
            "parameters": {
                "type": "object",
                "properties": {
                    "参数名": {
                        "type": "参数类型",
                        "description": "参数描述"
                    }
                },
                "required": ["必填参数列表"]
            }
        }
    }
]
```

## 使用方法

### 1. 基础调用（无工具执行）

```python
from ling_chat.core.llm_providers.manager import LLMManager

llm_manager = LLMManager()

result = llm_manager.process_message(messages, tools=[weather_tool])

if isinstance(result, dict) and result["tool_calls"]:
    # 需要业务层自己处理 tool_calls
    print(f"需要调用工具: {result['tool_calls']}")
```

使用 `process_message_with_tools` 方法，一行代码完成工具调用闭环：

```python
from ling_chat.core.llm_providers.manager import LLMManager

llm_manager = LLMManager()

# 定义工具执行器
def execute_tool(name: str, arguments: dict) -> str:
    if name == "get_weather":
        # 实际调用天气 API
        return f"北京今天晴天，气温 25°C"
    raise ValueError(f"未知工具: {name}")

# 完整闭环调用
result = llm_manager.process_message_with_tools(
    messages=[
        {"role": "system", "content": "你是一个有用的助手"},
        {"role": "user", "content": "北京今天天气怎么样？"}
    ],
    tools=[weather_tool],
    tool_executor=execute_tool,
    max_rounds=3
)

print(result)  # 直接拿到最终答案
```

**`process_message_with_tools` 参数说明**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `messages` | List[Dict] | 是 | 初始消息列表 |
| `tools` | List[Dict] | 否 | 工具定义列表 |
| `tool_choice` | str | 否 | 工具选择策略，默认 "auto" |
| `tool_executor` | Callable | 否* | 工具执行回调，接收 `(name, arguments)` 返回字符串 |
| `max_rounds` | int | 否 | 最大调用轮数，默认 3，防止无限循环 |

\* 当 LLM 返回 tool_calls 时必须提供，否则会抛出 ValueError。

### 4. 直接使用 Provider

```python
from ling_chat.core.llm_providers.manager import LLMManager

# 初始化 LLM 管理器
llm_manager = LLMManager()

# 定义工具
weather_tool = {
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "获取指定城市的天气信息",
        "parameters": {
            "type": "object",
            "properties": {
                "city": {
                    "type": "string",
                    "description": "城市名称"
                },
                "unit": {
                    "type": "string",
                    "enum": ["celsius", "fahrenheit"],
                    "description": "温度单位"
                }
            },
            "required": ["city"]
        }
    }
}

# 定义消息
messages = [
    {"role": "system", "content": "你是一个有帮助的助手"},
    {"role": "user", "content": "北京今天天气怎么样？"}
]

# 调用（带 tools 参数）
result = llm_manager.process_message(
    messages,
    tools=[weather_tool],
    tool_choice="auto"  # 可选: "auto", "none", "required", 或 {"type": "function", "function": {"name": "get_weather"}}
)

# 处理结果
if isinstance(result, dict):
    content = result["content"]  # 文本回复
    tool_calls = result["tool_calls"]  # 工具调用列表
    
    for call in tool_calls:
        print(f"工具名: {call['name']}")
        print(f"参数: {call['arguments']}")  # dict 类型
        print(f"调用ID: {call['id']}")  # 用于后续 tool response
else:
    # 没有 tools 时返回 str
    print(result)
```

### 2. 直接使用 Provider

```python
from ling_chat.core.llm_providers.web_llm import WebLLMProvider

provider = WebLLMProvider(
    model_type="deepseek-chat",
    api_key="your-api-key",
    base_url="https://api.deepseek.com/v1"
)

result = provider.generate_response(
    messages=messages,
    tools=[weather_tool],
    tool_choice="auto"
)
```

## 返回结果格式

### 有 tools 时返回 dict

```python
{
    "content": str | None,  # LLM 的文本回复
    "tool_calls": [
        {
            "id": "call_xxx",  # 调用唯一标识
            "name": "get_weather",  # 函数名
            "arguments": {  # 已解析为 dict
                "city": "北京",
                "unit": "celsius"
            }
        }
    ]
}
```

### 无 tools 时返回 str

保持原有行为，直接返回字符串。

## 参数说明

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `messages` | List[Dict] | 是 | 消息列表 |
| `tools` | List[Dict] | 否 | 工具定义列表 |
| `tool_choice` | str | 否 | 工具选择策略，默认 "auto" |

### tool_choice 选项

- `"auto"` - 模型自行决定是否调用工具
- `"none"` - 不调用工具
- `"required"` - 必须调用工具
- `{"type": "function", "function": {"name": "xxx"}}` - 强制调用指定工具

## 完整对话流程示例

```python
# 第一轮：用户提问，模型决定调用工具
messages = [
    {"role": "user", "content": "北京今天天气怎么样？"}
]

result = llm_manager.process_message(messages, tools=[weather_tool])

# 如果模型决定调用工具
if isinstance(result, dict) and result["tool_calls"]:
    # 执行工具调用（实际业务逻辑）
    tool_call = result["tool_calls"][0]
    weather_result = get_weather_api(**tool_call["arguments"])
    
    # 添加工具调用结果到对话
    messages.append({
        "role": "assistant",
        "content": result["content"] or "",
        "tool_calls": [{
            "id": tool_call["id"],
            "type": "function",
            "function": {
                "name": tool_call["name"],
                "arguments": str(tool_call["arguments"])
            }
        }]
    })
    
    messages.append({
        "role": "tool",
        "tool_call_id": tool_call["id"],
        "content": str(weather_result)
    })
    
    # 第二轮：获取最终回复
    final_result = llm_manager.process_message(messages, tools=[weather_tool])
```

## 注意事项

1. **模型支持**：请确保使用的模型支持 function calling（如 deepseek-chat、GPT-4、qwen3 等）
2. **参数已存在**：如果 tools 参数已存在，不会覆盖（保持原有值）

## 支持的提供商

| 提供商 | Tools 支持状态 | API 端点 |
|--------|---------------|----------|
| WebLLM | ✅ 完整支持 | OpenAI 兼容格式 |
| Ollama | ✅ 完整支持 | `/api/chat` 原生端点 |
| Gemini | ✅ 完整支持 | `/models/:name:generateContent` 原生端点 |
| LM Studio | ✅ 完整支持 | `/v1/chat/completions` 兼容端点（tools 时），`/api/v1/chat` 专有端点（无 tools 时） |
| Qwen Translate | ⚠️ 专用翻译模型，不建议使用 tools |

## 各 Provider 实现细节

### Ollama

使用原生 `/api/chat` 端点，请求格式：

```json
{
  "model": "qwen3",
  "messages": [...],
  "tools": [{"type": "function", "function": {...}}],
  "stream": false
}
```

响应中 `tool_calls.arguments` 为 **object**（无需解析）。

### Gemini

使用原生 `/models/:name:generateContent` 端点，需要将 OpenAI tools 格式转换为 Gemini 格式：

```json
{
  "contents": [...],
  "tools": [{"functionDeclarations": [{name, description, parameters}]}]
}
```

响应中 `functionCall.args` 为 **object**（无需解析）。

### LM Studio

采用双端点策略：

- **无 tools**：使用 `/api/v1/chat` 专有端点（更丰富的原生功能）
- **有 tools**：使用 `/v1/chat/completions` OpenAI 兼容端点

响应中 `tool_calls.arguments` 为 **JSON 字符串**（需要解析）。
