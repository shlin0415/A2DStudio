import asyncio
import json
import traceback
import uuid

from fastapi import WebSocket, WebSocketDisconnect

from ling_chat.core.achievement_manager import achievement_manager
from ling_chat.core.logger import logger
from ling_chat.core.messaging.broker import message_broker
from ling_chat.core.service_manager import service_manager


class WebSocketManager:
    def __init__(self):
        self.active_connections: dict[str, WebSocket] = {}

    async def handle_websocket(self, websocket: WebSocket, client_id: str):
        """处理WebSocket连接的主方法"""
        # 这里不再调用 websocket.accept()，因为已经在端点中调用
        self.active_connections[client_id] = websocket

        # 创建发送任务
        send_task = asyncio.create_task(self._send_messages(websocket, client_id))

        try:
            # 处理接收的消息
            async for message in self._receive_messages(websocket):
                await self._handle_client_message(websocket, client_id, message)

        except WebSocketDisconnect:
            logger.info(f"客户端 {client_id} 正常断开连接")
        except Exception as e:
            logger.error(f"WebSocket连接错误: {e}")
            traceback.print_exc()
        finally:
            # 清理资源
            self.active_connections.pop(client_id, None)
            send_task.cancel()
            try:
                await send_task
            except asyncio.CancelledError:
                pass
            if service_manager.ai_service is not None:
                await service_manager.ai_service.remove_client(client_id)
            logger.info(f"客户端 {client_id} 连接已清理")

    async def _receive_messages(self, websocket: WebSocket):
        """接收消息的通用逻辑"""
        while True:
            try:
                data = await websocket.receive()

                # 处理断开连接
                if data.get("type") == "websocket.disconnect":
                    logger.info("收到断开连接消息")
                    break

                # 处理文本消息
                if "text" in data:
                    yield json.loads(data["text"])
                # 处理二进制消息（如果需要）
                elif "bytes" in data:
                    # 可以处理二进制消息
                    pass

            except (WebSocketDisconnect, ConnectionResetError, RuntimeError):
                break
            except json.JSONDecodeError:
                logger.error("消息JSON格式错误")
                await websocket.send_json({"type": "error", "message": "消息格式错误"})

    async def _handle_client_message(
        self, websocket: WebSocket, client_id: str, message: dict
    ):
        """处理客户端消息"""
        message_type = message.get("type")

        if message_type == "ping":
            await websocket.send_json({"type": "pong"})
        elif message_type == "message":
            await self._handle_user_message(client_id, message)
        elif message_type == "achievement.unlock_request":
            # 处理前端发来的成就解锁请求
            achievement_data = message.get("data", {})
            achievement_id = achievement_data.get("id", None)

            if achievement_id:
                logger.info(f"收到成就解锁请求: {achievement_id}")
                # 尝试解锁成就
                unlocked_info = achievement_manager.unlock(
                    achievement_id, achievement_data
                )

                if unlocked_info:
                    # 如果成就解锁成功，则广播通知
                    # 这里以后端修正后的弹窗参数数据为主
                    await self.broadcast_achievement_unlock(unlocked_info, client_id)
                else:
                    logger.info(f"成就 {achievement_id} 解锁失败或已解锁，不发送通知")
            else:
                logger.warning("收到没有ID的成就解锁请求")
        elif message_type in ("a2d.start", "a2d.continue", "a2d.retry", "a2d.regenerate_tts"):
            await self._handle_a2d_message(client_id, message_type, message)
        else:
            logger.warning(f"未知消息类型: {message_type}")

    async def _handle_user_message(self, client_id: str, message: dict):
        """处理用户发送的消息"""
        logger.info(f"来自客户端 {client_id} 的消息: {message}")

        ai_service = service_manager.get_ai_service()

        ai_service.config.last_active_client = client_id  # 更新最后一次活跃的客户端ID
        user_message = message.get("content", "")

        # --- 成就触发检查 ---
        try:
            from ling_chat.core.achievement_triggers import achievement_trigger_handler

            new_unlocks = achievement_trigger_handler.handle_user_message(user_message)
            for achievement in new_unlocks:
                await self.broadcast_achievement_unlock(achievement, client_id)
        except Exception as e:
            logger.error(f"成就触发检查失败: {e}")
        # ------------------

        # --- 冒险触发检查 ---
        try:
            from ling_chat.core.adventure_trigger import adventure_trigger_system

            all_adventures = ai_service.scripts_manager.get_all_adventures()
            chat_count = ai_service.game_status.get_chat_message_count()
            newly_unlocked = adventure_trigger_system.check_all_adventures(
                user_id=1,  # TODO: 多用户支持时使用真实user_id
                adventures=all_adventures,
                chat_count=chat_count,
                game_status=ai_service.game_status,
            )
            for adventure in newly_unlocked:
                await self.send_to_client(
                    client_id, {"type": "adventure_unlock", "data": adventure}
                )
        except Exception as e:
            logger.error(f"冒险触发检查失败: {e}")
        # ------------------

        if user_message.startswith("/开始剧本"):
            parts = user_message.split(maxsplit=1)
            script_name = parts[1].strip() if len(parts) > 1 else None
            asyncio.create_task(ai_service.start_script(script_name))
            logger.info(f"开始进行剧本模式: {script_name or '(default)'}")
        elif user_message == "/查看记忆":
            ai_service.show_current_role_memory()
        elif user_message == "/查看台词":
            ai_service.show_lines()
        else:
            if ai_service.scripts_manager.is_running:
                asyncio.create_task(
                    message_broker.enqueue_ai_script_message(client_id, user_message)
                )
            else:
                asyncio.create_task(
                    message_broker.enqueue_ai_message(client_id, user_message)
                )

    async def _send_messages(self, websocket: WebSocket, client_id: str):
        """从消息队列中获取并发送消息"""
        try:
            async for message in message_broker.subscribe(client_id):
                if message:
                    logger.info(f"向客户端 {client_id} 发送消息: {message}")
                    try:
                        await websocket.send_json(message)
                    except (WebSocketDisconnect, RuntimeError):
                        break
                    except Exception as e:
                        logger.error(f"发送消息失败: {e}")
                        break
        except Exception as e:
            logger.error(f"消息订阅异常: {e}")

    async def send_to_client(self, client_id: str, message: dict):
        """直接向指定客户端发送消息"""
        if client_id in self.active_connections:
            try:
                await self.active_connections[client_id].send_json(message)
            except Exception as e:
                logger.error(f"直接发送消息失败: {e}")

    async def broadcast_achievement_unlock(
        self, achievement_data: dict, target_client_id: str | None = None
    ):
        """
        向客户端广播成就解锁消息
        :param achievement_data: 成就数据，应包含 id, title, message, type (common/rare) 等
        :param target_client_id: 如果指定，只发送给该客户端；否则广播给所有（虽然后端架构目前是一对一，但保留广播能力）
        """
        message = {"type": "achievement.unlocked", "data": achievement_data}

        if target_client_id:
            await self.send_to_client(target_client_id, message)
        else:
            # 广播给所有连接
            for client_id in self.active_connections:
                await self.send_to_client(client_id, message)

    # ── A2D Script Editor Handler (dispatch to a2d_message_handler) ─

    async def _handle_a2d_message(
        self, client_id: str, msg_type: str, message: dict
    ):
        """Route A2D WS messages to the standalone message dispatcher."""
        from ling_chat.core.a2d_message_handler import dispatch

        ai_service = service_manager.get_ai_service()
        payload = message.get("payload", {})

        async def send(msg: dict):
            await self.send_to_client(client_id, msg)

        handled = await dispatch(msg_type, ai_service, client_id, payload, send)
        if not handled:
            logger.warning(f"A2D: no handler for message type '{msg_type}'")
            await self.send_to_client(client_id, {
                "type": "error",
                "payload": {
                    "error_type": "unknown",
                    "message": f"Unknown A2D message type: {msg_type}",
                    "detail": "",
                    "generation_id": "",
                    "retry_count": 0,
                    "max_retries": 0,
                },
            })

