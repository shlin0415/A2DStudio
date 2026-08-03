"""Script-related data models"""
import uuid
from dataclasses import dataclass, field
from typing import Literal, Optional


@dataclass
class TextOverlay:
    """Screen-oriented text overlay with percentage coordinates (0-100).

    Percentage coords auto-adapt to any canvas resolution at render time
    (pixel_x = x% * canvas_width / 100).
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    text: str = ""
    x: float = 50.0  # percentage 0-100, relative to canvas
    y: float = 30.0
    width: float = 0  # 0 = auto
    font_size: int = 24
    color: str = "#ffffff"
    opacity: float = 1.0
    z: int = 0  # z-index for layering


@dataclass
class LineOverlay:
    line_id: str = ""
    character_id: int = 0
    ref_audio_path: Optional[str] = None
    gsv_params: Optional[dict] = None
    sprite_positions: Optional[dict] = None
    background: Optional[str] = None
    text_overlays: list[TextOverlay] = field(default_factory=list)
    image_overlays: list[dict] = field(default_factory=list)
    # Each image_overlay: {id, path, x, y, w, h, opacity, z}
    bgm: str = ""
    bgm_volume: float = 1.0
    bgm_loop: bool = True


@dataclass
class ScriptLine:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    index: int = 0
    generation_epoch: int = 0
    stage_id: str = ""  # NEW: associated Stage identifier

    speaker: Literal["ema", "hiro", "narrator"] = "ema"
    emotion: str = ""
    display_text: str = ""
    tts_text: str = ""
    action: str = ""  # （动作描述）extracted from LLM output, separate from display_text
    raw_text: str = ""  # LLM original line preserved for KV-cache-friendly history

    state: Literal[
        "draft", "approved", "tts_pending", "tts_ready", "playing", "played", "invalidated"
    ] = "draft"

    audio_path: Optional[str] = None
    original_audio_path: Optional[str] = None
    overlay: Optional[LineOverlay] = None
    parent_line_id: Optional[str] = None


@dataclass
class Stage:
    """Stage container — groups ScriptLines into narrative phases."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    title: str = ""
    line_ids: list[str] = field(default_factory=list)
    default_background: str = ""
    order: int = 0  # sorting index


@dataclass
class SceneConfig:
    scene_description: str = ""
    dialogue_style: str = "自由对话"  # "自由对话" | "同人演绎" | "知识讨论" | "睡前轻语"
    reference_material: str | None = None


# ═══════════════════════════════════════════════════════════════
# A2D Studio — WebSocket message types for script-editor protocol
# ═══════════════════════════════════════════════════════════════


@dataclass
class WSMessage:
    """Base WS message envelope."""
    type: str


@dataclass
class StartPayload:
    topic: str | None = None


@dataclass
class StartMessage(WSMessage):
    type: str = "a2d.start"
    payload: StartPayload | None = None


@dataclass
class EditEntry:
    id: str
    text: str


@dataclass
class ContinuePayload:
    generation_id: str
    edits: list[EditEntry] | None = None


@dataclass
class ContinueMessage(WSMessage):
    type: str = "a2d.continue"
    payload: ContinuePayload | None = None


@dataclass
class RetryPayload:
    generation_id: str


@dataclass
class RetryMessage(WSMessage):
    type: str = "a2d.retry"
    payload: RetryPayload | None = None


@dataclass
class RegenerateTTSPayload:
    id: str
    text: str


@dataclass
class RegenerateTTSMessage(WSMessage):
    type: str = "a2d.regenerate_tts"
    payload: RegenerateTTSPayload | None = None


@dataclass
class StatusPayload:
    phase: Literal["thinking", "translating", "synthesizing", "paused", "error"]


@dataclass
class StatusMessage(WSMessage):
    type: str = "status"
    payload: StatusPayload | None = None


@dataclass
class ScriptLinePayload:
    id: str
    speaker: str  # "ema" | "hiro"
    display_text: str
    tts_text: str
    emotion: str = ""
    index: int = 0


@dataclass
class ScriptLineMessage(WSMessage):
    type: str = "script_line"
    payload: ScriptLinePayload | None = None


@dataclass
class TTSReadyPayload:
    id: str
    audio_path: str


@dataclass
class TTSReadyMessage(WSMessage):
    type: str = "tts_ready"
    payload: TTSReadyPayload | None = None


@dataclass
class ErrorPayload:
    error_type: str  # "llm_timeout" | "llm_api_error" | "format_error" | "tts_error" | "network_error" | "unknown"
    message: str
    detail: str
    generation_id: str
    retry_count: int
    max_retries: int


@dataclass
class ErrorMessage(WSMessage):
    type: str = "error"
    payload: ErrorPayload | None = None
