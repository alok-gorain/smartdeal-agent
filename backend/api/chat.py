"""WebSocket chat. Protocol:

client -> {"message": "ANC earbuds under 3000"}
server -> {"type": "thinking", "content": "🔍 Searching Amazon, Flipkart…"}   (0..n)
server -> {"type": "response", "content": "<markdown>", "blocks": [{"kind": ..., "data": ...}]}
server -> {"type": "error", "content": "..."}
"""

import asyncio
import logging
import re

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from agents.runner import load_transcript, run_turn

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])

_SESSION_RE = re.compile(r"^[A-Za-z0-9_-]{6,64}$")
MAX_MESSAGE_CHARS = 1000
MIN_SECONDS_BETWEEN_MESSAGES = 1.0


@router.websocket("/ws/chat/{session_id}")
async def chat_ws(websocket: WebSocket, session_id: str):
    if not _SESSION_RE.match(session_id):
        await websocket.close(code=1008, reason="invalid session id")
        return
    await websocket.accept()
    graph = getattr(websocket.app.state, "graph", None)
    loop = asyncio.get_running_loop()
    last_message_at = 0.0

    async def emit(text: str) -> None:
        await websocket.send_json({"type": "thinking", "content": text})

    try:
        while True:
            data = await websocket.receive_json()
            message = str(data.get("message", "")).strip()[:MAX_MESSAGE_CHARS]
            if not message:
                continue
            if loop.time() - last_message_at < MIN_SECONDS_BETWEEN_MESSAGES:
                await websocket.send_json({"type": "error", "content": "You're sending messages too fast."})
                continue
            last_message_at = loop.time()
            try:
                result = await run_turn(graph, session_id, message, emit)
                await websocket.send_json({"type": "response", **result})
            except WebSocketDisconnect:
                raise
            except Exception:  # noqa: BLE001
                logger.exception("chat turn failed for session %s", session_id)
                await websocket.send_json(
                    {"type": "error", "content": "Something went wrong while answering. Please try again."}
                )
    except WebSocketDisconnect:
        logger.info("session %s disconnected", session_id)
    except ValueError:  # bad JSON from the client
        await websocket.close(code=1003)


@router.get("/api/chat/{session_id}/history", tags=["chat"])
async def chat_history(session_id: str):
    """Messages of a session, so the UI can restore a conversation after reload."""
    if not _SESSION_RE.match(session_id):
        return []
    return await load_transcript(session_id)
