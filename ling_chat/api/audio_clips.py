"""音频库搜索 API"""
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
import os

from ling_chat.core.audio_library import AudioLibraryIndex
from ling_chat.core.logger import logger

router = APIRouter(prefix="/api/v1/audio-clips", tags=["audio-clips"])

# 全局索引实例（由 startup 或懒加载初始化）
_audio_index: AudioLibraryIndex | None = None


def init_audio_index(index: AudioLibraryIndex):
    global _audio_index
    _audio_index = index


@router.get("/search")
async def search_clips(
    character: str = Query(..., description="角色标识"),
    query: str = Query(..., description="搜索关键词"),
    limit: int = Query(20, ge=1, le=100),
):
    if _audio_index is None:
        raise HTTPException(503, "音频库索引未初始化")
    results = _audio_index.search(character, query, limit)
    return {"results": results, "total": len(results)}


@router.get("/preview/{clip_id}")
async def preview_clip(clip_id: int):
    if _audio_index is None:
        raise HTTPException(503, "音频库索引未初始化")
    clip = _audio_index.get_clip(clip_id)
    if not clip:
        raise HTTPException(404, "音频片段未找到")
    path = clip["file_path"]
    if not os.path.exists(path):
        raise HTTPException(404, f"音频文件不存在: {path}")
    return FileResponse(path, media_type="audio/ogg")
