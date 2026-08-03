"""Session runtime orchestrator — coordinates LLM / TTS / Playback lifecycles for A2D Studio."""
import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from ling_chat.core.logger import logger
from ling_chat.schemas.script_overlay import CURRENT_VERSION, LineOverlay, SceneConfig, ScriptLine, Stage, TextOverlay


@dataclass
class CharacterConfig:
    """Per-character configuration loaded from settings.yml."""
    script_role_key: str          # "ema" | "hiro"
    character_folder: str         # "艾玛" | "希罗"
    voice_language: str = "ja"    # TTS 语音语言 (ja/zh/en)，来自 settings.yml voice_language
    display_language: str = "zh"  # 前端显示文本语言 (ja/zh/en)
    tts_type: str = "gsv"
    game_role: Any = None         # Optional[GameRole] — lazy-init for TTS reuse


@dataclass
class BudgetStatus:
    remaining_tokens: int = 0
    remaining_cost_yuan: float = 0.0
    remaining_seconds: int = 0
    can_continue: bool = True


class SessionRuntime:
    """Coordinates LLM / TTS / Playback lifecycles with epoch-based invalidation."""

    def __init__(self, characters: dict[str, "CharacterConfig"] | None = None):
        self.session_id: str = str(uuid.uuid4())
        self.generation_epoch: int = 0
        self.mode: str = "auto"  # "auto" | "script" | "asmr"

        # Character configs: script_role_key → CharacterConfig
        self.characters: dict[str, CharacterConfig] = characters or {}

        # Queues
        self.sentence_queue: asyncio.Queue = asyncio.Queue()
        self.audio_queue: asyncio.Queue = asyncio.Queue()

        # State
        self.paused: bool = False
        self.stopped: bool = False
        self.batch_size: int = 1
        self.last_batch_count: int = 0  # lines generated in last _generate_and_synthesize call
        self.last_raw_llm_response: str = ""  # verbatim LLM output from most recent a2d_generate_next

        # Script data
        self.script_lines: list[ScriptLine] = []
        self.stages: list[Stage] = []  # NEW: stage containers
        self.scene_config: SceneConfig = SceneConfig()

        # Active LLM stream task (cancellable)
        self._active_llm_task: Optional[asyncio.Task] = None

        # Budget
        self.budget = BudgetStatus()

    # ── Continue / Edit ──────────────────────────────────────────

    async def handle_continue(
        self, generation_id: str, edits: list[dict] | None = None
    ) -> int:
        """User clicks continue → cancel current stream + apply edits + new epoch."""
        self.generation_epoch += 1

        # Cancel current LLM stream if active
        if self._active_llm_task and not self._active_llm_task.done():
            self._active_llm_task.cancel()
            try:
                await self._active_llm_task
            except asyncio.CancelledError:
                pass
            self._active_llm_task = None

        # Apply edits: discard lines after first modified line
        if edits:
            self._apply_edits(edits)

        # Clear queues
        while not self.sentence_queue.empty():
            self.sentence_queue.get_nowait()

        self.paused = False
        logger.info(
            f"SessionRuntime: epoch={self.generation_epoch}, continuing..."
        )
        return self.generation_epoch

    def _apply_edits(self, modified_lines: list[dict]):
        """Apply user edits from frontend [{id, text}] format to script_lines.

        Frontend sends edits as a list of {id, text} dicts. This method:
        1. Finds the first modified line index by id lookup
        2. Truncates script_lines to that index (discarding subsequent lines)
        3. Appends edited lines, looking up the original speaker by id
        """
        if not modified_lines:
            return

        # Build maps for speaker and emotion preservation from original lines
        speaker_map = {ln.id: ln.speaker for ln in self.script_lines}
        emotion_map = {ln.id: ln.emotion for ln in self.script_lines}

        idx_entries = [
            self._find_line_index(ln.get("id", ""))
            for ln in modified_lines
            if ln.get("id")
        ]
        if not idx_entries:
            # All edits are new lines (no existing ID) — append after current script
            first_modified_idx = len(self.script_lines)
        else:
            first_modified_idx = min(idx_entries)

        # Truncate from first modified index
        self.script_lines = self.script_lines[:first_modified_idx]

        # Clean up dangling stage.line_ids references (AC-1.1)
        valid_ids = {l.id for l in self.script_lines}
        for stage in self.stages:
            stage.line_ids = [lid for lid in stage.line_ids if lid in valid_ids]

        # Append modified lines
        for i, line_data in enumerate(modified_lines):
            line_id = line_data.get("id", "")
            new_line = ScriptLine(
                index=first_modified_idx + i,
                generation_epoch=self.generation_epoch,
                speaker=speaker_map.get(line_id, "ema"),
                emotion=emotion_map.get(line_id, ""),  # preserve original emotion
                display_text=line_data.get("text", ""),
                tts_text="",  # cleared — triggers translation before TTS
                raw_text="",  # user-edited: can't preserve KV cache
                state="approved",
            )
            self.script_lines.append(new_line)

        logger.info(
            f"SessionRuntime: applied {len(modified_lines)} edit(s), "
            f"script_lines truncated to {len(self.script_lines)} entries"
        )

    def _find_line_index(self, line_id: str) -> int:
        for i, line in enumerate(self.script_lines):
            if line.id == line_id:
                return i
        return len(self.script_lines)

    # ── Line management ──────────────────────────────────────────

    def add_line(self, line: ScriptLine):
        line.index = len(self.script_lines)
        line.generation_epoch = self.generation_epoch
        self.script_lines.append(line)

    def invalidate_downstream(self, line_id: str):
        """Mark all lines after the given line as invalidated."""
        found = False
        for line in self.script_lines:
            if found:
                if line.generation_epoch == self.generation_epoch:
                    line.state = "invalidated"
            if line.id == line_id:
                found = True

    # ── Stage management ─────────────────────────────────────────

    def assign_line_to_stage(self, line_id: str, stage_id: str) -> None:
        """Associate a ScriptLine with a Stage (weak reference, no strict sync).

        AC-1 Negative: prevents same line from being assigned to multiple stages.
        """
        stage = self.get_stage(stage_id)
        if stage is None:
            logger.warning(f"Stage {stage_id} not found for line {line_id}")
            return
        # Remove line from any other stage first (prevent multi-stage assignment)
        for s in self.stages:
            if line_id in s.line_ids:
                s.line_ids.remove(line_id)
        for line in self.script_lines:
            if line.id == line_id:
                line.stage_id = stage_id
                if line_id not in stage.line_ids:
                    stage.line_ids.append(line_id)
                return

    def delete_stage(self, stage_id: str) -> None:
        """Remove a stage and clear associated ScriptLine.stage_id references."""
        self.stages = [s for s in self.stages if s.id != stage_id]
        for line in self.script_lines:
            if line.stage_id == stage_id:
                line.stage_id = ""

    def get_stage(self, stage_id: str) -> Stage | None:
        for s in self.stages:
            if s.id == stage_id:
                return s
        return None

    def get_line_stage(self, line_id: str) -> Stage | None:
        """Look up a line's stage by its stage_id (weak association)."""
        line = next((l for l in self.script_lines if l.id == line_id), None)
        if line and line.stage_id:
            return self.get_stage(line.stage_id)
        return None

    def get_background_for_line(self, line_id: str) -> str:
        """Resolve background with priority: line > stage > global default."""
        line = next((l for l in self.script_lines if l.id == line_id), None)
        if line and line.overlay and line.overlay.background:
            return line.overlay.background
        stage = self.get_line_stage(line_id) if line else None
        if stage and stage.default_background:
            return stage.default_background
        return ""

    def to_dict(self) -> dict:
        """Serialize session to L1 JSON-compatible dict."""
        return {
            "version": 1,
            "session_id": self.session_id,
            "generation_epoch": self.generation_epoch,
            "mode": self.mode,
            "batch_size": self.batch_size,
            "scene_config": {
                "scene_description": self.scene_config.scene_description,
                "dialogue_style": self.scene_config.dialogue_style,
                "reference_material": self.scene_config.reference_material,
            },
            "stages": [
                {
                    "id": s.id,
                    "title": s.title,
                    "line_ids": s.line_ids,
                    "default_background": s.default_background,
                    "order": s.order,
                }
                for s in self.stages
            ],
            "script_lines": [
                {
                    "id": l.id,
                    "index": l.index,
                    "generation_epoch": l.generation_epoch,
                    "stage_id": l.stage_id,
                    "speaker": l.speaker,
                    "emotion": l.emotion,
                    "display_text": l.display_text,
                    "tts_text": l.tts_text,
                    "action": l.action,
                    "raw_text": l.raw_text,
                    "state": l.state,
                    "audio_path": l.audio_path,
                    "original_audio_path": l.original_audio_path,
                    "parent_line_id": l.parent_line_id,
                    "overlay": {
                        "line_id": l.overlay.line_id if l.overlay else "",
                        "character_id": l.overlay.character_id if l.overlay else 0,
                        "ref_audio_path": l.overlay.ref_audio_path if l.overlay else None,
                        "gsv_params": l.overlay.gsv_params if l.overlay else None,
                        "sprite_positions": l.overlay.sprite_positions if l.overlay else None,
                        "background": l.overlay.background if l.overlay else None,
                        "text_overlays": [
                            {
                                "id": t.id,
                                "text": t.text,
                                "x": t.x,
                                "y": t.y,
                                "width": t.width,
                                "font_size": t.font_size,
                                "color": t.color,
                                "opacity": t.opacity,
                                "z": t.z,
                            }
                            for t in (l.overlay.text_overlays if l.overlay else [])
                        ],
                        "image_overlays": l.overlay.image_overlays if l.overlay else [],
                        "bgm": l.overlay.bgm if l.overlay else "",
                        "bgm_volume": l.overlay.bgm_volume if l.overlay else 1.0,
                        "bgm_loop": l.overlay.bgm_loop if l.overlay else True,
                    },
                }
                for l in self.script_lines
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SessionRuntime":
        """Deserialize session from L1 JSON dict (with backward compat for v0)."""
        version = data.get("version", 0)
        if version > CURRENT_VERSION:
            raise ValueError(f"Unsupported session format version: {version} (max {CURRENT_VERSION})")
        runtime = cls()
        runtime.session_id = data.get("session_id", runtime.session_id)
        runtime.generation_epoch = data.get("generation_epoch", 0)
        runtime.mode = data.get("mode", "auto")
        runtime.batch_size = data.get("batch_size", 1)

        # Scene config
        sc = data.get("scene_config", {})
        runtime.scene_config = SceneConfig(
            scene_description=sc.get("scene_description", ""),
            dialogue_style=sc.get("dialogue_style", "自由对话"),
            reference_material=sc.get("reference_material"),
        )

        # Stages (v0 compat: no stages → create default)
        for s_data in data.get("stages", []):
            stage = Stage(
                id=s_data.get("id", str(uuid.uuid4())),
                title=s_data.get("title", ""),
                line_ids=s_data.get("line_ids", []),
                default_background=s_data.get("default_background", ""),
                order=s_data.get("order", 0),
            )
            runtime.stages.append(stage)

        # v0 backward compat: if no stages, create a default one
        if not runtime.stages and data.get("script_lines"):
            default_stage = Stage(title="默认阶段", order=0)
            runtime.stages.append(default_stage)

        # Script lines
        for l_data in data.get("script_lines", []):
            overlay_data = l_data.get("overlay") or {}
            overlay = LineOverlay(
                line_id=overlay_data.get("line_id", ""),
                character_id=overlay_data.get("character_id", 0),
                ref_audio_path=overlay_data.get("ref_audio_path"),
                gsv_params=overlay_data.get("gsv_params"),
                sprite_positions=overlay_data.get("sprite_positions"),
                background=overlay_data.get("background"),
                text_overlays=[
                    TextOverlay(
                        id=t.get("id", str(uuid.uuid4())),
                        text=t.get("text", ""),
                        x=t.get("x", 50.0),
                        y=t.get("y", 30.0),
                        width=t.get("width", 0),
                        font_size=t.get("font_size", 24),
                        color=t.get("color", "#ffffff"),
                        opacity=t.get("opacity", 1.0),
                        z=t.get("z", 0),
                    )
                    for t in overlay_data.get("text_overlays", [])
                ],
                image_overlays=overlay_data.get("image_overlays", []),
                bgm=overlay_data.get("bgm", ""),
                bgm_volume=overlay_data.get("bgm_volume", 1.0),
                bgm_loop=overlay_data.get("bgm_loop", True),
            )
            line = ScriptLine(
                id=l_data.get("id", str(uuid.uuid4())),
                index=l_data.get("index", 0),
                generation_epoch=l_data.get("generation_epoch", 0),
                stage_id=l_data.get("stage_id", ""),
                speaker=l_data.get("speaker", "ema"),
                emotion=l_data.get("emotion", ""),
                display_text=l_data.get("display_text", ""),
                tts_text=l_data.get("tts_text", ""),
                action=l_data.get("action", ""),
                raw_text=l_data.get("raw_text", ""),
                state=l_data.get("state", "draft"),
                audio_path=l_data.get("audio_path"),
                original_audio_path=l_data.get("original_audio_path"),
                parent_line_id=l_data.get("parent_line_id"),
                overlay=overlay,
            )
            runtime.script_lines.append(line)
            # v0 compat: assign to default stage
            if not line.stage_id and runtime.stages:
                line.stage_id = runtime.stages[0].id
                runtime.stages[0].line_ids.append(line.id)

        return runtime

    # ── Scene config ─────────────────────────────────────────────

    def update_scene(self, description: str, style: str, material: str | None):
        self.scene_config = SceneConfig(
            scene_description=description,
            dialogue_style=style,
            reference_material=material,
        )

    def build_scene_prompt_suffix(self) -> str:
        """Convert scene config into a suffix to append to the system prompt."""
        cfg = self.scene_config
        parts = [f"当前场景：{cfg.scene_description}"]
        if cfg.reference_material:
            parts.append(f"参考材料：{cfg.reference_material}")

        style_prompts = {
            "自由对话": "",
            "同人演绎": "请围绕参考材料中的故事内容展开对话，忠实还原原作风格与氛围。如有参考材料中的人物，请扮演之。",
            "知识讨论": "请围绕参考材料中的知识点展开讨论，用通俗易懂的方式讲解，可以将抽象概念融入日常对话中。",
            "睡前轻语": "请用轻声、缓慢、亲密的语气对话，声音像是在耳边低语，适合睡前聆听。减少激烈情绪波动。",
        }
        instruction = style_prompts.get(cfg.dialogue_style, "")
        if instruction:
            parts.append(instruction)
        return "\n".join(parts)

    # ── Lifecycle ────────────────────────────────────────────────

    def stop(self):
        self.stopped = True
        if self._active_llm_task and not self._active_llm_task.done():
            self._active_llm_task.cancel()
