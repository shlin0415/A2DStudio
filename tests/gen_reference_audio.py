"""Generate reference audio from GSV — exact same paths & params as test_dual_port_performance-new-5.py.

Reads voice_setting.txt + ref_setting.txt from Character-voice-example/
(identical to the working origin script). Saves to tmp/ref_audio/.

Usage:
  cd D:/aaa-new/setups/a2d-studio/ref/LingChat
  PYTHONUTF8=1 uv run python tests/gen_reference_audio.py --line 0 --line 1
"""

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Optional, Dict

import httpx

_LOG_DIR = Path(__file__).resolve().parent.parent / "tmp" / "ref_audio"
_JSONL = Path("D:/aaa-new/setups/a2d-studio/ref/try-test/dialogue-server/output/old-real-dialogue-ja-bak3.jsonl")
_VOICE_BASE = Path("D:/aaa-new/setups/a2d-studio/ref/try-test/Character-voice-example")

CHAR_PORTS = {
    "艾玛": {"port": 31801, "folder": "艾玛"},
    "希罗": {"port": 31802, "folder": "希罗"},
}


def parse_kv(text: str) -> Dict[str, str]:
    cfg = {}
    for line in text.strip().split("\n"):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip()
        if (v.startswith("'") and v.endswith("'")) or (v.startswith('"') and v.endswith('"')):
            v = v[1:-1]
        cfg[k] = v
    return cfg


async def set_model(client: httpx.AsyncClient, api_url: str, gpt_path: str, sovits_path: str) -> bool:
    r = await client.get(f"{api_url}/set_gpt_weights", params={"weights_path": gpt_path})
    if r.status_code != 200:
        print(f"  GPT load error: {r.text[:200]}")
        return False
    r = await client.get(f"{api_url}/set_sovits_weights", params={"weights_path": sovits_path})
    if r.status_code != 200:
        print(f"  SoVITS load error: {r.text[:200]}")
        return False
    return True


async def generate(client: httpx.AsyncClient, api_url: str, *,
                   text: str, ref_audio_path: str, ref_text: str,
                   ref_lang: str, text_lang: str = "ja",
                   speed_factor: float = 1.0, top_k: int = 5, top_p: float = 1.0,
                   temperature: float = 1.0) -> Optional[bytes]:
    """Call GSV /tts — exact same payload shape as origin script."""
    ref_lang = ref_lang.lower() if ref_lang.lower() in ["ja","zh","en","yue","ko"] else "auto"
    text_lang = text_lang.lower() if text_lang.lower() in ["ja","zh","en","yue","ko"] else "auto"

    payload = {
        "text": text,
        "text_lang": text_lang,
        "ref_audio_path": str(ref_audio_path),
        "prompt_text": ref_text,
        "prompt_lang": ref_lang,
        "speed_factor": speed_factor,
        "top_k": top_k,
        "top_p": top_p,
        "temperature": temperature,
        "text_split_method": "cut5",
        "media_type": "wav",
    }
    r = await client.post(f"{api_url}/tts", json=payload, timeout=120.0)
    if r.status_code == 200:
        return r.content
    print(f"  TTS error [{r.status_code}]: {r.text[:200]}")
    return None


async def main():
    lines_to_gen = []
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--line" and i + 1 < len(args):
            lines_to_gen.append(int(args[i + 1]))
            i += 2
        else:
            i += 1
    if not lines_to_gen:
        lines_to_gen = [0, 1]

    _LOG_DIR.mkdir(parents=True, exist_ok=True)

    # ── Load JSONL ──
    dialogues = []
    with open(_JSONL, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and (d := json.loads(line)) and "header" not in d:
                dialogues.append(d)

    # ── Load config from Character-voice-example/ (same as origin script) ──
    char_configs = {}
    for name, info in CHAR_PORTS.items():
        gsv_dir = _VOICE_BASE / info["folder"] / "GPT-SoVITS"
        try:
            vs = parse_kv((gsv_dir / "voice_setting.txt").read_text(encoding="utf-8"))
            rs = parse_kv((gsv_dir / vs["DEFAULT_REF_SETTING"]).read_text(encoding="utf-8"))

            ref_audio = gsv_dir / vs["DEFAULT_REF_VOICE"]

            char_configs[name] = {
                **info,
                "gpt_model": str(gsv_dir / vs["GPT_WEIGHT"]),
                "sovits_model": str(gsv_dir / vs["SoVITS_WEIGHT"]),
                "ref_audio": str(ref_audio),
                "ref_text": rs["REF_TEXT"],
                "ref_lang": rs.get("REF_LANGUAGE", "auto"),
                "speed_factor": float(rs["SPEAK_SPEED"]),
                "top_k": int(rs["TOP_K"]),
                "top_p": float(rs["TOP_P"]),
                "temperature": float(rs["TEMPERATURE"]),
            }
            print(f"[{name}] gpt={vs['GPT_WEIGHT']} sovits={vs['SoVITS_WEIGHT']} ref={ref_audio.name} speed={rs['SPEAK_SPEED']} top_k={rs['TOP_K']} top_p={rs['TOP_P']} temp={rs['TEMPERATURE']}")
        except Exception as e:
            print(f"[{name}] CONFIG ERROR: {e}")
            import traceback; traceback.print_exc()
            return

    # ── Clients ──
    clients = {31801: httpx.AsyncClient(timeout=120.0), 31802: httpx.AsyncClient(timeout=120.0)}

    # ── Set models ──
    print("\n[Models]")
    for name, cfg in char_configs.items():
        ok = await set_model(clients[cfg["port"]], f"http://127.0.0.1:{cfg['port']}", cfg["gpt_model"], cfg["sovits_model"])
        print(f"  {name}:{cfg['port']} {'OK' if ok else 'FAIL'}")

    # ── Generate ──
    print(f"\n[Generate] {len(lines_to_gen)} lines")
    results = []
    for idx in lines_to_gen:
        if idx >= len(dialogues):
            print(f"  [{idx}] out of range")
            continue
        d = dialogues[idx]
        name = d["character"]
        cfg = char_configs[name]
        text = d.get("text_jp") or d.get("voice_text") or d["text"]  # origin script uses text_jp
        print(f"  [{idx}] {name}: \"{text[:60]}\" -> ", end="", flush=True)

        audio = await generate(
            clients[cfg["port"]], f"http://127.0.0.1:{cfg['port']}",
            text=text,
            ref_audio_path=cfg["ref_audio"],
            ref_text=cfg["ref_text"],
            ref_lang=cfg["ref_lang"],
            text_lang="ja",
            speed_factor=cfg["speed_factor"],
            top_k=cfg["top_k"],
            top_p=cfg["top_p"],
            temperature=cfg["temperature"],
        )
        if audio:
            out = _LOG_DIR / f"ref_{name}_{idx:03d}.wav"
            out.write_bytes(audio)
            print(f"{len(audio)}b -> {out.name}")
            results.append({"idx": idx, "character": name, "text": text, "file": str(out), "size": len(audio)})
        else:
            print("FAILED")

    for c in clients.values():
        await c.aclose()

    print(f"\n[Done] {len(results)}/{len(lines_to_gen)} -> {_LOG_DIR}")
    for r in results:
        print(f"  {Path(r['file']).name}  ({r['size']}b)  [{r['character']}] {r['text'][:50]}")


if __name__ == "__main__":
    asyncio.run(main())