def _a2d_build_character_configs(ai_service) -> dict:
    """Build CharacterConfig dict by scanning all character directories.

    Scans game_data/characters/ for all subdirectories containing settings.yml,
    loads each character's configuration, and builds a CharacterConfig keyed by
    script_role_key.

    This replaces the old approach of reading only ai_service.settings (single
    character), enabling dual-character A2D sessions.
    """
    from ling_chat.core.session_runtime import CharacterConfig
    from ling_chat.utils.function import Function
    from ling_chat.utils.runtime_path import user_data_path

    configs = {}
    characters_dir = user_data_path / "game_data" / "characters"

    if not characters_dir.exists():
        logger.warning(f"A2D: characters dir not found: {characters_dir}")
        return configs

    for char_dir in sorted(characters_dir.iterdir()):
        if not char_dir.is_dir():
            continue
        if not (char_dir / "settings.yml").exists():
            continue

        try:
            settings = Function.load_character_settings(char_dir)
        except Exception as e:
            logger.warning(
                f"A2D: failed to load settings for '{char_dir.name}': {e}"
            )
            continue

        role_key = getattr(settings, 'script_role_key', None) or char_dir.name
        folder = char_dir.name
        voice_lang = getattr(
            getattr(settings, 'voice_models', None), 'voice_language', None
        ) or "ja"

        # Try to create a GameRole for TTS reuse (non-fatal if it fails)
        game_role = None
        try:
            from ling_chat.core.ai_service.type import GameRole
            game_role = GameRole(
                settings=settings,
                resource_path=str(char_dir),
                display_name=getattr(settings, 'ai_name', None) or folder,
            )
        except Exception as e:
            logger.warning(
                f"A2D: GameRole init failed for '{role_key}' "
                f"(TTS may not be available): {e}"
            )

        configs[role_key] = CharacterConfig(
            script_role_key=role_key,
            character_folder=folder,
            voice_language=voice_lang,
            display_language="zh",
            game_role=game_role,
        )

    if configs:
        logger.info(
            f"A2D character configs built: {len(configs)} characters: "
            f"{list(configs.keys())}"
        )
    else:
        logger.warning("A2D: no characters found in game_data/characters/")

    return configs


# 改进的端点函数
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket端点 - 改进版本"""
    # 首先接受连接
    await websocket.accept()

    # 后端分配client_id
    client_id = f"client_{uuid.uuid4().hex}"

    # 立即通知客户端分配的ID
    await websocket.send_json(
        {"type": "connection_established", "client_id": client_id}
    )

    service_manager.get_ai_service()  # 确保初始化AI服务
    await service_manager.add_client(client_id)

    try:
        await ws_manager.handle_websocket(websocket, client_id)
    except Exception as e:
        logger.error(f"WebSocket端点异常: {e}")
        try:
            await websocket.close(code=1011, reason="服务器错误")
        except Exception:
            pass


ws_manager = WebSocketManager()
