"""
A2D Studio: per-save export persistence (Option B).

On export, the frontend sends the .a2d.json envelope. This endpoint:
  - assigns a save_id
  - writes the snapshot to data/saves/{save_id}/snapshot.json
  - copies per-line WAVs from the temp audio dir to data/saves/{save_id}/audio/
  - rewrites audio_paths to /api/a2d/save/audio/{save_id}/{line_id}.wav
  - serves those WAVs via GET /api/a2d/save/audio/{save_id}/{line_id}.wav

This makes exports survive temp cleanup and machine migration (DEC-1 = Option B).
"""
import os
import shutil
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from ling_chat.core.logger import logger
from ling_chat.utils.runtime_path import temp_path

router = APIRouter()

# Persistent base dir for A2D saves (NOT the ephemeral temp_path).
SAVE_BASE_DIR = Path("data/saves")


class A2DSaveRequest(BaseModel):
    envelope: dict[str, Any]


def _temp_audio_dir() -> Path:
    return Path(os.environ.get("TEMP_VOICE_DIR", temp_path / "audio"))


@router.post("/api/a2d/save")
async def save_a2d_envelope(req: A2DSaveRequest):
    """Persist an export envelope + copy WAVs into a per-save audio dir."""
    envelope = req.envelope
    save_id = str(uuid.uuid4())[:12]
    save_dir = SAVE_BASE_DIR / save_id
    audio_dir = save_dir / "audio"
    try:
        audio_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"创建保存目录失败: {e}")

    # Rewrite audio_paths + copy WAVs.
    temp_audio = _temp_audio_dir()
    lines = envelope.get("script", {}).get("lines", [])
    copied = 0
    for line in lines:
        audio_path = line.get("audio_path") or ""
        # Only rewrite paths pointing at the temp /audio mount.
        if audio_path.startswith("/audio/a2d_") and audio_path.endswith(".wav"):
            line_id = audio_path.rsplit("/", 1)[-1].replace(".wav", "")
            src = temp_audio / f"a2d_{line_id}.wav"
            dst = audio_dir / f"{line_id}.wav"
            if src.exists():
                try:
                    shutil.copy2(src, dst)
                    copied += 1
                except Exception as e:
                    logger.warning(f"复制音频失败 {src} -> {dst}: {e}")
            # Rewrite to the persistent-serving route regardless of copy success.
            line["audio_path"] = f"/api/a2d/save/audio/{save_id}/{line_id}.wav"

    # Write the (rewritten) snapshot.
    snapshot_path = save_dir / "snapshot.json"
    try:
        import json
        snapshot_path.write_text(json.dumps(envelope, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"保存快照失败: {e}")

    logger.info(f"A2D save {save_id}: {len(lines)} lines, {copied} audio files copied")
    return JSONResponse({"ok": True, "save_id": save_id, "url": f"/api/a2d/save/{save_id}"})


@router.get("/api/a2d/save/audio/{save_id}/{line_id}.wav")
async def serve_save_audio(save_id: str, line_id: str):
    """Serve a per-save WAV file."""
    # Sanitize path components to prevent traversal.
    if ".." in save_id or "/" in save_id or ".." in line_id or "/" in line_id:
        raise HTTPException(status_code=400, detail="无效的路径参数")
    audio_file = SAVE_BASE_DIR / save_id / "audio" / f"{line_id}.wav"
    if not audio_file.exists():
        raise HTTPException(status_code=404, detail="音频文件不存在")
    response = FileResponse(audio_file, media_type="audio/wav")
    response.headers["Cache-Control"] = "public, max-age=86400"
    return response


@router.get("/api/a2d/save/{save_id}")
async def get_save_snapshot(save_id: str):
    """Return the stored snapshot JSON (for re-download / share)."""
    if ".." in save_id or "/" in save_id:
        raise HTTPException(status_code=400, detail="无效的 save_id")
    snapshot_path = SAVE_BASE_DIR / save_id / "snapshot.json"
    if not snapshot_path.exists():
        raise HTTPException(status_code=404, detail="保存不存在")
    try:
        import json
        return JSONResponse(json.loads(snapshot_path.read_text(encoding="utf-8")))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读取快照失败: {e}")
