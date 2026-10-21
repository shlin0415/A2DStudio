import os
import re
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from ling_chat.core.a2d_project_assets import resolve_reference_audio_path
from ling_chat.core.service_manager import service_manager

router = APIRouter()
ROLE_KEY_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


@router.get("/api/a2d/project-assets/reference-audio/{speaker_key}")
async def get_project_reference_audio(speaker_key: str) -> FileResponse:
    """Serve the active local GSV reference WAV for one A2D speaker key."""
    if not ROLE_KEY_PATTERN.fullmatch(speaker_key):
        raise HTTPException(status_code=400, detail="说话者键格式无效")

    ai_service = service_manager.ai_service
    if ai_service is None:
        raise HTTPException(status_code=503, detail="A2D 服务尚未初始化")

    session = ai_service.a2d_session
    effective_speaker = speaker_key
    if speaker_key == "narrator":
        effective_speaker = session.narrator_voice_key or ""
    character_config = session.characters.get(effective_speaker)
    if character_config is None or character_config.game_role is None:
        raise HTTPException(status_code=404, detail="找不到该说话者的本机语音配置")

    voice_maker: Any = character_config.game_role.voice_maker
    gsv_adapter = voice_maker.tts_provider.gsv_adapter
    if gsv_adapter is None:
        raise HTTPException(status_code=404, detail="该说话者没有可用的 GSV 参考音频")

    reference_path = gsv_adapter.params.get("ref_audio_path")
    character_root = voice_maker.character_path
    try:
        resolved_path = resolve_reference_audio_path(
            reference_path,
            character_root,
            bool(os.environ.get("GPT_SOVITS_REF_AUDIO", "").strip()),
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="本机角色参考 WAV 不存在") from None
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from None

    return FileResponse(resolved_path, media_type="audio/wav")
