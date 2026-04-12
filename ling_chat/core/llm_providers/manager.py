<<<<<<< HEAD
=======
import json
>>>>>>> c8a234ea (feat:工具基础支持)
import os
from typing import Callable, Dict, List, Optional, Union

from ling_chat.core.llm_providers.base import BaseLLMProvider
from ling_chat.core.llm_providers.provider_factory import LLMProviderFactory
from ling_chat.core.logger import logger


class LLMManager:
    def __init__(self, llm_job=None):
        """
        初始化LLM管理器

        :param provider_config: 可选，提供者配置字典。如果为None，则从环境变量加载
        """
        if not llm_job or llm_job == "main":
            self.llm_provider_type = os.environ.get("LLM_PROVIDER", "webllm")
            self.model_type = os.environ.get("MODEL_TYPE", "deepseek-chat")
            self.api_key = os.environ.get("CHAT_API_KEY", "")
            self.api_url = os.environ.get(
                "CHAT_BASE_URL", "https://api.deepseek.com/v1"
            )
            # 确保provider_type存在
            provider_type = self.llm_provider_type.lower()
            logger.info(f"初始化LLM {provider_type} 提供商中...")
        elif llm_job == "translator":
            translate_provider = os.environ.get("TRANSLATE_LLM_PROVIDER", "none")

            # 检查是否需要使用主LLM配置
            if translate_provider.lower() in ["none", ""]:
                logger.info(
                    "检测到TRANSLATE_LLM_PROVIDER为none或空值，将使用主LLM配置进行翻译"
                )

                self.llm_provider_type = os.environ.get("LLM_PROVIDER", "webllm")
                self.model_type = os.environ.get("MODEL_TYPE", "deepseek-chat")
                self.api_key = os.environ.get("CHAT_API_KEY", "")
                self.api_url = os.environ.get(
                    "CHAT_BASE_URL", "https://api.deepseek.com/v1"
                )
                provider_type = self.llm_provider_type.lower()
                logger.info(f"翻译模型将使用主LLM配置: {provider_type}")
            else:
                # 使用独立的翻译配置
                self.llm_provider_type = translate_provider
                self.model_type = os.environ.get("TRANSLATE_MODEL", "")
                self.api_key = os.environ.get("TRANSLATE_API_KEY", "")
                self.api_url = os.environ.get("TRANSLATE_BASE_URL", "")
                provider_type = self.llm_provider_type.lower()
                logger.info(f"初始化翻译模型 {provider_type} 提供商中...")

        self.provider = self._initialize_provider()

    def _initialize_provider(self) -> "BaseLLMProvider":
        """
        初始化大模型提供者

        :param provider_config: 提供者配置字典
        :return: 初始化的大模型提供者实例
        """
        # 确保provider_type存在
        provider_type = self.llm_provider_type.lower()
        if provider_type == "webllm":
            return LLMProviderFactory.create_provider(
                provider_type, self.model_type, self.api_key, self.api_url
            )
        else:
            return LLMProviderFactory.create_provider(provider_type)

    def process_message(
        self,
        messages: List[Dict],
        tools: Optional[List[Dict]] = None,
        tool_choice: str = "auto",
    ) -> Union[str, Dict]:
        """处理消息请求

        Args:
            messages: 消息列表
            tools: 可选的工具列表，格式为 OpenAI tools 格式
            tool_choice: 工具选择策略，默认 "auto"

        Returns:
            如果没有 tools，返回 str
            如果有 tools，返回 dict，包含 content 和 tool_calls
        """
        return self.provider.generate_response(
            messages, tools=tools, tool_choice=tool_choice
        )

    async def process_message_stream(self, messages: List[Dict]):
        async for chunk in self.provider.generate_stream_response(messages):
            yield chunk

    def process_message_with_tools(
        self,
        messages: List[Dict],
        tools: Optional[List[Dict]] = None,
        tool_choice: str = "auto",
        tool_executor: Optional[Callable[[str, dict], str]] = None,
        max_rounds: int = 3,
    ) -> str:
        """带工具执行的完整对话闭环

        Args:
            messages: 初始消息
            tools: 工具列表
            tool_choice: 工具选择策略
            tool_executor: 工具执行回调 (tool_name, arguments) -> 结果字符串
            max_rounds: 最大工具调用轮数

        Returns:
            最终的文本响应（str）

        Raises:
            ValueError: 如果提供了 tool_calls 但没有 tool_executor
            RuntimeError: 如果超过 max_rounds 仍未完成
        """
        if not tools:
            result = self.process_message(messages, tools=None)
            return result if isinstance(result, str) else result.get("content", "")

        rounds = 0
        current_messages = [msg.copy() for msg in messages]

        while rounds < max_rounds:
            rounds += 1

            result = self.process_message(
                current_messages, tools=tools, tool_choice=tool_choice
            )

            if not isinstance(result, dict) or not result.get("tool_calls"):
                #logger.debug(f"LLM 最终响应: {result if isinstance(result, str) else result.get('content', '')}")
                return result if isinstance(result, str) else result.get("content", "")

            if not tool_executor:
                raise ValueError(
                    "LLM 返回了 tool_calls 但未提供 tool_executor。"
                    "请使用 process_message_with_tools 并传入 tool_executor 回调。"
                )

            assistant_msg = {
                "role": "assistant",
                "content": result.get("content") or "",
                "tool_calls": [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": json.dumps(tc["arguments"])
                        }
                    }
                    for tc in result["tool_calls"]
                ]
            }
            current_messages.append(assistant_msg)

            #logger.debug(f"助手消息: {assistant_msg}")

            for tool_call in result["tool_calls"]:
                tool_id = tool_call.get("id", "")
                tool_name = tool_call.get("name", "")
                tool_args = tool_call.get("arguments", {})

                try:
                    tool_result = tool_executor(tool_name, tool_args)
                    content = str(tool_result)
                except Exception as e:
                    content = f"Error: {str(e)}"
                    logger.error(f"工具执行失败 [{tool_name}]: {str(e)}")

                tool_response_msg = {
                    "role": "tool",
                    "tool_call_id": tool_id,
                    "name": tool_name,
                    "content": content,
                }
                
                current_messages.append(tool_response_msg)
                #logger.debug(f"工具响应: {tool_response_msg}")

        raise RuntimeError(f"超过最大轮数 {max_rounds} 仍未完成工具调用")
