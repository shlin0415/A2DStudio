from abc import ABC, abstractmethod
from typing import AsyncGenerator, Dict, List, Optional, Union


class BaseLLMProvider(ABC):
    def __init__(self):
        """基类初始化"""
        super().__init__()

    @abstractmethod
    def initialize_client(self):
        """初始化客户端连接"""
        pass

    @abstractmethod
    def generate_response(
        self,
        messages: List[Dict],
        tools: Optional[List[Dict]] = None,
        tool_choice: str = "auto",
    ) -> Union[str, Dict]:
        """生成模型响应

        Args:
            messages: 消息列表
            tools: 可选的工具列表，格式为 OpenAI tools 格式
            tool_choice: 工具选择策略，默认 "auto"

        Returns:
            如果没有 tools，返回 str
            如果有 tools，返回 dict，包含 content 和 tool_calls
        """
        pass

    @abstractmethod
    async def generate_stream_response(
        self, messages: List[Dict]
    ) -> AsyncGenerator[str, None]:
        """生成模型流式响应"""
        yield ""  # hack return type for async generator
