import json
import os
from typing import AsyncGenerator, Dict, List, Optional, Union

import httpx

from ling_chat.core.llm_providers.base import BaseLLMProvider
from ling_chat.core.logger import logger


# 文档：https://ai.google.dev/api
class GeminiProvider(BaseLLMProvider):
    def __init__(self):
        super().__init__()
        self.api_key = os.environ.get("GEMINI_API_KEY")
        self.base_url = os.environ.get(
            "GEMINI_API_URL", "https://generativelanguage.googleapis.com/v1beta"
        )
        self.model_type = os.environ.get("GEMINI_MODEL_TYPE", "gemini-2.5-flash")
        self.proxy_url = os.environ.get("GEMINI_PROXY_URL")
        self.temperature = float(os.environ.get("TEMPERATURE", 1.0))
        self.top_p = float(os.environ.get("TOP_P", 1.0))

        if not self.api_key:
            raise ValueError("需要Gemini API密钥！")

    def initialize_client(self):
        pass

    def _get_http_client(self):
        """获取HTTP客户端，支持代理"""
        timeout_config = httpx.Timeout(connect=20.0, read=60.0, write=20.0, pool=20.0)
        if self.proxy_url and self.proxy_url.strip():
            return httpx.Client(proxy=self.proxy_url, timeout=timeout_config)
        return httpx.Client(timeout=timeout_config)

    def _get_async_http_client(self):
        """获取异步HTTP客户端，支持代理"""
        timeout_config = httpx.Timeout(connect=20.0, read=60.0, write=20.0, pool=20.0)
        if self.proxy_url and self.proxy_url.strip():
            return httpx.AsyncClient(proxy=self.proxy_url, timeout=timeout_config)
        return httpx.AsyncClient(timeout=timeout_config)

    def _convert_messages_to_contents(
        self, messages: List[Dict]
    ) -> tuple[Optional[str], List[Dict]]:
        """
        将OpenAI格式的消息转换为Gemini原生API格式

        :param messages: OpenAI格式的消息列表
        :return: (system_instruction, contents) 元组
        """
        system_instruction = None
        contents = []

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            # 处理system消息 - Gemini使用systemInstruction字段
            if role == "system":
                system_instruction = str(content)
                continue

            # 处理 tool 消息（function response）
            if role == "tool":
                # Gemini 使用 functionResponse 格式
                tool_call_id = msg.get("tool_call_id", "")
                tool_content = msg.get("content", "")
                # 从消息中获取 function name（OpenAI 格式的 tool 消息可能包含 name）
                func_name = msg.get("name") or msg.get("function_name", "")
                contents.append(
                    {
                        "role": "user",
                        "parts": [
                            {
                                "functionResponse": {
                                    "name": func_name,
                                    "response": {"result": tool_content},
                                    "id": tool_call_id,
                                }
                            }
                        ],
                    }
                )
                continue

            # 处理 assistant 消息中的 tool_calls
            if role == "assistant" and msg.get("tool_calls"):
                parts = []
                # 如果有文本内容
                if content:
                    parts.append({"text": str(content)})
                # 添加 tool_calls
                for tc in msg.get("tool_calls", []):
                    func = tc.get("function", {})
                    args = func.get("arguments", {})
                    if isinstance(args, str):
                        args = json.loads(args) if args else {}
                    parts.append(
                        {
                            "functionCall": {
                                "name": func.get("name", ""),
                                "args": args,
                                "id": tc.get("id", ""),
                            }
                        }
                    )
                contents.append({"role": "model", "parts": parts})
                continue

            # 转换角色名称: user -> user, assistant/model -> model
            if role == "human":
                role = "user"
            elif role in ("assistant", "model"):
                role = "model"

            # 构建Gemini格式的content
            contents.append({"role": role, "parts": [{"text": str(content)}]})

        return system_instruction, contents

    def _convert_openai_tools_to_gemini(self, tools: List[Dict]) -> List[Dict]:
        """
        将 OpenAI 格式的 tools 转换为 Gemini 原生格式

        OpenAI 格式：
        [{"type": "function", "function": {"name", "description", "parameters"}}]

        Gemini 格式：
        [{"functionDeclarations": [{"name", "description", "parameters"}]}]
        """
        function_declarations = []
        for tool in tools:
            if tool.get("type") == "function":
                func = tool.get("function", {})
                declaration = {
                    "name": func.get("name", ""),
                    "description": func.get("description", ""),
                    "parameters": func.get("parameters", {}),
                }
                function_declarations.append(declaration)

        return (
            [{"functionDeclarations": function_declarations}]
            if function_declarations
            else []
        )

    def _parse_function_calls(self, parts: List[Dict]) -> List[Dict]:
        """
        解析 Gemini functionCall 响应

        Gemini 格式：parts 中包含 functionCall 对象
        functionCall: {name, id, args}
        注意：args 已经是对象，无需解析
        """
        tool_calls = []
        for part in parts:
            if "functionCall" in part:
                fc = part["functionCall"]
                tool_calls.append(
                    {
                        "id": fc.get("id", ""),
                        "name": fc.get("name", ""),
                        "arguments": fc.get("args", {}),  # args 已是对象
                    }
                )
        return tool_calls

    def _build_request_body(
        self,
        messages: List[Dict],
        stream: bool = False,
        tools: Optional[List[Dict]] = None,
    ) -> Dict:
        """构建Gemini API请求体"""
        system_instruction, contents = self._convert_messages_to_contents(messages)

        body = {
            "contents": contents,
            "generationConfig": {
                "temperature": self.temperature,
                "topP": self.top_p,
            },
        }

        # 添加system instruction（如果有）
        if system_instruction:
            body["systemInstruction"] = {"parts": [{"text": system_instruction}]}

        # 添加 tools（Gemini 原生格式）
        if tools:
            gemini_tools = self._convert_openai_tools_to_gemini(tools)
            if gemini_tools:
                body["tools"] = gemini_tools

        return body

    def generate_response(
        self,
        messages: List[Dict],
        tools: Optional[List[Dict]] = None,
        tool_choice: str = "auto",
    ) -> Union[str, Dict]:
        """生成Gemini模型响应（非流式）"""
        try:
            logger.debug(f"向Gemini API发送请求: {self.model_type}")

            body = self._build_request_body(messages, stream=False, tools=tools)
            url = f"{self.base_url}/models/{self.model_type}:generateContent?key={self.api_key}"

            with self._get_http_client() as client:
                response = client.post(url, json=body, timeout=60.0)

                if response.status_code != 200:
                    error_msg = (
                        f"Gemini API请求错误: {response.status_code} - {response.text}"
                    )
                    logger.error(error_msg)
                    raise Exception(error_msg)

                response_json = response.json()

                # 解析Gemini原生响应格式
                candidates = response_json.get("candidates", [])
                if not candidates:
                    logger.warning("Gemini API返回空candidates")
                    if tools:
                        return {"content": "", "tool_calls": []}
                    return ""

                content = candidates[0].get("content", {})
                parts = content.get("parts", [])

                # 检查是否有 functionCall
                if tools:
                    tool_calls = self._parse_function_calls(parts)
                    # 拼接文本内容
                    result_text = ""
                    for part in parts:
                        if "text" in part:
                            result_text += part["text"]
                    return {
                        "content": result_text,
                        "tool_calls": tool_calls,
                    }

                # 没有 tools，返回纯文本
                result_text = ""
                for part in parts:
                    if "text" in part:
                        result_text += part["text"]
                return result_text

        except Exception as e:
            logger.error(f"Gemini API请求错误: {str(e)}")
            raise

    async def generate_stream_response(
        self, messages: List[Dict]
    ) -> AsyncGenerator[str, None]:
        """生成Gemini流式响应

        :param messages: 消息列表
        :return: 生成器，逐个返回响应内容块
        """
        try:
            logger.debug(f"向Gemini模型发送流式请求: {self.model_type}")

            body = self._build_request_body(messages, stream=True)
            url = f"{self.base_url}/models/{self.model_type}:streamGenerateContent?key={self.api_key}&alt=sse"

            async with self._get_async_http_client() as client:
                async with client.stream(
                    "POST", url, json=body, timeout=60.0
                ) as response:
                    if response.status_code != 200:
                        await response.aread()
                        error_msg = f"Gemini流式API请求错误: {response.status_code} - {response.text}"
                        logger.error(error_msg)
                        raise Exception(error_msg)

                    async for line in response.aiter_lines():
                        if not line.strip():
                            continue

                        # SSE格式: data: {...}
                        if line.startswith("data: "):
                            chunk_data = line[6:]  # 移除 "data: " 前缀
                            if chunk_data == "[DONE]":
                                break

                            try:
                                chunk_json = json.loads(chunk_data)

                                # 解析Gemini流式响应格式
                                candidates = chunk_json.get("candidates", [])
                                if not candidates:
                                    continue

                                content = candidates[0].get("content", {})
                                parts = content.get("parts", [])

                                for part in parts:
                                    if "text" in part:
                                        yield part["text"]

                            except json.JSONDecodeError:
                                logger.warning(f"未能解析返回数据: {line}")
                                continue

        except Exception as e:
            logger.error(f"Gemini API流式请求失败: {str(e)}")
            raise
