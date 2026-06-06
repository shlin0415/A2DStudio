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


async def _generate_and_synthesize(ai_service, send: SendFn) -> str | None:
    """Generate one script line + synthesize TTS. Returns generation_id or None.

    Sends: status(thinking) → script_line → status(synthesizing) → tts_ready → status(paused)
    On error: sends error message, returns None.
    """
    try:
        # Step 1: Generate text (LLM decides speaker)
        send({"type": "status", "payload": {"phase": "thinking"}})

        session = ai_service.a2d_session
        result = await ai_service.a2d_generate_next(
            scene_suffix=session.build_scene_prompt_suffix()
            if session.scene_config and session.scene_config.scene_description
            else None,
        )

        if not result:
            raise RuntimeError("LLM returned empty result")

        await send(result)
        gen_id = result.get("payload", {}).get("id", "")

        # Step 2: Synthesize TTS (non-fatal on failure)
        pl = result.get("payload")
        if pl:
            await send({"type": "status", "payload": {"phase": "synthesizing"}})
            try:
                speaker = pl.get("speaker", "")
                audio_path = await ai_service.a2d_synthesize(
                    pl["id"], pl["tts_text"], speaker=speaker
                )
                await send({
                    "type": "tts_ready",
                    "payload": {"id": pl["id"], "audio_path": audio_path},
                })
            except Exception as tts_e:
                logger.warning(f"A2D TTS failed (non-fatal): {tts_e}")

        await send({"type": "status", "payload": {"phase": "paused"}})
        return gen_id

    except Exception as e:
        logger.error(f"A2D generate+synthesize failed: {e}")
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
        return None


# ── Message handlers ──────────────────────────────────────


@register("a2d.start")
async def _handle_start(ai_service, client_id: str, payload: dict, send: SendFn):
    """Start a new A2D script-editor session."""
    from ling_chat.api.new_chat_main import _a2d_build_character_configs

    session = ai_service.a2d_session

    if not session.characters:
        session.characters = _a2d_build_character_configs(ai_service)

    session.mode = "script"
    session.paused = False
    session.batch_size = 1

    topic = payload.get("topic")
    if topic:
        session.update_scene(topic, "自由对话", None)

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
    """Regenerate the last line after an error."""
    session = ai_service.a2d_session
    if session.script_lines:
        session.script_lines.pop()
    await _generate_and_synthesize(ai_service, send)


@register("a2d.regenerate_tts")
async def _handle_regenerate_tts(ai_service, client_id: str, payload: dict, send: SendFn):
    """Re-synthesize TTS for an existing line (no text regeneration)."""
    line_id = payload.get("id", "")
    text = payload.get("text", "")

    await send({"type": "status", "payload": {"phase": "synthesizing"}})

    try:
        # Look up speaker from script_lines
        speaker = ""
        session = ai_service.a2d_session
        for line in session.script_lines:
            if line.id == line_id:
                speaker = line.speaker
                break

        audio_path = await ai_service.a2d_synthesize(line_id, text, speaker=speaker)
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
