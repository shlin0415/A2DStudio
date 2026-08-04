"""
A2D Studio: pure persistence logic (no FastAPI dependency).

Separated from a2d_save.py so it can be unit-tested without triggering the
env's FastAPI 0.104.1 / Starlette 1.3.1 version mismatch (which breaks
TestClient). The route handlers in a2d_save.py call into this module.
"""
import os
import shutil
from pathlib import Path
from typing import Any

from ling_chat.core.logger import logger
from ling_chat.utils.runtime_path import temp_path, user_data_path

# Persistent base dir for A2D saves — anchored to user_data_path so exports survive
# machine migration and are independent of backend CWD (NOT the ephemeral temp_path).
SAVE_BASE_DIR = user_data_path / "a2d_saves"


def temp_audio_dir() -> Path:
    return Path(os.environ.get("TEMP_VOICE_DIR", temp_path / "audio"))


def persist_envelope(envelope: dict[str, Any], save_dir: Path, audio_dir: Path) -> int:
    """Copy WAVs + rewrite audio_paths in-place. Returns count copied.

    On-disk format: /audio/a2d_{line_id}.wav (core.py L933/939).
    Destination + rewrite URL + serve route all use the bare line_id.
    """
    temp_audio = temp_audio_dir()
    lines = envelope.get("script", {}).get("lines", [])
    copied = 0
    for line in lines:
        audio_path = line.get("audio_path") or ""
        if audio_path.startswith("/audio/a2d_") and audio_path.endswith(".wav"):
            audio_filename = audio_path.rsplit("/", 1)[-1]            # "a2d_{line_id}.wav"
            line_id = audio_filename[4:-4]                           # strip "a2d_" + ".wav"
            src = temp_audio / audio_filename                         # correct on-disk path
            dst = audio_dir / f"{line_id}.wav"                        # match rewrite URL + serve route
            if src.exists():
                try:
                    shutil.copy2(src, dst)
                    copied += 1
                except Exception as e:
                    logger.warning(f"复制音频失败 {src} -> {dst}: {e}")
            # Rewrite to the persistent-serving route regardless of copy success.
            line["audio_path"] = f"/api/a2d/save/audio/{save_dir.name}/{line_id}.wav"
    return copied
