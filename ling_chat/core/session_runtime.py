"""Session runtime orchestrator — coordinates LLM / TTS / Playback lifecycles for A2D Studio."""
import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Optional

from ling_chat.core.logger import logger
from ling_chat.schemas.script_overlay import SceneConfig, ScriptLine


@dataclass
class CharacterConfig:
    """Per-character configuration loaded from settings.yml."""
    script_role_key: str          # "ema" | "hiro"
    character_folder: str         # "艾玛" | "希罗"
    voice_language: str = "ja"    # TTS 语音语言 (ja/zh/en)，来自 settings.yml voice_language
    display_language: str = "zh"  # 前端显示文本语言 (ja/zh/en)
    tts_type: str = "gsv"


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

        # Script data
        self.script_lines: list[ScriptLine] = []
        self.scene_config: SceneConfig = SceneConfig()

        # Active LLM stream task (cancellable)
        self._active_llm_task: Optional[asyncio.Task] = None

        # Budget
        self.budget = BudgetStatus()

    # ── Continue / Edit ──────────────────────────────────────────

    async def handle_continue(
        self, generation_id: str, edits: dict | None = None
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
        if edits and "modified_lines" in edits:
            self._apply_edits(edits["modified_lines"])

        # Clear queues
        while not self.sentence_queue.empty():
            self.sentence_queue.get_nowait()

        self.paused = False
        logger.info(
            f"SessionRuntime: epoch={self.generation_epoch}, continuing..."
        )
        return self.generation_epoch

    def _apply_edits(self, modified_lines: list[dict]):
        """Update edited lines in script_lines; discard everything after the first edit."""
        if not modified_lines:
            return

        first_modified_idx = min(
            self._find_line_index(ln["id"])
            for ln in modified_lines
            if "id" in ln
        )

        # Truncate from first modified index
        self.script_lines = self.script_lines[:first_modified_idx]

        # Append modified lines
        for i, line_data in enumerate(modified_lines):
            new_line = ScriptLine(
                index=first_modified_idx + i,
                generation_epoch=self.generation_epoch,
                speaker=line_data.get("speaker", "ema"),
                display_text=line_data.get("display_text", ""),
                tts_text=line_data.get("tts_text", ""),
                state="approved",
            )
            self.script_lines.append(new_line)

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
