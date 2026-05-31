"""测试音频三级链 — ref → cache → generate（需 GSV + Cache）"""
import os
import wave
import pytest
from ling_chat.core.audio_orchestrator import get_best_audio, AudioResult
from ling_chat.core.TTS.gsv_adapter import GPTSoVITSAdapter
from ling_chat.core.cache_manager import CacheManager


def _assert_valid_wav(filepath: str):
    with wave.open(filepath, "rb") as wf:
        frames = wf.getnframes()
        rate = wf.getframerate()
        duration = frames / rate if rate > 0 else 0
    assert duration > 0.3, (
        f"Generated audio too short: {duration:.2f}s "
        f"({frames} samples @ {rate}Hz)"
    )


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
async def test_tier3_fallback_to_generation(ema_adapter, tmp_path):
    """Tier 1+2 都关 → 直接走 Tier 3 生成"""
    os.environ["A2D_ENABLE_REF_AUDIO"] = "false"
    os.environ["A2D_ENABLE_AUDIO_CACHE"] = "false"
    cm = CacheManager(cache_dir=str(tmp_path), max_size_mb=100)
    result = await get_best_audio(
        character="ema",
        tts_text="こんにちは",
        display_text="こんにちは",
        gsv_adapter=ema_adapter,
        cache_manager=cm,
    )
    assert isinstance(result, AudioResult)
    assert result.source == "generated"
    assert os.path.exists(result.audio_path)
    _assert_valid_wav(result.audio_path)
@pytest.mark.asyncio
async def test_tier2_cache_hit(ema_adapter, tmp_path):
    """第二次相同文本 → 命中缓存"""
    os.environ["A2D_ENABLE_REF_AUDIO"] = "false"
    os.environ["A2D_ENABLE_AUDIO_CACHE"] = "true"
    cm = CacheManager(cache_dir=str(tmp_path), max_size_mb=100)
    # 第一次：生成
    r1 = await get_best_audio(
        character="ema",
        tts_text="おはよう",
        display_text="おはよう",
        gsv_adapter=ema_adapter,
        cache_manager=cm,
    )
    assert r1.source == "generated"
    _assert_valid_wav(r1.audio_path)
    # 第二次：应命中缓存
    r2 = await get_best_audio(
        character="ema",
        tts_text="おはよう",
        display_text="おはよう",
        gsv_adapter=ema_adapter,
        cache_manager=cm,
    )
    assert r2.source == "cache"
    assert r2.audio_path == r1.audio_path


@pytest.mark.asyncio
async def test_audio_result_has_valid_source(ema_adapter, tmp_path):
    """验证返回结构正确"""
    os.environ["A2D_ENABLE_REF_AUDIO"] = "false"
    os.environ["A2D_ENABLE_AUDIO_CACHE"] = "false"
    cm = CacheManager(cache_dir=str(tmp_path), max_size_mb=100)
    result = await get_best_audio(
        character="ema",
        tts_text="テスト",
        display_text="テスト",
        gsv_adapter=ema_adapter,
        cache_manager=cm,
    )
    assert result.audio_path
    assert result.source in ("ref", "cache", "generated")
    _assert_valid_wav(result.audio_path)