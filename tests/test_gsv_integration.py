"""测试 GSV API 集成 — generate_voice + stream（需 GSV 在线）"""
import pytest
import httpx
from ling_chat.core.TTS.gsv_adapter import GPTSoVITSAdapter


REF_AUDIO = (
    "D:/aaa-new/setups/a2d-studio/ref/LingChat/"
    "ling_chat/static/game_data/characters/艾玛/0101Adv26_Ema012.wav"
)


@pytest.fixture
def ema_adapter():
    return GPTSoVITSAdapter(
        ref_audio_path=REF_AUDIO,
        prompt_text="うん、ノアちゃんは新しくまた何かを描くって言ってた。",
        prompt_lang="ja",
        text_lang="ja",
        api_url="http://127.0.0.1:31801",
    )


@pytest.mark.asyncio
async def test_generate_voice_returns_non_empty_bytes(ema_adapter):
    data = await ema_adapter.generate_voice("こんにちは")
    assert isinstance(data, bytes)
    assert len(data) > 100  # WAV header is 44 bytes, audio should be larger


@pytest.mark.asyncio
async def test_generate_voice_stream_yields_chunks(ema_adapter):
    chunks = []
    async for chunk in ema_adapter.generate_voice_stream(
        "こんにちは。お元気ですか。"
    ):
        chunks.append(chunk)
    assert len(chunks) > 0, "Expected at least one chunk from streaming"
    for c in chunks:
        assert isinstance(c, bytes)
        assert len(c) > 100


@pytest.mark.asyncio
async def test_gsv_api_reachable(ema_adapter):
    """验证 GSV API /docs 端点可连通"""
    async with httpx.AsyncClient() as client:
        resp = await client.get(ema_adapter.api_url + "/docs", timeout=5)
    assert resp.status_code == 200
