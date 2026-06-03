"""GSV API 集成测试 — 每角色独立参数 + 真实对话文本 + set_model（需 GSV 在线）"""
import json
import os
import wave
from pathlib import Path

import pytest
import httpx
from ling_chat.core.TTS.gsv_adapter import GPTSoVITSAdapter


# ═══════════════════════════════════════════════════════════════
# 路径常量
# ═══════════════════════════════════════════════════════════════

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_CHAR_BASE = _PROJECT_ROOT / "ling_chat" / "static" / "game_data" / "characters"
_DIALOGUE_PATH = _CHAR_BASE / "艾玛" / "test_data" / "dialogue.jsonl"



# ═══════════════════════════════════════════════════════════════
# 每角色配置（参数来源：voice_setting.txt 的 RefAudioSettings）
# ═══════════════════════════════════════════════════════════════

EMA_CONFIG = {
    "port": 31801,
    "char_folder": str(_CHAR_BASE / "艾玛"),
    "ref_audio": str(_CHAR_BASE / "艾玛" / "0101Adv26_Ema012.wav"),
    # ref_text 必须与参考音频内容一致（完整版）
    "ref_text": (
        "うん、ノアちゃんは新しくまた何かを描くって言ってた。"
        "そのために一旦、白くしたんじゃないかな。"
    ),
    "gpt_model": str(_CHAR_BASE / "艾玛" / "models" / "gsv" / "manosaba_ema-e15.ckpt"),
    "sovits_model": str(_CHAR_BASE / "艾玛" / "models" / "gsv" / "manosaba_ema_e8_s864.pth"),
    "speed_factor": 0.95,
    "top_k": 10,
    "top_p": 0.9,
    "temperature": 0.8,
}

HIRO_CONFIG = {
    "port": 31802,
    "char_folder": str(_CHAR_BASE / "希罗"),
    "ref_audio": str(_CHAR_BASE / "希罗" / "0205Trial09_Hiro093.ogg"),
    # ref_text 必须与参考音频内容一致
    "ref_text": "その感情を人は……【博愛】と呼ぶんじゃないかな。",
    "gpt_model": str(_CHAR_BASE / "希罗" / "models" / "gsv" / "hiro-e15.ckpt"),
    "sovits_model": str(_CHAR_BASE / "希罗" / "models" / "gsv" / "hiro_e8_s2184.pth"),
    "speed_factor": 1.05,
    "top_k": 15,
    "top_p": 1.0,
    "temperature": 1.0,
}


# ═══════════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════════

