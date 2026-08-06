"""Standalone runtime for the fanfiction-to-script pipeline.

Composes the real A2D pieces WITHOUT constructing a full AIService
(whose __init__ starts background tasks, proactive system, message loops —
all irrelevant to offline batch generation). Reuses:
- SessionRuntime          (script_lines, characters, scene_config, update_scene)
- CharacterConfig + GameRole + VoiceMaker + GSV adapter (real TTS path)
- LLMManager              (real LLM provider)
- parse_script_line       (extracted, battle-tested format parser)

The only thing it does NOT reuse is AIService's heavy system-prompt builder;
instead it builds a focused "adapt this passage to script format" prompt that
teaches the LLM the same output format conventions (【】, <TTS>, （action）,
{"speaker":...} markers, 旁白：) so parse_script_line works unchanged.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import uuid
from typing import List, Optional

from ling_chat.core.fic_chunker import Chunk
from ling_chat.core.ai_service.core import parse_script_line, TTS_JOIN_SEP
from ling_chat.core.llm_providers.manager import LLMManager
from ling_chat.core.session_runtime import CharacterConfig, SessionRuntime
from ling_chat.schemas.script_overlay import ScriptLine


logger = logging.getLogger(__name__)


# Reuse the real character-config builder. It only needs something with no
# ai_service-specific state (the original signature takes ai_service but never
# reads it), so we pass None safely.
async def _build_character_configs() -> dict[str, CharacterConfig]:
    """Build ema/hiro CharacterConfig dict with real GameRole + voice_maker."""
    from ling_chat.utils.function import Function
    from ling_chat.utils.runtime_path import user_data_path

    configs: dict[str, CharacterConfig] = {}
    characters_dir = user_data_path / "game_data" / "characters"
    if not characters_dir.exists():
        logger.warning(f"characters dir not found: {characters_dir}")
        return configs

    allowed_raw = os.environ.get("A2D_STAGE_CHARACTERS", "").strip()
    allowed = (
        {k.strip() for k in allowed_raw.split(",") if k.strip()}
        if allowed_raw
        else None
    )

    for char_dir in sorted(characters_dir.iterdir()):
        if not char_dir.is_dir() or not (char_dir / "settings.yml").exists():
            continue
        try:
            settings = Function.load_character_settings(char_dir)
        except Exception as e:
            logger.warning(f"failed to load settings for '{char_dir.name}': {e}")
            continue

        role_key = getattr(settings, "script_role_key", None) or char_dir.name
        if allowed is not None and role_key not in allowed:
            continue

        voice_lang = (
            getattr(getattr(settings, "voice_models", None), "voice_language", None)
            or "ja"
        )
        game_role = None
        try:
            from ling_chat.core.ai_service.type import GameRole

            # GameRole.__post_init__ calls set_tts → set_tts_settings, which for
            # GSV voices calls asyncio.create_task (model loading). That needs a
            # running event loop at construction time — satisfied here because
            # _build_character_configs is awaited from within a live loop.
            game_role = GameRole(
                settings=settings,
                resource_path=str(char_dir),
                display_name=getattr(settings, "ai_name", None) or char_dir.name,
            )
        except Exception as e:
            logger.warning(f"GameRole init failed for '{role_key}': {e}")

        configs[role_key] = CharacterConfig(
            script_role_key=role_key,
            character_folder=char_dir.name,
            voice_language=voice_lang,
            display_language="zh",
            game_role=game_role,
        )

    return configs


class FicRuntime:
    """Standalone fanfiction-to-script runtime (no AIService, no web server)."""

    def __init__(
        self,
        *,
        characters: dict[str, CharacterConfig],
        llm: Optional[LLMManager] = None,
        batch_size: int = 1,
        narration_mode: str = "merge",
        narrator_voice_key: Optional[str] = None,
    ) -> None:
        self.session = SessionRuntime(characters=characters)
        self.session.batch_size = batch_size
        self.session.narration_mode = narration_mode
        self.session.narrator_voice_key = narrator_voice_key
        self.llm = llm if llm is not None else LLMManager()

    @classmethod
    async def create(
        cls,
        *,
        characters: Optional[dict[str, CharacterConfig]] = None,
        llm: Optional[LLMManager] = None,
        batch_size: int = 1,
        narration_mode: str = "merge",
        narrator_voice_key: Optional[str] = None,
    ) -> "FicRuntime":
        """Async factory — builds character configs (needs a running loop for GSV)."""
        built = characters if characters is not None else await _build_character_configs()
        return cls(
            characters=built,
            llm=llm,
            batch_size=batch_size,
            narration_mode=narration_mode,
            narrator_voice_key=narrator_voice_key,
        )

    # ------------------------------------------------------------------
    # Prompt
    # ------------------------------------------------------------------
    def build_prompt(self, material: str, speaker_ids: List[str]) -> str:
        """Focused adaptation prompt: convert a prose passage to script format."""
        chars_block = "\n".join(
            f"- {key}: {cfg.character_folder}（显示语言={cfg.display_language}, 语音语言={cfg.voice_language}）"
            for key, cfg in self.session.characters.items()
        )
        speaker_rules = "\n".join(
            f'  - 当{person}说话时，输出 {{"speaker":"{key}"}} 标记'
            for key, cfg in self.session.characters.items()
            for person in [cfg.character_folder]
        )
        return f"""你是一个剧本改编器。请围绕参考材料中的故事内容展开对话，忠实还原原作风格与氛围（同人演绎）。把下面的同人文片段忠实改编为双人对话剧本，尽可能保留原文的台词和风格。

