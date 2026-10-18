from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ling_chat.core.llm_providers.web_llm import WebLLMProvider


@pytest.mark.asyncio
async def test_generate_stream_response_skips_chunks_without_choices():
    async def stream_chunks():
        yield SimpleNamespace(choices=[], usage=SimpleNamespace(total_tokens=12))
        yield SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(content="第一句"))]
        )
        yield SimpleNamespace(choices=[], usage=SimpleNamespace(total_tokens=12))
        yield SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(content="第二句"))]
        )

    provider = WebLLMProvider.__new__(WebLLMProvider)
    provider.async_client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=AsyncMock(return_value=stream_chunks()))
        )
    )
    provider.model_type = "mimo-v2.6-flash"
    provider.temperature = 1.3
    provider.top_p = 0.9
    provider.max_tokens = 16
    provider.thinking = "none"

    content_chunks = [
        content
        async for content in provider.generate_stream_response(
            [{"role": "user", "content": "生成两句测试文本"}]
        )
    ]

    assert content_chunks == ["第一句", "第二句"]
