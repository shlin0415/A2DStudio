"""音频库搜索 API — 懒加载，不侵入 main.py

初始化由会话层驱动：调用方从 settings.yml 读取活跃角色的音频库路径，
调 init_audio_index() 按需加载。API 层不扫描文件系统、不硬编码角色。
"""
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
import os

from ling_chat.core.audio_library import AudioLibraryIndex
from ling_chat.core.logger import logger

router = APIRouter(prefix="/api/v1/audio-clips", tags=["audio-clips"])

_audio_index: AudioLibraryIndex | None = None


def init_audio_index(character_configs: list[dict]) -> int:
    """
    由会话层调用，按需加载活跃角色的音频库。

    character_configs 每条记录需包含以下字段（均直接取自 settings.yml）：
      - script_role_key (str, 必填): 内部角色标识，用于搜索匹配
      - character_folder (str, 必填): 展示名，仅用于日志输出
      - list_path (str, 必填): .list 文件完整路径
      - base_dir (str, 必填): 音频文件所在目录

    示例:
      [{"script_role_key": "ema", "character_folder": "艾玛",
        "list_path": "D:/.../ema.list", "base_dir": "D:/.../ema_audio"}]

    日志输出如: 音频库初始化: ema(艾玛) 6234条, hiro(希罗) 5812条, 共2角色
    返回加载的音频片段总数。
    """
    global _audio_index
    _audio_index = AudioLibraryIndex()
    total = 0
    for cfg in character_configs:
        n = _audio_index.load_list(
            cfg["list_path"], cfg["script_role_key"], cfg["base_dir"]
        )
        logger.info(
            f"  {cfg['script_role_key']}({cfg['character_folder']}): {n} 条"
        )
        total += n
    logger.info(
        f"音频库初始化完成: {total} 条, {len(character_configs)} 角色"
    )
    return total


def _get_audio_index() -> AudioLibraryIndex | None:
    return _audio_index


@router.get("/search")
async def search_clips(
    character: str = Query(..., description="角色标识 (script_role_key)"),
    query: str = Query(..., description="搜索关键词"),
    limit: int = Query(20, ge=1, le=100),
):
    idx = _get_audio_index()
    if idx is None:
        raise HTTPException(503, "音频库索引未初始化")
    results = idx.search(character, query, limit)
    return {"results": results, "total": len(results)}


@router.get("/preview/{clip_id}")
async def preview_clip(clip_id: int):
    idx = _get_audio_index()
    if idx is None:
        raise HTTPException(503, "音频库索引未初始化")
    clip = idx.get_clip(clip_id)
    if not clip:
        raise HTTPException(404, "音频片段未找到")
    path = clip["file_path"]
    if not os.path.exists(path):
        raise HTTPException(404, f"音频文件不存在: {path}")
    return FileResponse(path, media_type="audio/ogg")