## 可用角色（speaker_id）
{chars_block}

## 改编规则
- 将叙述性描写转为旁白（旁白：…），将对话转为角色台词。
- 保留原台词；如原文为中文，台词保持中文（显示语言），语音朗读文本为日语翻译（<TTS>内）。
- 每行必须是严格的单行格式：【情绪】显示文本<TTS语音文本>（动作）
- 情绪标签从以下选择：高兴、兴奋、生气、厌恶、无语、疑惑、慌张、担心、紧张、害怕、害羞、认真、调皮、尴尬、难情、惊讶、心动、哭泣、自信、无奈
- 在每句台词前输出说话者标记（单独一行）：
{speaker_rules}
- 旁白格式（单独成行）：
{{"speaker":"narrator"}}
旁白：要描述的文本
- 不要使用颜文字；每句话保持完整断句；<TTS>中不要包含动作。

## 参考材料（待改编片段）
{material}

现在开始改编这个片段，一次输出一行（标记+台词/旁白），忠实于原文。"""

    # ------------------------------------------------------------------
    # Material guard (AC-2 negative)
    # ------------------------------------------------------------------
    _SENTENCE_BOUND = re.compile(r"(?<=[。！？；])\s*")

    def _truncate_material(self, material: str) -> str:
        """Truncate over-long material at the last sentence boundary + marker."""
        if len(material) <= self.MAX_MATERIAL_CHARS:
            return material
        truncated = material[: self.MAX_MATERIAL_CHARS]
        # Cut at the last sentence boundary so we don't split mid-sentence.
        last = truncated.rfind("。")
        if last > 0:
            truncated = truncated[: last + 1]
        return truncated + self._TRUNCATION_MARKER

    # ------------------------------------------------------------------
    # Messages (reuse A2D history convention)
    # ------------------------------------------------------------------
    def build_messages(self, system_prompt: str) -> list[dict]:
        """Build LLM messages from session history (mirrors A2D convention)."""
        session = self.session
        messages = [{"role": "system", "content": system_prompt}]

        for line in session.script_lines:
            if line.raw_text:
                content = line.raw_text
            else:
                tts_text = line.tts_text or line.display_text
                content = f"【{line.emotion}】{line.display_text}<{tts_text}>"
            if line.speaker == "narrator":
                messages.append({"role": "user", "content": f"{{旁白: {content}}}"})
            else:
                messages.append(
                    {"role": "assistant", "content": f'{{"speaker":"{line.speaker}"}}\n{content}'}
                )

        if not session.script_lines:
            messages.append({"role": "user", "content": "{旁白：开场}"})
        return messages

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------
    # AC-2 guard: material longer than this is truncated with a visible marker.
    MAX_MATERIAL_CHARS = 4000
    _TRUNCATION_MARKER = "[材料已截断]"

    async def generate_one(self, material: str) -> Optional[dict]:
        """Generate one script line from the reference material."""
        if not self.session.characters:
            raise RuntimeError("No characters configured in FicRuntime")
        if material is None:
            raise ValueError("material=None — nothing to adapt (AC-2 guard)")

        # AC-2 negative: over-long material → truncate at sentence boundary + marker.
        material = self._truncate_material(material)

        speaker_ids = list(self.session.characters.keys())
        system_prompt = self.build_prompt(material, speaker_ids)
        messages = self.build_messages(system_prompt)
        full_text = await self._call_llm(messages)

        session = self.session
        session.last_raw_llm_response = full_text
        current_speaker = speaker_ids[0]

        for raw_line in full_text.split("\n"):
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            if raw_line.startswith("{") and '"speaker"' in raw_line:
                try:
                    marker = json.loads(raw_line)
                    sid = marker.get("speaker", "")
                    if sid in session.characters:
                        current_speaker = sid
                    else:
                        # AC-3 negative: unknown speaker → narrator + warning.
                        logger.warning(
                            f"unmapped speaker '{sid}', defaulting to narrator"
                        )
                        current_speaker = "narrator"
                except (json.JSONDecodeError, KeyError, ValueError):
                    pass
                continue
            line = parse_script_line(raw_line, current_speaker)
            if line:
                if line.speaker == "narrator":
                    if session.narration_mode == "split":
                        session.add_line(line)
                    else:
                        if session.script_lines:
                            prev = session.script_lines[-1]
                            prev.raw_text = (prev.raw_text or "") + "\n" + raw_line
                        else:
                            session.add_line(line)
                else:
                    session.add_line(line)
                return line
        return None

    async def _call_llm(self, messages: list[dict]) -> str:
        full_text = ""
        async for chunk in self.llm.process_message_stream(messages):
            if isinstance(chunk, str):
                full_text += chunk
            elif hasattr(chunk, "content"):
                full_text += chunk.content or ""
            elif isinstance(chunk, dict):
                full_text += chunk.get("content", "") or str(chunk)
            else:
                full_text += str(chunk)
        if not full_text.strip():
            raise RuntimeError("LLM returned empty response")
        return full_text

    # ------------------------------------------------------------------
    # Synthesis
    # ------------------------------------------------------------------
    async def synthesize(self, line: ScriptLine) -> str:
        """Synthesize TTS for a line. Returns audio URL path ('' if skipped)."""
        import os

        session = self.session
        effective_speaker = line.speaker
        if line.speaker == "narrator":
            vk = session.narrator_voice_key
            if isinstance(vk, str) and vk:
                cfg = session.characters.get(vk)
                if cfg and cfg.game_role and cfg.game_role.voice_maker:
                    effective_speaker = vk
                else:
                    return ""
            else:
                return ""

        cfg = session.characters.get(effective_speaker) if effective_speaker else None
        if not (cfg and cfg.game_role and cfg.game_role.voice_maker):
            return ""
        voice_maker = cfg.game_role.voice_maker
        if not voice_maker.tts_provider.gsv_adapter:
            return ""

        line_id = line.id or f"fic_{uuid.uuid4().hex[:12]}"
        output_path = os.path.join(
            str(voice_maker.tts_provider.temp_dir), f"a2d_{line_id}.wav"
        )
        text = line.tts_text.strip()
        if not text:
            return ""  # empty tts_text → skip
        try:
            audio_data = await voice_maker.tts_provider.gsv_adapter.generate_voice(text)
        except Exception as exc:  # GSV server offline / network error → degrade
            logger.warning(f"GSV synthesis failed for {line_id} ({exc}); skipping audio")
            return ""
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(audio_data)
        return f"/audio/a2d_{line_id}.wav"
