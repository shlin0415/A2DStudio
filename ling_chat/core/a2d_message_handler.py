"""A2D Studio — lightweight message dispatcher.

Event-dispatch pattern (like EventHandlerLoader) but standalone:
does NOT require script_status, so it works for A2D's independent sessions.

Each handler is a simple async function keyed by WS message type.
The WS handler only routes — all A2D logic lives here.
"""

import traceback
from typing import Any, Callable, Coroutine

from ling_chat.core.logger import logger

# ── Type aliases ──────────────────────────────────────────

SendFn = Callable[[dict], Coroutine[Any, Any, None]]

# ── Handler registry ──────────────────────────────────────

_handlers: dict[str, Callable[..., Coroutine[Any, Any, None]]] = {}


def register(msg_type: str):
    """Decorator: register an A2D message handler."""

    def decorator(fn):
        _handlers[msg_type] = fn
        return fn

    return decorator


def get_handler(msg_type: str):
    """Look up a handler by message type. Returns None if not found."""
    return _handlers.get(msg_type)


# ── Shared helpers ────────────────────────────────────────


async def _send_a2d_characters(session, send: SendFn) -> list[dict]:
    """Scan all A2D characters, look up their DB role_ids, and send them to the frontend.

    Respects the A2D_STAGE_CHARACTERS .env var when set — only those script_role_keys
    are sent.  When empty or unset, all registered characters are sent.

    Returns the list of character dicts that were sent (for reuse by caller).
    """
    import os
    from ling_chat.game_database.managers.role_manager import RoleManager

    # ── Filter: which characters to show on stage ──────────
    stage_cfg = os.environ.get("A2D_STAGE_CHARACTERS", "")
    allowed_keys: set[str] | None = None
    if stage_cfg.strip():
        allowed_keys = {k.strip() for k in stage_cfg.split(",") if k.strip()}
        logger.info(f"A2D: stage characters filter active: {allowed_keys}")

    characters: list[dict] = []

    for role_key, cfg in session.characters.items():
        # Skip characters not in the stage whitelist (when configured)
        if allowed_keys is not None and role_key not in allowed_keys:
            continue

        folder = cfg.character_folder

        # Look up the role in the DB (synced on startup from game_data/characters/)
        db_role = RoleManager.get_main_role_by_resource_folder(folder)
        if db_role is None:
            logger.warning(
                f"A2D: no DB role found for '{role_key}' (folder={folder}) — "
                f"character will not appear on stage"
            )
            continue

        # Read defaults from settings if GameRole is available
        s = cfg.game_role.settings if cfg.game_role else None

        characters.append({
            "roleId": db_role.id,
            "roleName": getattr(s, "ai_name", None) or folder,
            "roleSubTitle": getattr(s, "ai_subtitle", None) or "",
            "thinkMessage": getattr(s, "thinking_message", None) or "正在思考中...",
            "scale": getattr(s, "scale", None) or 1.0,
            "offsetX": getattr(s, "offset_x", None) or 0.0,
            "offsetY": getattr(s, "offset_y", None) or 0.0,
            "bubbleTop": getattr(s, "bubble_top", None) or 5,
            "bubbleLeft": getattr(s, "bubble_left", None) or 20,
            "character_folder": folder,
            "script_role_key": role_key,
        })

    if characters:
        await send({"type": "a2d.characters", "payload": {"characters": characters}})
        logger.info(f"A2D: sent {len(characters)} characters to frontend")

    return characters


