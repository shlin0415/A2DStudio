"""测试 GSV API 集成 — generate_voice + stream + WAV 有效性（需 GSV 在线）"""
import os
import wave
import pytest
import httpx
from ling_chat.core.TTS.gsv_adapter import GPTSoVITSAdapter


REF_AUDIO = (
    "D:/aaa-new/setups/a2d-studio/ref/LingChat/"
    "ling_chat/static/game_data/characters/艾玛/0101Adv26_Ema012.wav"
)
REF_TEXT = "うん、ノアちゃんは新しくまた何かを描くって言ってた。"


def validate_wav(filepath: str) -> dict:
    """用 wave + array 模块检查：时长 > 0.3s 且样本峰值 > 100（非静音）"""
    import array
    with wave.open(filepath, "rb") as wf:
        frames = wf.getnframes()
        rate = wf.getframerate()
        duration = frames / rate if rate > 0 else 0
        raw = wf.readframes(frames)
        samples = array.array("h", raw)
        max_val = max(abs(s) for s in samples) if samples else 0
    return {
        "duration_s": round(duration, 2),
        "max_sample": max_val,
        "sample_count": frames,
        "sample_rate": rate,
        "valid": duration > 0.3 and max_val > 100,
    }


def _save_and_validate(audio_bytes: bytes, tmp_path: str, label: str) -> None:
    """写入临时文件并断言音频有效（非静音）"""
    path = os.path.join(tmp_path, f"{label}.wav")
    with open(path, "wb") as f:
        f.write(audio_bytes)
    info = validate_wav(path)
    assert info["valid"], (
        f"Audio invalid: {info['duration_s']}s, max_sample={info['max_sample']} "
        f"({info['sample_count']} samples @ {info['sample_rate']}Hz) — "
        f"{'too short' if info['duration_s'] <= 0.3 else 'near-silent'}"
    )


@pytest.fixture
def ema_adapter():
    return GPTSoVITSAdapter(
        ref_audio_path=REF_AUDIO,
        prompt_text=REF_TEXT,
        prompt_lang="ja",
        text_lang="ja",
        api_url="http://127.0.0.1:31801",
    )


@pytest.mark.asyncio
async def test_generate_voice_valid_audio(ema_adapter, tmp_path):
    """生成一段日文语音，必须 > 0.3 秒"""
    data = await ema_adapter.generate_voice("こんにちは")
    assert isinstance(data, bytes)
    assert len(data) > 100
    _save_and_validate(data, str(tmp_path), "ema_hello")


@pytest.mark.asyncio
async def test_generate_voice_stream_valid_audio(ema_adapter, tmp_path):
    """流式生成后合并所有 chunk，验证总时长 > 0.3 秒"""
    all_data = b""
    async for chunk in ema_adapter.generate_voice_stream(
        "こんにちは。お元気ですか。"
    ):
        assert isinstance(chunk, bytes)
        assert len(chunk) > 100
        all_data += chunk
    assert len(all_data) > 0
    _save_and_validate(all_data, str(tmp_path), "ema_stream")


@pytest.mark.asyncio
async def test_both_ports_generate_valid_audio(tmp_path):
    """验证两个 GSV 端口都能生成有效日文语音"""
    for port, label in [("31801", "ema"), ("31802", "hiro")]:
        adapter = GPTSoVITSAdapter(
            ref_audio_path=REF_AUDIO,
            prompt_text=REF_TEXT,
            prompt_lang="ja",
            text_lang="ja",
            api_url=f"http://127.0.0.1:{port}",
        )
        data = await adapter.generate_voice("こんにちは")
        assert len(data) > 100, f"{label}:{port} returned {len(data)} bytes"
        _save_and_validate(data, str(tmp_path), f"{label}_port_{port}")


@pytest.mark.asyncio
async def test_gsv_api_reachable(ema_adapter):
    """验证 GSV API /docs 端点可连通"""
    async with httpx.AsyncClient() as client:
        resp = await client.get(ema_adapter.api_url + "/docs", timeout=5)
    assert resp.status_code == 200
