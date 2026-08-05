import asyncio
import os
from typing import Dict

from ling_chat.core.ai_service.ai_logger import AILogger
from ling_chat.core.session_runtime import CharacterConfig, SessionRuntime
from ling_chat.core.ai_service.config import AIServiceConfig
from ling_chat.core.ai_service.exceptions import ScriptEngineError
from ling_chat.core.ai_service.game_system.game_status import GameStatus
from ling_chat.core.ai_service.message_system.message_generator import MessageGenerator
from ling_chat.core.ai_service.message_system.message_processor import MessageProcessor
from ling_chat.core.ai_service.proactive_system.core import ProactiveSystem
from ling_chat.core.ai_service.script_engine.script_manager import ScriptManager
from ling_chat.core.ai_service.translator import Translator
from ling_chat.core.llm_providers.manager import LLMManager
from ling_chat.core.logger import logger
from ling_chat.core.messaging.broker import message_broker
from ling_chat.core.schemas.response_models import ResponseFactory
from ling_chat.game_database.models import GameLine, LineAttribute, LineBase
from ling_chat.schemas.character_settings import CharacterSettings
from ling_chat.utils.function import Function


class AIService:
    def __init__(self, settings: CharacterSettings):
        """
        初始化AI助手实例

        参数:
            settings: 配置字典，包含各种设置项
        """
        self.game_status = GameStatus()

        self.user_id = "1"  # TODO: 多用户的时候这里可以改成按照初始化获取，或者直接从client_id中获取

        self.config = AIServiceConfig(clients=set(), user_id=self.user_id)

        self.use_rag = os.environ.get("USE_RAG", "False").lower() == "true"
        self.llm_model = LLMManager()
        self.ai_logger = AILogger()
        self.translator = Translator(self.game_status)
        self.message_broker = message_broker
        self.message_processor = MessageProcessor(self.game_status)
        self.message_generator = MessageGenerator(
            self.config,
            self.message_processor,
            self.translator,
            self.llm_model,
            self.ai_logger,
            self.game_status,
        )

        # self.events_scheduler.start_nodification_schedules()        # 之后会通过API设置和处理

        # self.output_queue_name = self.client_id             # WebSocket输出队列
        self.client_tasks: Dict[str, asyncio.Task] = {}

        # 全局生成锁：确保同一时刻只有一路 process_message_stream 在运行，
        # 防止主动对话与用户消息并发导致流式输出交叉混乱
        self._generation_lock = asyncio.Lock()

        self.processing_task = asyncio.create_task(self._process_message_loop())
        self.global_task = asyncio.create_task(self._process_global_messages())

        # self.events_scheduler = EventsScheduler(self.config)
        self.proactive_system = ProactiveSystem(
            self.config, self.game_status, self.message_generator, self._generation_lock
        )
        self.import_settings(settings)
        # self.events_scheduler.start_nodification_schedules()        # TODO: 这个由前端开关控制
        self.proactive_system.start()

        self.scripts_manager = ScriptManager(self.config, self.game_status)

        # A2D Studio: script-editor session orchestrator
        self.a2d_session: SessionRuntime = SessionRuntime()

        # 特别的，设定当游戏角色被导入的时候，设定它为游戏主角，其他情况下则以变量为准，并初始化system prompt
        self._init_game_status()

    def import_settings(self, settings: CharacterSettings) -> None:
        # TODO: 这些以后全都可以删除，改为通过修改game_status的GameRole来实现
        if settings:
            self.character_path = settings.resource_path
            self.character_id = (
                settings.character_id
            )  # TODO: character_id就是查找的role_id，这里写的不太优雅，可以之后优化
            self.ai_name = settings.ai_name
            self.ai_subtitle = settings.ai_subtitle
            self.user_name = settings.user_name
            self.user_subtitle = settings.user_subtitle
            self.ai_prompt = (
                settings.system_prompt
                or "你的信息被设置错误了，请你在接下来的对话中提示用户检查配置信息"
            )
            self.game_status.player.user_name = self.user_name
            self.game_status.player.user_subtitle = (
                self.user_subtitle if self.user_subtitle else ""
            )

            self.ai_prompt_example = settings.system_prompt_example
            self.ai_prompt_example_old = settings.system_prompt_example_old
            self.ai_prompt = Function.sys_prompt_builder(
                self.user_name,
                self.ai_name,
                self.ai_prompt,
                self.ai_prompt_example,
                self.ai_prompt_example_old,
            )

            self.clothes_name = settings.clothes_name
            self.body_part = settings.body_part
            self.clothes = settings.clothes
            self.settings = settings

        else:
            logger.error("角色信息settings没有被正常导入，请检查问题！")

        # self.events_scheduler.ai_name = self.ai_name
        # self.events_scheduler.user_name = self.user_name

    def apply_runtime_config(self, updates: dict[str, str]) -> None:
        """
        根据运行时更新的配置，热重载关键组件，避免重启。
        仅在有相关键变动时做最小开销的重建。
        """
        try:
            llm_keys = {
                "LLM_PROVIDER",
                "MODEL_TYPE",
                "CHAT_API_KEY",
                "CHAT_BASE_URL",
                "TRANSLATE_LLM_PROVIDER",
                "TRANSLATE_MODEL",
                "TRANSLATE_API_KEY",
                "TRANSLATE_BASE_URL",
            }
            if any(k in updates for k in llm_keys):
                self.llm_model = LLMManager()
                self.message_generator.llm_model = self.llm_model
                logger.info("运行时配置更新：LLMManager 已重建并替换。")

            if "COMSUMERS" in updates:
                try:
                    new_concurrency = int(
                        os.environ.get("COMSUMERS", self.message_generator.concurrency)
                    )
                    if new_concurrency > 0:
                        self.message_generator.concurrency = new_concurrency
                        logger.info(
                            f"运行时配置更新：并发消费者数量设置为 {new_concurrency}"
                        )
                except Exception:
                    logger.warning("COMSUMERS 配置无效，忽略。")

        except Exception as e:
            logger.error(f"应用运行时配置失败: {e}", exc_info=True)

    def get_lines(self):
        return self.game_status.line_list

    def set_active_save_id(self, save_id: int | None):
        """
        设置当前激活存档，用于 MemoryBank 持久化/自动压缩等逻辑。
        """
        self.game_status.active_save_id = save_id

    def load_lines(
        self, lines: list[GameLine], main_role_id: int, save_id: int | None = None
    ):
        self.game_status.line_list = lines
        if save_id is not None:
            self.set_active_save_id(save_id)
            # 仅在“载入存档”时从 DB 载入 MemoryBank 到运行时缓存
            involved_role_ids = set()
            for line in self.game_status.line_list:
                if line.sender_role_id:
                    involved_role_ids.add(line.sender_role_id)
                involved_role_ids.update(line.perceived_role_ids or [])
            self.game_status.role_manager.load_memory_banks_from_db(
                save_id, list(involved_role_ids)
            )

        self.game_status.role_manager.sync_memories(self.game_status.line_list)
        main_role = self.game_status.role_manager.get_role(role_id=main_role_id)

        if main_role:
            # TODO: 以后加载台词的时候，current_character应该由存档中的变量数据来决定，而不是直接使用存档主角。
            self.game_status.current_character = main_role
            self.game_status.main_role = main_role
        else:
            logger.error(f"存档的主角色ID {main_role_id} 未找到。")

    def reset_lines(self):
        self._init_game_status()

    def clear_lines(self):
        """
        清除对话历史，保留角色和基本配置，只清除台词和主角记忆。
        比 reset_lines() 更轻量，不重新初始化角色，不误伤 NPC 记忆。
        """
        # 清空台词列表
        self.game_status.line_list = []
        # 添加系统提示作为第一条消息
        system_line = LineBase(
            content=self.ai_prompt,
            attribute=LineAttribute.SYSTEM,
            sender_role_id=self.character_id,
            display_name=self.ai_name,
        )
        self.game_status.add_line(system_line)

        # 只清除主角的短期记忆，保留 NPC 记忆
        if self.game_status.main_role and self.game_status.main_role.role_id:
            self.game_status.role_manager.clear_role_memory(
                self.game_status.main_role.role_id
            )

        logger.info("对话历史已清除（仅主角记忆）")

    def persist_memory_banks(self, save_id: int):
        """
        将运行时的 memory_bank 缓存写入 DB（仅在创建/保存存档时调用）。
        """
        self.game_status.role_manager.persist_memory_banks_to_db(save_id)

    def _init_game_status(self):
        self.game_status.role_manager.reset_roles()

        self.game_status.line_list = []
        system_line = LineBase(
            content=self.ai_prompt,
            attribute=LineAttribute.SYSTEM,
            sender_role_id=self.character_id,
            display_name=self.ai_name,
        )
        self.game_status.add_line(system_line)

        if self.character_id:
            self.game_status.current_character = self.game_status.role_manager.get_role(
                self.character_id
            )
            self.game_status.onstage_role(self.game_status.current_character)
            self.game_status.main_role = self.game_status.current_character
            # logger.info(f"初始化游戏主角：{self.game_status.current_character} 已初始化。")
        else:
            logger.error("初始化游戏主角失败，未指定角色ID。")

    def show_lines(self):
        logger.info("当前台词列表如下：")
        for line in self.game_status.line_list:
            logger.info(
                f"{line.display_name} : 【{line.original_emotion}】{line.content}<{line.tts_content}>（{line.action_content}）"
            )

    def show_current_role_memory(self):
        if self.game_status.current_character:
            logger.info("当前角色的记忆列表如下：")
            logger.info(f"{self.game_status.current_character.memory}")
        else:
            logger.error("没有当前绑定的角色。")

    async def start_script(self, script_name: str | None = None):
        """
        开始剧本模式。
        - script_name=None: 使用剧本列表第一个
        - script_name=指定: 使用指定剧本名（story_config.yaml 的 script_name）
        """
        script_list = self.scripts_manager.get_script_list()
        if not script_list:
            raise ScriptEngineError("没有可用的剧本。")

        # 剧本模式启动的时候，先清理 proactive_system，防止主动对话
        chosen = script_name or script_list[0]
        await self.proactive_system.cleanup()
        ok = await self.scripts_manager.start_script(chosen)
        if not ok:
            raise ScriptEngineError(f"剧本 {chosen} 加载失败。")
        self.proactive_system.start()

    async def set_scene(self, scene_id: str, trigger_response: bool = False) -> bool:
        """
        设置场景（增强版）

        Args:
            scene_id: 场景 ID
            trigger_response: 是否立即触发 AI 响应
        """
        from ling_chat.utils.scene_manager import SceneManager

        scene_manager = SceneManager()
        scene = scene_manager.get_scene(scene_id)

        if not scene:
            logger.error(f"场景不存在: {scene_id}")
            return False

        # 确定是否之前存在场景感知台词，如果有的话，替换掉之前的感知台词

        # 1. 取出 game_status 中的栈顶台词
        top_line = self.game_status.line_list[-1]

        # 2. 判断是否是场景感知台词
        if top_line.attribute == LineAttribute.USER and top_line.content.startswith(
            "{ 旁白：现在场景切换到了"
        ):
            # 3. 替换场景感知台词
            scene_line_content = f"{{ 旁白：现在场景切换到了{scene['sceneName']}, {scene['sceneDescription']}。"
            top_line.content = scene_line_content

        # 4. 如果没有场景感知台词，则新增一条场景感知台词
        else:
            scene_line_content = f"{{ 旁白：现在场景切换到了{scene['sceneName']}, {scene['sceneDescription']}。"
            line = LineBase(content=scene_line_content, attribute=LineAttribute.USER)
            self.game_status.add_line(line)

        # 更新当前场景
        self.game_status.current_scene = scene["sceneDescription"]

        # 通过 WebSocket 通知前端
        for client_id in self.config.clients:
            await message_broker.publish(
                client_id, {"type": "scene_change", "scene": scene}
            )

        logger.info(f"场景已加载: {scene['sceneName']}")
        return True

    async def _process_client_messages(self, client_id: str):
        """处理单个客户端的消息"""
        input_queue_name = f"ai_input_{client_id}"
        try:
            async for message in self.message_broker.subscribe(input_queue_name):
                try:
                    user_message = message.get("content", "")
                    if user_message:
                        # 用全局生成锁串行化所有流式生成，防止主动对话与用户消息并发交叉
                        async with self._generation_lock:
                            self.is_processing = True
                            try:
                                await message_broker.publish(
                                    client_id,
                                    (
                                        ResponseFactory.create_thinking(
                                            True
                                        ).model_dump()
                                    ),
                                )
                                responses = []
                                async for (
                                    response
                                ) in self.message_generator.process_message_stream(
                                    user_message=user_message
                                ):
                                    await message_broker.publish(
                                        client_id, response.model_dump()
                                    )
                                    responses.append(response)
                                logger.debug(
                                    f"消息处理完成，共生成 {len(responses)} 个响应片段"
                                )
                            finally:
                                self.is_processing = False
                        self.proactive_system.on_user_message_received()

                except Exception as e:
                    logger.error(f"处理消息时发生错误: {e}")
                    self.is_processing = False
                    await message_broker.publish(
                        client_id, (ResponseFactory.create_thinking(False).model_dump())
                    )

        except asyncio.CancelledError:
            logger.info(f"客户端 {client_id} 的消息处理任务已被取消")
        except Exception as e:
            logger.error(f"客户端 {client_id} 的消息处理发生严重错误: {e}")
            raise

    async def _process_message_loop(self):
        """主消息处理循环"""
        while True:
            try:
                # 检查是否有新的客户端需要添加
                for client_id in self.config.clients:
                    if client_id not in self.client_tasks:
                        task = asyncio.create_task(
                            self._process_client_messages(client_id)
                        )
                        self.client_tasks[client_id] = task
                        logger.info(f"已为客户端 {client_id} 创建消息处理任务")

                # 检查是否有客户端任务已完成或需要移除
                for client_id in list(self.client_tasks.keys()):
                    if client_id not in self.config.clients:
                        task = self.client_tasks[client_id]
                        task.cancel()
                        try:
                            await task
                        except asyncio.CancelledError:
                            pass
                        del self.client_tasks[client_id]
                        logger.info(f"已移除客户端 {client_id} 的消息处理任务")

                await asyncio.sleep(0.1)  # 短暂休眠以避免过度占用CPU

            except Exception as e:
                logger.error(f"消息处理循环发生错误: {e}")
                await asyncio.sleep(1)  # 发生错误时等待较长时间再重试

    async def add_client(self, client_id: str):
        """添加新客户端"""
        logger.info(f"添加客户端: {client_id}")
        self.config.clients.add(client_id)
        # 消息处理循环会在下一次迭代时自动创建新任务

    async def remove_client(self, client_id: str):
        """移除客户端"""
        logger.info(f"移除客户端: {client_id}")
        self.config.clients.discard(client_id)
        # 消息处理循环会在下一次迭代时自动取消并清理任务

    async def _process_global_messages(self):
        """处理全局消息"""
        global_queue_name = "ai_input_global"
        try:
            async for message in self.message_broker.subscribe(global_queue_name):
                try:
                    user_message = message.get("content", "")
                    if user_message:
                        # 用全局生成锁串行化所有流式生成，防止主动对话与全局消息并发交叉
                        async with self._generation_lock:
                            self.is_processing = True
                            try:
                                responses = []
                                async for (
                                    response
                                ) in self.message_generator.process_message_stream(
                                    user_message
                                ):
                                    if self.config.last_active_client:
                                        await message_broker.publish(
                                            self.config.last_active_client,
                                            response.model_dump(),
                                        )
                                    else:
                                        for client_id in self.config.clients:
                                            await message_broker.publish(
                                                client_id, response.model_dump()
                                            )
                                        responses.append(response)
                                logger.debug(
                                    f"全局消息处理完成，共生成 {len(responses)} 个响应片段"
                                )
                            finally:
                                self.is_processing = False

                except Exception as e:
                    logger.error(f"处理全局消息时发生错误: {e}")
                    self.is_processing = False
        except asyncio.CancelledError:
            logger.info("全局消息处理任务已被取消")
        except Exception as e:
            logger.error(f"全局消息处理发生严重错误: {e}")
            raise

    async def shutdown(self):
        """优雅关闭服务"""
        logger.info("正在关闭AI服务...")

        # 取消所有客户端任务
        for _client_id, task in self.client_tasks.items():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass  # 忽略取消错误

        # 取消全局消息处理任务
        self.global_task.cancel()
        try:
            await self.global_task
        except asyncio.CancelledError:
            pass

        # 取消主处理任务
        self.processing_task.cancel()
        try:
            await self.processing_task
        except asyncio.CancelledError:
            pass

        logger.info("AI服务已关闭")

    # ── A2D Studio: Script Editor Methods ─────────────────────────

    async def a2d_generate_one(
        self,
        scene_suffix: str | None = None,
    ) -> dict | None:
        """Generate exactly one script line. Call N times for batch_size=N.

        LLM outputs one line: {"speaker":"ema"}\\n【高兴】text<TTS_text>（action）
        Returns a WS-ready dict: {type: "script_line", payload: {id, speaker, ...}}
        Returns None if LLM returns no valid line.
        """
        import json as json_mod
        from ling_chat.schemas.script_overlay import ScriptLine

        session = self.a2d_session
        if not session.characters:
            raise RuntimeError("No characters configured in SessionRuntime")

        system_prompt = self._a2d_build_system_prompt(scene_suffix)
        messages = self._a2d_build_messages(system_prompt)
        full_text = await self._a2d_call_llm_with_retry(messages)

        # Store verbatim LLM response for monitor/debugging
        session.last_raw_llm_response = full_text

        # Parse exactly one speaker marker + one dialogue line
        first_key = list(session.characters.keys())[0]
        current_speaker = first_key

        for raw_line in full_text.split("\n"):
            raw_line = raw_line.strip()
            if not raw_line:
                continue

            # Speaker marker: {"speaker":"ema"}
            try:
                if raw_line.startswith("{") and '"speaker"' in raw_line:
                    marker = json_mod.loads(raw_line)
                    speaker_id = marker.get("speaker", "")
                    if speaker_id in session.characters:
                        current_speaker = speaker_id
                    continue
            except (json_mod.JSONDecodeError, KeyError, ValueError):
                pass

            # Parse: 【emotion】content<TTS>（action）
            line = self._a2d_parse_script_line(raw_line, current_speaker)
            if line:
                if line.speaker == "narrator":
                    if session.narration_mode == "split":
                        # Split mode: narrator as independent ScriptLine (own id, own raw_text)
                        session.add_line(line)
                    else:
                        # Merge mode (default): merge into previous line's raw_text
                        script_lines = session.script_lines
                        if script_lines:
                            prev = script_lines[-1]
                            prev.raw_text = (prev.raw_text or "") + "\n" + raw_line
                            continue  # Don't create a new ScriptLine
                        else:
                            session.add_line(line)
                else:
                    session.add_line(line)

                # Format-violation detection: action leaked into TTS text (dialogue only).
                # Count violations to track LLM format compliance. Threshold warning emitted
                # by caller if violation rate exceeds 30%.
                if line.speaker != "narrator":
                    if re.search(r"[（(][^）)]+[）)]", line.tts_text):
                        session.format_violations = getattr(session, "format_violations", 0) + 1

                # Honour A2D_SHOW_ACTIONS env var (default "1" = show)
                show_actions = os.environ.get("A2D_SHOW_ACTIONS", "1") != "0"
                final_display = line.display_text
                if show_actions and line.action:
                    final_display = f"{final_display}（{line.action}）"

                return {
                    "type": "script_line",
                    "payload": {
                        "id": line.id,
                        "speaker": line.speaker,
                        "emotion": line.emotion,
                        "display_text": final_display,
                        "tts_text": line.tts_text,
                        "action": line.action,
                        "index": line.index,
                    },
                }

        return None  # No valid line found

    def _a2d_build_system_prompt(self, scene_suffix: str | None = None) -> str:
        """Build system prompt with character configs, scene, and knowledge.

        Language instructions are generated dynamically from CharacterConfig,
        not hardcoded. Reuses LingChat format conventions ({旁白}, 【情绪】, <TTS>).
        """
        session = self.a2d_session
        # Filter to A2D_STAGE_CHARACTERS env var (belt-and-suspenders: config builder
        # also filters, but this ensures prompt never includes non-stage characters)
        import os
        stage_cfg = os.environ.get("A2D_STAGE_CHARACTERS", "").strip()
        allowed = {k.strip() for k in stage_cfg.split(",") if k.strip()} if stage_cfg else None
        all_chars = session.characters
        chars = (
            {k: v for k, v in all_chars.items() if k in allowed}
            if allowed is not None
            else all_chars
        )

        parts = ["你是一个双人对话生成器。根据以下角色设定生成自然对话。"]

        # ── Character personas + knowledge ─────────────────
        for key, cfg in chars.items():
            parts.append(f"\n## {cfg.character_folder}（speaker_id: {key}）")
            # Prefer GameRole.settings.system_prompt, fall back to file loading
            persona = None
            if cfg.game_role and cfg.game_role.settings.system_prompt:
                persona = f"角色人设：{cfg.game_role.settings.system_prompt}"
            else:
                persona = self._a2d_load_persona(cfg.character_folder)
            if persona:
                parts.append(persona)
            knowledge = self._a2d_load_knowledge(key, cfg.character_folder)
            if knowledge:
                parts.append(knowledge)

        # ── Scene ──────────────────────────────────────────
        if scene_suffix:
            parts.append(f"\n{scene_suffix}")

        # ── LingChat format conventions ────────────────────
        # These match what LingChat's sys_prompt_builder teaches LLM,
        # so 【】, <>, （） parsing by StreamProducer works correctly.
        parts.append("""
## 上下文格式
大括号{}包裹的内容是系统给你的感知信息，比如：
{旁白: 环境描述或开场信息}
{系统提醒: 时间信息}
这些是上下文提示，需要根据它们自然对话，无需逐条回应。

## 单人标准发言格式
对每句话的回应要符合格式：【情绪】显示文本<TTS语音朗读文本>
- 【情绪】内为情绪标签，从以下选择：高兴、兴奋、生气、厌恶、无语、疑惑、慌张、担心、紧张、害怕、害羞、认真、调皮、尴尬、难为情、惊讶、心动、哭泣、自信、无奈
- <TTS语音朗读文本> 尖括号内为语音合成朗读文本
- 只会在必要的时候用括号（）来描述动作，接在TTS语音朗读文本后面，不需要每一段回应都带有动作，（动作）放在对话末尾，同一行内。TTS语音朗读文本中不要包含动作。
- 示例：【情绪】显示文本<TTS语音朗读文本>（动作）
- 示例1：【羞耻】呀……！？<きゃんっ……！？>（稍稍后退）
- 示例2：【羞耻】艾玛，你这个小笨狗。<エマ、このバカ犬。>
- 不使用颜文字，每句话保持完整断句""")

        # ── A2D dual-character rules ───────────────────────
        lang_lines = []
        for key, cfg in chars.items():
            lang_lines.append(
                f"  {cfg.character_folder}: 显示语言={cfg.display_language}, "
                f"TTS语音语言={cfg.voice_language}"
            )
        lang_info = "\n".join(lang_lines)

        dual_lang_chars = [
            key for key, cfg in chars.items()
            if cfg.display_language != cfg.voice_language
        ]

        if dual_lang_chars:
            dual_names = [chars[k].character_folder for k in dual_lang_chars]
            tts_instruction = (
                f"注意：{', '.join(dual_names)} 的显示语言与TTS语音语言不同，"
                "这些角色需要提供<TTS语音朗读文本>。"
                "TTS文本是对应语音语言的翻译。"
            )
        else:
            # tts_instruction = "可省略<TTS文本>（显示语言与TTS语言相同）。"
            tts_instruction = ""

        prompt_lines = []
        prompt_lines.append("## 多人整体输出格式，承接单人标准发言格式")
        prompt_lines.append("每次生成一句对话。根据对话上下文，选择一个合适的角色发言。")
        prompt_lines.append("先标注说话者，然后使用标准发言格式。")
        prompt_lines.append("示例1：")
        prompt_lines.append('{"speaker":"ema"}')
        prompt_lines.append("【害羞】唔，又被希罗酱说小笨狗了。<うん、またヒロちゃんにバカ犬って言われちゃった。>")
        prompt_lines.append("示例2：")
        prompt_lines.append('{"speaker":"hiro"}')
        prompt_lines.append("【害羞】艾玛，这是，不正确的。<エマ、それは、正しくない。>（脸红着别开视线）")
        prompt_lines.append("")
        prompt_lines.append("规则：")
        prompt_lines.append("- speaker 使用上面定义的 speaker_id")
        # prompt_lines.append("- 【情绪】方括号内为情绪标签，从给定列表中选择")
        # prompt_lines.append(f"- <TTS语音朗读文本> 尖括号内为TTS语音合成文本，{tts_instruction}")
        # prompt_lines.append("- （动作描述）放在对话末尾，同一行内。TTS语音朗读文本中绝对不要包含动作描述")
        prompt_lines.append("- 可以根据对话历史和流向选择合适的发言者，用自然的对话节奏")
        char_names = [cfg.character_folder for cfg in chars.values()]
        # if len(char_names) > 1:
        #     prompt_lines.append("- 交替让角色发言，不要连续让同一个角色说话")
        # prompt_lines.append("- 如果对话应该继续，选择下一个角色；如果自然结束，可以给出简短的结束语")
        prompt_lines.append("")
        prompt_lines.append("## 角色语言设定")
        prompt_lines.append(lang_info)
        parts.append("\n".join(prompt_lines))
        return "\n".join(parts)

    def _a2d_load_persona(self, folder_name: str) -> str | None:
        """Load character system_prompt from settings.yml."""
        from pathlib import Path
        from ling_chat.utils.function import Function
        from ling_chat.utils.runtime_path import user_data_path

        char_dir = user_data_path / "game_data" / "characters" / folder_name
        if not char_dir.exists():
            return None
        try:
            settings = Function.load_character_settings(char_dir)
            if settings.system_prompt:
                return f"角色人设：{settings.system_prompt}"
        except Exception as e:
            logger.warning(f"A2D: failed to load persona for {folder_name}: {e}")
        return None

    def _a2d_load_knowledge(self, speaker_id: str, folder_name: str) -> str | None:
        """Load character knowledge from knowledge/ directory."""
        from pathlib import Path

        knowledge_dir = (
            Path("ling_chat/static/game_data/characters")
            / folder_name
            / "knowledge"
        )
        if not knowledge_dir.exists():
            return None

        parts = []
        for f in sorted(knowledge_dir.glob("*.md")):
            try:
                parts.append(f.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning(f"A2D: failed to read knowledge file {f}: {e}")
        return "\n\n".join(parts) if parts else None

    def _a2d_build_messages(self, system_prompt: str) -> list[dict]:
        """Build LLM message list from SessionRuntime script_lines state."""
        session = self.a2d_session

        messages = [{"role": "system", "content": system_prompt}]

        for line in session.script_lines:
            if line.raw_text:
                # KV-cache-friendly: use LLM's original output verbatim.
                # This preserves （action）, exact spacing, and token sequence.
                content = line.raw_text
            else:
                # Fallback: reconstruct from fields (edited lines, legacy data).
                # edited lines have raw_text=None; we can't preserve KV cache for them.
                tts_text = line.tts_text or line.display_text
                content = f"【{line.emotion}】{line.display_text}<{tts_text}>"

            if line.speaker == "narrator":
                messages.append({
                    "role": "user",
                    "content": f"{{旁白: {content}}}",
                })
            else:
                messages.append({
                    "role": "assistant",
                    "content": f'{{"speaker":"{line.speaker}"}}\n{content}',
                })

        if len(session.script_lines) == 0:
            messages.append({
                "role": "user",
                "content": "{旁白：开场}\n可以开始对话啦。",
                # "content": "{旁白：开场}\n剧本家希望两个角色开始对话。",
            })

        logger.debug(
            f"A2D messages built: {len(messages)} messages, "
            f"{len(session.script_lines)} history lines"
        )
        for i, msg in enumerate(messages):
            logger.debug(f"  A2D msg[{i}] {msg['role']}: {msg['content']}")
        return messages

    async def _a2d_call_llm_with_retry(self, messages: list[dict]) -> str:
        """Call LLM with retry logic (3 attempts, 5s/15s backoff)."""
        last_error = None
        backoff_delays = [5, 15]
        for attempt in range(3):
            try:
                full_text = ""
                async for chunk in self.llm_model.process_message_stream(messages):
                    if isinstance(chunk, str):
                        full_text += chunk
                    elif hasattr(chunk, "content"):
                        full_text += chunk.content or ""
                    elif isinstance(chunk, dict):
                        full_text += chunk.get("content", "") or str(chunk)
                    else:
                        full_text += str(chunk)
                if full_text.strip():
                    logger.debug(
                        f"A2D LLM response ({len(full_text)} chars): "
                        f"{full_text[:200]}..."
                    )
                    return full_text
                raise RuntimeError("LLM returned empty response")
            except asyncio.TimeoutError as e:
                last_error = e
                if attempt < len(backoff_delays):
                    delay = backoff_delays[attempt]
                    logger.warning(
                        f"A2D LLM timeout attempt {attempt+1}/3, retrying in {delay}s"
                    )
                    await asyncio.sleep(delay)
            except Exception as e:
                last_error = e
                if attempt < len(backoff_delays):
                    delay = backoff_delays[attempt]
                    logger.warning(
                        f"A2D LLM error attempt {attempt+1}/3: {e}, retrying in {delay}s"
                    )
                    await asyncio.sleep(delay)

        raise last_error or RuntimeError("LLM call failed after 3 retries")

    def _a2d_parse_script_line(
        self, raw_text: str, speaker: str
    ) -> "ScriptLine | None":
        """Parse one line of LLM output into a ScriptLine.

        Expected format: 【emotion】display_text<TTS_text>（action） or 【emotion】display_text<TTS_text>
        Language-agnostic — no assumptions about ja/zh/en.
        """
        import re
        from ling_chat.schemas.script_overlay import ScriptLine

        text = raw_text.strip()
        if not text:
            return None

        # Explicit narration marker: "旁白：xxx" or "旁白:xxx" (full/half colon).
        # Priority over pure-（）heuristic. Prefix is stripped from display_text so the
        # frontend never sees the LLM marker. Non-empty content is voiceable (tts_text
        # set to content); empty content falls through to the pure-action heuristic below.
        narration_match = re.match(r"^旁白[：:]\s*(.+)$", text)
        if narration_match:
            content = narration_match.group(1).strip()
            if content:
                return ScriptLine(
                    speaker="narrator",
                    emotion="",
                    display_text=content,
                    tts_text=content,  # non-empty = can be voiced via narrator_voice_key
                    raw_text=text,  # preserve LLM original for KV-cache-friendly history
                    state="approved",
                )
            # Empty after prefix — fall through to pure-action heuristic

        # Pure action line: entire content is （...）with no dialogue.
        # LLM sometimes splits actions onto separate lines when batch_size > 1.
        # Treat as narration — no emotion, no TTS.
        if re.match(r"^（.+?）$", text):
            return ScriptLine(
                speaker="narrator",
                emotion="",
                display_text=text,
                tts_text="",  # empty = skip TTS
                raw_text=text,  # preserve for KV-cache-friendly history
                state="approved",
            )

        # Parse: 【emotion】content<TTS>（action）
        emotion_match = re.match(r"^【(.+?)】", text)
        emotion = emotion_match.group(1) if emotion_match else ""
        content = re.sub(r"^【.*?】", "", text).strip()
        if not content:
            content = text

        tts_match = re.search(r"<(.+?)>", content)
        tts_text = tts_match.group(1) if tts_match else content
        display_text = re.sub(r"<.+?>", "", content).strip()

        # Extract action （...）at end of line — preserve it as a separate field
        action = ""
        action_match = re.search(r"（(.+?)）$", display_text)
        if action_match:
            action = action_match.group(1)
            display_text = re.sub(r"（.+?）$", "", display_text).strip()

        # Defense-in-depth: strip parenthetical action leaked into TTS tag.
        # LLM sometimes writes "<你够了（摔门）>" — GSV would read the parens aloud.
        # Strip both fullwidth （）and halfwidth () content. If stripping empties the
        # text, retain original as safety net (never produce empty TTS from non-empty input).
        def _clean_tts(src: str) -> tuple[str, str]:
            cleaned = re.sub(r"[（(][^）)]+[）)]", "", src).strip()
            actions = re.findall(r"[（(]([^）)]+)[）)]", src)
            return cleaned, "、".join(actions) if actions else ""

        tts_cleaned, stripped_actions = _clean_tts(tts_text)
        if stripped_actions:
            action = (action + "、" + stripped_actions).strip("、") if action else stripped_actions
        tts_text = tts_cleaned if tts_cleaned else tts_text

        if not display_text:
            display_text = text
            tts_text = text

        return ScriptLine(
            speaker=speaker,
            emotion=emotion,
            display_text=display_text,
            tts_text=tts_text,
            action=action,
            raw_text=text,  # preserve LLM original for KV-cache-friendly history
            state="approved",
        )

    def _a2d_translate_for_tts(
        self, text: str, speaker: str
    ) -> str:
        """Translate display_text to voice_language for TTS synthesis.

        Only called when character has voice_language != display_language.
        Uses the separate translator LLM provider (NOT the main dialogue LLM)
        so translation context is fully isolated from story generation.
        On failure, returns empty string — caller should skip TTS, never send
        untranslated text to GSV with mismatched text_lang.
        """
        import os
        from ling_chat.core.llm_providers.manager import LLMManager

        cfg = self.a2d_session.characters.get(speaker) if speaker else None
        if not cfg:
            return ""

        target_lang = cfg.voice_language  # "ja", "zh", etc.
        if not target_lang or target_lang == cfg.display_language:
            return text  # no translation needed

        if not text or not text.strip():
            return ""

        lang_names = {"ja": "日语", "zh": "中文", "en": "英语"}
        target_name = lang_names.get(target_lang, target_lang)

        try:
            translator = LLMManager(llm_job="translator")
            prompt = (
                f"将以下文本翻译为{target_name}，只返回译文，不要任何解释：\n{text}"
            )
            messages = [{"role": "user", "content": prompt}]
            translated = translator.process_message(messages)  # sync, not async
            if translated and translated.strip():
                logger.info(
                    f"A2D translate: '{text[:40]}...' → '{translated[:40]}...'"
                )
                return translated.strip()
        except Exception as e:
            logger.warning(
                f"A2D translation failed for speaker={speaker}: {e}"
            )

        return ""  # Fail closed — don't send wrong-language text to GSV

    async def a2d_synthesize(self, line_id: str, text: str, speaker: str = "") -> str:
        """Synthesize TTS for a script line. Returns audio file path.

        Tries GameRole.voice_maker first (LingChat native path), falls back
        to the AIService-level tts_provider.

        Narrator routing: when speaker == "narrator", borrow the voice_maker of the
        character identified by session.narrator_voice_key. If key is None/invalid or the
        character has no voice_maker, return "" (silent fallback, pure subtitle).
        """
        import os

        # ── Narrator dispatch: reuse selected character's voice_maker ─
        if speaker == "narrator":
            vk = self.a2d_session.narrator_voice_key
            if isinstance(vk, str) and vk:
                cfg = self.a2d_session.characters.get(vk)
                if cfg and cfg.game_role and cfg.game_role.voice_maker:
                    speaker = vk  # reuse that character's voice_maker via Path 1 below
                else:
                    return ""  # silent fallback: invalid key or no voice_maker
            else:
                return ""  # silent fallback: no narrator_voice_key set

        # ── Path 1: GameRole.voice_maker (per-character, preferred) ─
        cfg = self.a2d_session.characters.get(speaker) if speaker else None
        if cfg and cfg.game_role:
            voice_maker = cfg.game_role.voice_maker
            # Ensure GSV adapter is ready
            if voice_maker.tts_provider.gsv_adapter:
                output_path = os.path.join(
                    str(voice_maker.tts_provider.temp_dir),
                    f"a2d_{line_id}.wav",
                )
                audio_data = await voice_maker.tts_provider.gsv_adapter.generate_voice(text)
                os.makedirs(os.path.dirname(output_path), exist_ok=True)
                with open(output_path, "wb") as f:
                    f.write(audio_data)
                return f"/audio/a2d_{line_id}.wav"

        # ── Path 2: AIService-level tts_provider (fallback) ─
        if not hasattr(self, 'tts_provider') or not self.tts_provider:
            raise RuntimeError("TTS provider not initialized")
        if not self.tts_provider.gsv_adapter:
            raise RuntimeError("GSV adapter not initialized")

        output_path = os.path.join(
            str(self.tts_provider.temp_dir),
            f"a2d_{line_id}.wav",
        )

        audio_data = await self.tts_provider.gsv_adapter.generate_voice(text)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(audio_data)

        return f"/audio/a2d_{line_id}.wav"
