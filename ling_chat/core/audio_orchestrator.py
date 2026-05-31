"""音频三级获取链 — 原声 → 缓存 → 生成

环境变量开关:
  A2D_ENABLE_REF_AUDIO=false   → 跳过 Tier 1（游戏原声）
  A2D_ENABLE_AUDIO_CACHE=false → 跳过 Tier 2（缓存复用）
  两个都关 → 直接 Tier 3（每次全新生成）
"""
import os
from dataclasses import dataclass

from ling_chat.core.audio_library import AudioLibraryIndex
from ling_chat.core.cache_manager import CacheManager
from ling_chat.core.TTS.gsv_adapter import GPTSoVITSAdapter
from ling_chat.core.logger import logger


@dataclass
class AudioResult:
    audio_path: str
    source: str  # "ref" | "cache" | "generated"


async def get_best_audio(
    character: str,
    tts_text: str,
    display_text: str,
    gsv_adapter: GPTSoVITSAdapter,
    audio_index: AudioLibraryIndex | None = None,
    cache_manager: CacheManager | None = None,
    gsv_params: dict | None = None,
) -> AudioResult:
    """
    三级音频获取：原声 > 缓存 > 实时生成。

    返回 AudioResult(audio_path, source)。
    source: "ref" = 游戏原声匹配, "cache" = 过往生成复用, "generated" = 新建。
    """
    params = gsv_params or {}

    # ── Tier 1: 游戏原声 ──
    if (
        os.environ.get("A2D_ENABLE_REF_AUDIO", "true").lower() == "true"
        and audio_index is not None
    ):
        try:
            results = audio_index.search(character, display_text, limit=1)
            if results:
                path = results[0]["file_path"]
                if os.path.exists(path):
                    logger.debug(f"Tier 1 (ref) hit: {path}")
                    return AudioResult(audio_path=path, source="ref")
                else:
                    logger.warning(f"Tier 1 file missing: {path}")
        except Exception as e:
            logger.warning(f"Tier 1 search failed (non-fatal): {e}")

    # ── Tier 2: 缓存 ──
    if (
        os.environ.get("A2D_ENABLE_AUDIO_CACHE", "true").lower() == "true"
        and cache_manager is not None
    ):
        try:
            hash_str = cache_manager._compute_hash(character, tts_text, params)
            row = cache_manager.conn.execute(
                "SELECT file_path FROM cache_entries WHERE hash = ?", [hash_str]
            ).fetchone()
            if row and os.path.exists(row["file_path"]):
                logger.debug(f"Tier 2 (cache) hit: {hash_str[:8]}")
                return AudioResult(audio_path=row["file_path"], source="cache")
            elif row:
                # 脏记录：文件被手动删除，自愈清理
                logger.warning(f"Tier 2 stale record cleaned: {hash_str[:8]}")
                cache_manager.conn.execute(
                    "DELETE FROM cache_entries WHERE hash = ?", [hash_str]
                )
                cache_manager.conn.commit()
        except Exception as e:
            logger.warning(f"Tier 2 cache lookup failed (non-fatal): {e}")

    # ── Tier 3: 实时生成 ──
    logger.debug("Tier 3: generating via GSV...")
    path = await cache_manager.get_or_generate(
        character, tts_text,
        generate_fn=lambda t: gsv_adapter.generate_voice(t),
        params=params,
    )
    return AudioResult(audio_path=path, source="generated")