async def _generate_and_synthesize(ai_service, send: SendFn) -> int:
    """Stream generate + synthesize: LLM → script_line → TTS → tts_ready per line.

    Each iteration: status(thinking) → LLM → send script_line →
    status(synthesizing) → TTS → send tts_ready.
    Final: status(paused).

    On error: pops generated lines, sends error message, returns 0.
    """
    session = ai_service.a2d_session
    line_count = 0  # successfully generated lines (for batch_index)

    try:
        for i in range(session.batch_size):
            if session.stopped:
                break

            # Step 1: Generate one line (LLM returns exactly 1 line)
            await send({"type": "status", "payload": {"phase": "thinking"}})

            result = await ai_service.a2d_generate_one(
                scene_suffix=session.build_scene_prompt_suffix()
                if session.scene_config and session.scene_config.scene_description
                else None,
            )

            if not result:
                # None: (a) LLM returned nothing, or (b) action line merged into
                # previous line. Continue next iteration.
                continue

            line_count += 1
            result["payload"]["batch_index"] = line_count
            result["payload"]["batch_total"] = session.batch_size

            # Log raw LLM response for monitor extraction
            raw_preview = session.last_raw_llm_response[:2000]
            logger.info(f"A2D LLM raw response ({len(session.last_raw_llm_response)} chars):\n{raw_preview}")

            # Send script_line immediately (streaming)
            await send(result)

            pl = result.get("payload")
            if not pl:
                continue

            # Step 2: Synthesize TTS (non-fatal per line)
            await send({"type": "status", "payload": {"phase": "synthesizing"}})
            try:
                speaker = pl.get("speaker", "")
                tts_text = pl.get("tts_text", "")
                display_text = pl.get("display_text", "")

                cfg = session.characters.get(speaker) if speaker else None
                if cfg and cfg.voice_language != cfg.display_language:
                    if not tts_text or tts_text == display_text:
                        tts_text = ai_service._a2d_translate_for_tts(
                            display_text, speaker
                        )

                if tts_text:
                    audio_path = await ai_service.a2d_synthesize(
                        pl["id"], tts_text, speaker=speaker
                    )
                    await send({
                        "type": "tts_ready",
                        "payload": {"id": pl["id"], "audio_path": audio_path},
                    })
                else:
                    logger.warning(
                        f"A2D: skipping TTS for line {pl['id']} — "
                        f"no valid tts_text after translation"
                    )
            except Exception as tts_e:
                logger.warning(f"A2D TTS failed (non-fatal): {tts_e}")

        # Emit format-violation warning if >30% of dialogue lines had action in TTS.
        total_dialogue = len([l for l in session.script_lines if l.speaker != "narrator"])
        if total_dialogue > 0 and session.format_violations / total_dialogue > 0.3:
            rate = session.format_violations / total_dialogue
            logger.warning(
                f"A2D: narrator format violation rate {rate:.0%} exceeds 30% "
                f"({session.format_violations}/{total_dialogue} dialogue lines). "
                f"Consider switching narration_mode to 'merge'."
            )

        await send({"type": "status", "payload": {"phase": "paused"}})
        session.last_batch_count = line_count
        return line_count

    except Exception as e:
        logger.error(f"A2D generate+synthesize failed: {e}")
        # Pop generated lines from session
        for _ in range(line_count):
            if session.script_lines:
                session.script_lines.pop()
        session.last_batch_count = 0
        await send({
            "type": "error",
            "payload": {
                "error_type": "unknown",
                "message": str(e),
                "detail": traceback.format_exc(),
                "generation_id": "",
                "retry_count": 0,
                "max_retries": 3,
            },
        })
        return 0


# ── Message handlers ──────────────────────────────────────


@register("a2d.start")
async def _handle_start(ai_service, client_id: str, payload: dict, send: SendFn):
    """Start a new A2D script-editor session."""
    from ling_chat.api.new_chat_main import _a2d_build_character_configs

    session = ai_service.a2d_session

    # Always rebuild to pick up A2D_STAGE_CHARACTERS env changes
    session.characters = _a2d_build_character_configs(ai_service)

    session.mode = "script"
    session.paused = False
    session.format_violations = 0  # reset per-session so violation rate is fresh
    bs = payload.get("batch_size", 1)
    session.batch_size = max(1, int(bs))  # clamp to >= 1

    topic = payload.get("topic")
    if topic:
        session.update_scene(topic, "自由对话", None)

    # Narrator configuration (session-level override)
    # narration_mode: "merge" (default) | "split". Invalid values fall back to merge.
    narration_mode = payload.get("narration_mode")
    if narration_mode in ("merge", "split"):
        session.narration_mode = narration_mode
    else:
        session.narration_mode = "merge"  # default for missing/invalid

    # narrator_voice_key: script_role_key of character whose voice_maker narrator borrows.
    # Invalid key degrades silently (validated at synthesize time, not here).
    narrator_voice_key = payload.get("narrator_voice_key")
    if narrator_voice_key is None or isinstance(narrator_voice_key, str):
        session.narrator_voice_key = narrator_voice_key if narrator_voice_key else None

    # Send character list first so frontend renders sprites before first line
    await _send_a2d_characters(session, send)

    await _generate_and_synthesize(ai_service, send)


