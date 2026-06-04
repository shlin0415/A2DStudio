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
    phase: Literal["thinking", "synthesizing", "paused", "error"]


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
    index: int


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
