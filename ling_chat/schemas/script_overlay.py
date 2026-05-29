"""Script-related data models"""
import uuid
from dataclasses import dataclass, field
from typing import Literal, Optional


@dataclass
class TextOverlayBox:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    content: str = ""
    content_type: Literal["text", "code", "formula"] = "text"
    position: dict = field(default_factory=lambda: {"x": 50, "y": 30})
    style: dict = field(default_factory=lambda: {"font_size": 14, "color": "#ffffff"})
    start_line_id: str = ""
    end_line_id: str = ""


@dataclass
class LineOverlay:
    line_id: str = ""
    character_id: int = 0
    ref_audio_path: Optional[str] = None
    gsv_params: Optional[dict] = None
    sprite_positions: Optional[dict] = None
    background: Optional[str] = None
    text_overlays: list[TextOverlayBox] = field(default_factory=list)


@dataclass
class ScriptLine:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    index: int = 0
    generation_epoch: int = 0

    speaker: Literal["ema", "hiro", "narrator"] = "ema"
    display_text: str = ""
    tts_text: str = ""

    state: Literal[
        "draft", "approved", "tts_pending", "tts_ready", "playing", "played", "invalidated"
    ] = "draft"

    audio_path: Optional[str] = None
    original_audio_path: Optional[str] = None
    overlay: Optional[LineOverlay] = None
    parent_line_id: Optional[str] = None


@dataclass
class SceneConfig:
    scene_description: str = ""
    dialogue_style: str = "自由对话"  # "自由对话" | "同人演绎" | "知识讨论" | "睡前轻语"
    reference_material: str | None = None