@register("a2d.continue")
async def _handle_continue(ai_service, client_id: str, payload: dict, send: SendFn):
    """Apply edits and generate the next line."""
    session = ai_service.a2d_session
    generation_id = payload.get("generation_id", "")
    edits = payload.get("edits")
    await session.handle_continue(generation_id, edits)
    await _generate_and_synthesize(ai_service, send)


@register("a2d.retry")
async def _handle_retry(ai_service, client_id: str, payload: dict, send: SendFn):
    """Regenerate the last batch after an error."""
    session = ai_service.a2d_session
    pop_count = max(session.last_batch_count, 1)
    for _ in range(pop_count):
        if session.script_lines:
            session.script_lines.pop()
    session.last_batch_count = 0
    await _generate_and_synthesize(ai_service, send)


@register("a2d.set_batch_size")
async def _handle_set_batch_size(ai_service, client_id: str, payload: dict, send: SendFn):
    """Change batch_size at runtime (between batches)."""
    bs = int(payload.get("batch_size", 1))
    ai_service.a2d_session.batch_size = max(1, bs)
    logger.info(f"A2D: batch_size set to {ai_service.a2d_session.batch_size}")


@register("a2d.regenerate_tts")
async def _handle_regenerate_tts(ai_service, client_id: str, payload: dict, send: SendFn):
    """Re-synthesize TTS for an existing line (no text regeneration).

    Translates display_text to voice_language before TTS when languages differ.
    Updates ScriptLine in session with translated tts_text.
    """
    line_id = payload.get("id", "")
    text = payload.get("text", "")

    try:
        # Look up speaker from script_lines
        speaker = ""
        session = ai_service.a2d_session
        target_line = None
        for line in session.script_lines:
            if line.id == line_id:
                speaker = line.speaker
                target_line = line
                break

        # Translate if character uses different voice language
        tts_text = text
        cfg = session.characters.get(speaker) if speaker else None
        if cfg and cfg.voice_language != cfg.display_language:
            await send({"type": "status", "payload": {"phase": "translating"}})
            translated = ai_service._a2d_translate_for_tts(text, speaker)  # sync
            if translated:
                tts_text = translated
                # Update ScriptLine so history reconstruction uses correct text
                if target_line:
                    target_line.display_text = text
                    target_line.tts_text = tts_text
            else:
                logger.warning(
                    f"A2D: translation failed for regenerate_tts line {line_id}"
                )
                await send({"type": "status", "payload": {"phase": "paused"}})
                return

        await send({"type": "status", "payload": {"phase": "synthesizing"}})
        audio_path = await ai_service.a2d_synthesize(line_id, tts_text, speaker=speaker)
        await send({
            "type": "tts_ready",
            "payload": {"id": line_id, "audio_path": audio_path},
        })
        await send({"type": "status", "payload": {"phase": "paused"}})
    except Exception as e:
        logger.error(f"A2D TTS regenerate failed: {e}")
        await send({
            "type": "error",
            "payload": {
                "error_type": "tts_error",
                "message": f"TTS synthesis failed: {e}",
                "detail": traceback.format_exc(),
                "generation_id": "",
                "retry_count": 0,
                "max_retries": 1,
            },
        })


@register("a2d.user_action")
async def _handle_user_action(ai_service, client_id: str, payload: dict, send: SendFn):
    """Log user interaction (click, edit) from frontend."""
    action = payload.get("action", "?")
    target = payload.get("target", "?")
    detail = payload.get("detail", "")
    ts = payload.get("timestamp", "")
    logger.info(f"A2D user action: {action} | target={target} | {detail} | ts={ts}")


# ── Public API ────────────────────────────────────────────


async def dispatch(
    msg_type: str,
    ai_service,
    client_id: str,
    payload: dict,
    send: SendFn,
) -> bool:
    """Route an A2D message to its handler. Returns True if handled."""
    handler = get_handler(msg_type)
    if handler is None:
        return False
    await handler(ai_service, client_id, payload, send)
    return True
