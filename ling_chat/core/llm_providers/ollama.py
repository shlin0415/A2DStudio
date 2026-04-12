import json
import os
from typing import AsyncGenerator, Dict, List, Optional, Union

import httpx

from ling_chat.core.llm_providers.base import BaseLLMProvider
from ling_chat.core.logger import logger


def _normalize_base_url(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw:
        return "http://localhost:11434"
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw.rstrip("/")
    return f"http://{raw}".rstrip("/")


class OllamaProvider(BaseLLMProvider):
    def __init__(self):
        super().__init__()
        self.base_url = _normalize_base_url(
            os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
        )
        self.model_type = (
            os.environ.get("OLLAMA_MODEL") or os.environ.get("MODEL_TYPE") or "llama3"
        )
        self._timeout = httpx.Timeout(connect=20.0, read=60.0, write=20.0, pool=20.0)
        self.temperature = float(os.environ.get("TEMPERATURE", 1.3))
        self.top_p = float(os.environ.get("TOP_P", 0.9))

    def initialize_client(self):
        pass

    def _parse_tool_calls(self, tool_calls_raw: List[Dict]) -> List[Dict]:
        """
        解析 Ollama 工具调用响应

        根据 Ollama OpenAPI 文档：
        ToolCall 格式为 {function: {name, description, arguments: object}}
        注意：arguments 是 object，不是 JSON 字符串！
        """
        parsed = []
        for tc in tool_calls_raw:
            func = tc.get("function", {})
            # Ollama 原生 API 的 arguments 已经是对象
            args = func.get("arguments", {})
            if isinstance(args, str):
                # 兼容处理：如果意外收到字符串，尝试解析
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    logger.warning(f"无法解析 tool_call arguments: {args}")
                    args = {}
            parsed.append(
                {
                    "id": tc.get("id", f"call_{len(parsed)}"),  # Ollama 可能不返回 id
                    "name": func.get("name", ""),
                    "arguments": args,
                }
            )
        return parsed

    def generate_response(
        self,
        messages: List[Dict],
        tools: Optional[List[Dict]] = None,
        tool_choice: str = "auto",
    ) -> Union[str, Dict]:
        """生成 Ollama 模型响应（使用原生 /api/chat 端点）"""
        try:
            logger.info(f"Sending request to Ollama API: {self.base_url}/api/chat")

            payload: Dict = {
                "model": self.model_type,
                "messages": messages,
<<<<<<< HEAD
                "options": {
                    "temperature": self.temperature,
                    "top_p": self.top_p,
                },
=======
>>>>>>> c8a234ea (feat:工具基础支持)
                "stream": False,
            }

            # 添加 options（温度等参数放在 options 中）
            payload["options"] = {
                "temperature": self.temperature,
                "top_p": self.top_p,
            }

            # 添加 tools 支持（Ollama 原生格式）
            if tools:
                payload["tools"] = tools

            with httpx.Client(timeout=self._timeout) as client:
                response = client.post(f"{self.base_url}/api/chat", json=payload)

                if response.status_code != 200:
                    error_msg = f"Ollama API returned error: {response.status_code} - {response.text}"
                    logger.error(error_msg)
                    raise Exception(error_msg)

                response_json = response.json()

                # 解析响应
                message = response_json.get("message", {})
                content = message.get("content", "")
                tool_calls_raw = message.get("tool_calls", [])

                # 检查是否有 tool_calls
                if tools and tool_calls_raw:
                    return {
                        "content": content,
                        "tool_calls": self._parse_tool_calls(tool_calls_raw),
                    }

                # 没有 tools 或没有 tool_calls，返回纯文本
                if tools:
                    return {"content": content, "tool_calls": []}
                return content

        except Exception as e:
            logger.error(f"Ollama API call failed: {str(e)}")
            raise

    async def generate_stream_response(
        self, messages: List[Dict]
    ) -> AsyncGenerator[str, None]:
<<<<<<< HEAD
        """生成Ollama流式响应
=======
        """生成 Ollama 流式响应
>>>>>>> c8a234ea (feat:工具基础支持)
        :param messages: 消息列表
        :return: 返回一个生成器，每次迭代返回一个内容块
        """
        try:
            logger.info(f"正在给 Ollama 发送流式请求: {self.base_url}/api/chat")

            payload = {
                "model": self.model_type,
                "messages": messages,
                "options": {
                    "temperature": self.temperature,
                    "top_p": self.top_p,
                },
                "stream": True,
            }

            async with httpx.AsyncClient(timeout=self._timeout) as client:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/api/chat",
                    json=payload,
                ) as response:
                    if response.status_code != 200:
                        body = await response.aread()
                        text = ""
                        try:
                            text = body.decode("utf-8", errors="replace")
                        except Exception:
                            text = str(body)
                        error_msg = (
                            f"Ollama 流式返回了错误: {response.status_code} - {text}"
                        )
                        logger.error(error_msg)
                        raise Exception(error_msg)

                    async for line in response.aiter_lines():
                        if line.strip():  # 确保不是空行
                            try:
                                chunk_json = json.loads(line)
                                content = chunk_json.get("message", {}).get(
                                    "content", ""
                                )
                                if content:
                                    yield content
                            except json.JSONDecodeError:
                                logger.warning(f"无法解析的响应块: {line}")
                                continue

        except Exception as e:
            logger.error(f"Ollama 流式调用失败: {str(e)}")
            raise