def _load_dialogue_lines() -> list[dict]:
    """从角色 test_data/dialogue.jsonl 加载对话行，跳过 header，返回每角色各行"""
    lines: list[dict] = []
    with open(_DIALOGUE_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            if "header" in data:
                continue
            lines.append(data)
    return lines


def _lines_for(character: str) -> list[dict]:
    """筛选某角色的所有台词"""
    return [d for d in _load_dialogue_lines() if d.get("character") == character]


def validate_wav(filepath: str) -> dict:
    """时长 > 0.3s 且样本峰值 > 100（非静音）"""
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


def _save_and_validate(audio_bytes: bytes, tmp_path: str, label: str) -> dict:
    """写入临时文件 + 断言音频有效"""
    path = os.path.join(tmp_path, f"{label}.wav")
    with open(path, "wb") as f:
        f.write(audio_bytes)
    info = validate_wav(path)
    assert info["valid"], (
        f"Audio invalid: {info['duration_s']}s, max_sample={info['max_sample']} "
        f"({info['sample_count']} samples @ {info['sample_rate']}Hz) — "
        f"{'too short' if info['duration_s'] <= 0.3 else 'near-silent'}"
    )
    return info


def _make_adapter(config: dict) -> GPTSoVITSAdapter:
    """用角色配置创建 adapter（正确参数）"""
    return GPTSoVITSAdapter(
        ref_audio_path=config["ref_audio"],
        prompt_text=config["ref_text"],
        prompt_lang="ja",
        api_url=f"http://127.0.0.1:{config['port']}",
        speed_factor=config["speed_factor"],
        top_k=config["top_k"],
        top_p=config["top_p"],
        temperature=config["temperature"],
    )


# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════

@pytest.fixture(scope="session")
def _gsv_models_loaded():
    """会话级 fixture：预加载 Emma + Hiro 模型到各自端口（仅一次）"""
    import asyncio

    async def _load():
        for cfg in [EMA_CONFIG, HIRO_CONFIG]:
            adapter = GPTSoVITSAdapter(
                ref_audio_path=cfg["ref_audio"],
                prompt_text=cfg["ref_text"],
                api_url=f"http://127.0.0.1:{cfg['port']}",
            )
            ok = await adapter.set_model(cfg["gpt_model"], cfg["sovits_model"])
            if not ok:
                pytest.fail(f"Failed to set model on port {cfg['port']}")
        return True

    return asyncio.run(_load())


@pytest.fixture
def ema_adapter():
    """Emma adapter — 角色专属参数"""
    return _make_adapter(EMA_CONFIG)


@pytest.fixture
def hiro_adapter():
    """Hiro adapter — 角色专属参数"""
    return _make_adapter(HIRO_CONFIG)


# ═══════════════════════════════════════════════════════════════
# 连通性检查
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_gsv_ema_reachable(ema_adapter):
    """Emma 端口 /docs 可连通"""
    async with httpx.AsyncClient() as client:
        resp = await client.get(ema_adapter.api_url + "/docs", timeout=5)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_gsv_hiro_reachable(hiro_adapter):
    """Hiro 端口 /docs 可连通"""
    async with httpx.AsyncClient() as client:
        resp = await client.get(hiro_adapter.api_url + "/docs", timeout=5)
    assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════
# 单句生成 — 艾玛
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_ema_first_line(ema_adapter, tmp_path):
    """艾玛第一句台词：text_jp 已含 '，，' 防吞音前缀"""
    line = _lines_for("艾玛")[0]
    text = line["text_jp"]
    assert "ヒロちゃん" in text, f"Expected katakana name in: {text}"

    data = await ema_adapter.generate_voice(text)
    assert isinstance(data, bytes)
    assert len(data) > 500

    info = _save_and_validate(data, str(tmp_path), "ema_first")
    assert info["duration_s"] >= 1.5, (
        f"Too short for '{text[:30]}...': {info['duration_s']}s"
    )


@pytest.mark.asyncio
async def test_ema_all_lines(ema_adapter, tmp_path):
    """艾玛所有台词逐一生成验证"""
    lines = _lines_for("艾玛")
    assert len(lines) >= 3, f"Expected at least 3 Emma lines, got {len(lines)}"

    for i, line in enumerate(lines):
        text = line["text_jp"]
        data = await ema_adapter.generate_voice(text)
        info = _save_and_validate(data, str(tmp_path), f"ema_line_{i}")
        assert info["duration_s"] > 0.5, (
            f"Line {i} too short: {info['duration_s']}s — '{text[:30]}...'"
        )


# ═══════════════════════════════════════════════════════════════
# 单句生成 — 希罗
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_hiro_first_line(hiro_adapter, tmp_path):
    """希罗第一句台词"""
    line = _lines_for("希罗")[0]
    text = line["text_jp"]

    data = await hiro_adapter.generate_voice(text)
    assert isinstance(data, bytes)
    assert len(data) > 500

    info = _save_and_validate(data, str(tmp_path), "hiro_first")
    assert info["duration_s"] >= 1.0, (
        f"Too short for '{text[:30]}...': {info['duration_s']}s"
    )


@pytest.mark.asyncio
async def test_hiro_all_lines(hiro_adapter, tmp_path):
    """希罗所有台词逐一生成验证"""
    lines = _lines_for("希罗")
    assert len(lines) >= 2, f"Expected at least 2 Hiro lines, got {len(lines)}"

    for i, line in enumerate(lines):
        text = line["text_jp"]
        data = await hiro_adapter.generate_voice(text)
        info = _save_and_validate(data, str(tmp_path), f"hiro_line_{i}")
        assert info["duration_s"] > 0.5, (
            f"Line {i} too short: {info['duration_s']}s — '{text[:30]}...'"
        )


# ═══════════════════════════════════════════════════════════════
# 与已知正确音频比对（参考：角色 test_data/ 目录内）
# ═══════════════════════════════════════════════════════════════

def _ref_audio_info(character: str, index: int) -> dict | None:
    """读取参考音频的元信息，文件不存在则返回 None"""
    folder = "艾玛" if character == "ema" else "希罗"
    path = _CHAR_BASE / folder / "test_data" / f"{character}_{index:02d}.wav"
    if not path.exists():
        return None
    return validate_wav(str(path))


@pytest.mark.asyncio
async def test_ema_vs_reference_first_line(ema_adapter, tmp_path):
    """艾玛第一句：与参考音频比对时长/峰值在合理区间"""
    ref = _ref_audio_info("ema", 0)
    if ref is None:
        pytest.skip("Reference audio not found")

    line = _lines_for("艾玛")[0]
    data = await ema_adapter.generate_voice(line["text_jp"])
    gen = _save_and_validate(data, str(tmp_path), "ema_vs_ref_0")

    # 时长应在参考的 50%-200% 之间（不同 seed 有波动）
    ratio = gen["duration_s"] / ref["duration_s"]
    assert 0.4 < ratio < 2.5, (
        f"Duration mismatch: gen={gen['duration_s']}s ref={ref['duration_s']}s "
        f"(ratio={ratio:.1%})"
    )
    # 峰值应 > 5000（确保不是静音）
    assert gen["max_sample"] > 5000, (
        f"Generated audio too quiet: peak={gen['max_sample']}"
    )


@pytest.mark.asyncio
async def test_hiro_vs_reference_first_line(hiro_adapter, tmp_path):
    """希罗第一句：与参考音频比对时长/峰值在合理区间"""
    ref = _ref_audio_info("hiro", 1)
    if ref is None:
        pytest.skip("Reference audio not found")

    line = _lines_for("希罗")[0]
    data = await hiro_adapter.generate_voice(line["text_jp"])
    gen = _save_and_validate(data, str(tmp_path), "hiro_vs_ref_1")

    ratio = gen["duration_s"] / ref["duration_s"]
    assert 0.4 < ratio < 2.5, (
        f"Duration mismatch: gen={gen['duration_s']}s ref={ref['duration_s']}s "
        f"(ratio={ratio:.1%})"
    )
    assert gen["max_sample"] > 5000, (
        f"Generated audio too quiet: peak={gen['max_sample']}"
    )


# ═══════════════════════════════════════════════════════════════
# 参数正确性检查
# ═══════════════════════════════════════════════════════════════

def test_ema_adapter_params(ema_adapter):
    """Emma adapter 使用正确的角色参数"""
    p = ema_adapter.params
    assert p["speed_factor"] == 0.95
    assert p["top_k"] == 10
    assert p["top_p"] == 0.9
    assert p["temperature"] == 0.8
    assert p["parallel_infer"] is False
    assert "0101Adv26_Ema012.wav" in str(p["ref_audio_path"])
    # ref_text 完整
    assert "ノアちゃん" in p["prompt_text"]
    assert "白くしたんじゃないかな" in p["prompt_text"]


def test_hiro_adapter_params(hiro_adapter):
    """Hiro adapter 使用正确的角色参数"""
    p = hiro_adapter.params
    assert p["speed_factor"] == 1.05
    assert p["top_k"] == 15
    assert p["top_p"] == 1.0
    assert p["temperature"] == 1.0
    assert p["parallel_infer"] is False
    assert "0205Trial09_Hiro093" in str(p["ref_audio_path"])
    assert "博愛" in p["prompt_text"]


def test_anti_clipping_default():
    """anti_clipping 默认开启"""
    a = GPTSoVITSAdapter(ref_audio_path="/nonexistent.wav", prompt_text="test")
    assert a.anti_clipping is True


def test_model_files_exist():
    """模型文件确实存在"""
    for cfg in [EMA_CONFIG, HIRO_CONFIG]:
        assert os.path.isfile(cfg["gpt_model"]), f"Missing: {cfg['gpt_model']}"
        assert os.path.isfile(cfg["sovits_model"]), f"Missing: {cfg['sovits_model']}"
        assert os.path.isfile(cfg["ref_audio"]), f"Missing: {cfg['ref_audio']}"
