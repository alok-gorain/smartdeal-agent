"""Runs one chat turn (LLM graph or rule-based fallback) and stores the UI transcript."""

import json
import logging
import time
from collections.abc import Awaitable, Callable

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from agents.fallback import run_fallback
from agents.tools import THINKING_MESSAGES
from core.redis_client import get_redis
from services.platforms.registry import active_adapters

logger = logging.getLogger(__name__)

Emit = Callable[[str], Awaitable[None]]

TRANSCRIPT_TTL = 7 * 24 * 3600
_memory_transcripts: dict[str, list[dict]] = {}


def _text(message: AIMessage) -> str:
    text = message.text
    return text if isinstance(text, str) else str(text)


def _stores_label() -> str:
    labels = []
    for a in active_adapters():
        if a.slug == "catalog":
            continue
        labels.append("all stores via Google Shopping" if a.slug == "google_shopping" else a.label)
    return ", ".join(labels) if labels else "the SmartDeal catalog"


def _merge_blocks(blocks: list[dict]) -> list[dict]:
    """Keep the latest block of each kind (products, comparison, history, ...), in order."""
    latest: dict[str, dict] = {}
    for b in blocks:
        key = b["kind"] + (f":{b['data'].get('product_id')}" if b["kind"] in ("history", "discount", "timing") else "")
        latest.pop(key, None)
        latest[key] = b
    merged = list(latest.values())
    # A one-product search next to a full comparison of that product only repeats it
    if any(b["kind"] == "comparison" for b in merged):
        merged = [b for b in merged if not (b["kind"] == "products" and len(b["data"].get("groups", [])) <= 2)]
    return merged


async def run_llm_turn(graph, session_id: str, text: str, emit: Emit) -> dict:
    config = {"configurable": {"thread_id": session_id}, "recursion_limit": 25}
    blocks: list[dict] = []
    final = ""
    async for chunk in graph.astream({"messages": [HumanMessage(text)]}, config, stream_mode="updates"):
        for node, payload in chunk.items():
            updates = payload if isinstance(payload, list) else [payload]
            for update in updates:
                if update is None:
                    continue
                if not isinstance(update, dict):
                    update = getattr(update, "update", None) or {}
                for msg in update.get("messages", []):
                    if isinstance(msg, AIMessage):
                        if msg.tool_calls:
                            for call in msg.tool_calls:
                                template = THINKING_MESSAGES.get(call["name"], "⚙️ Working…")
                                await emit(template.format(stores=_stores_label()))
                        elif _text(msg).strip():
                            final = _text(msg)
                    elif isinstance(msg, ToolMessage) and msg.artifact:
                        blocks.append(msg.artifact)
    return {"content": final or "I couldn't produce an answer. Please try rephrasing.", "blocks": _merge_blocks(blocks)}


async def run_turn(graph, session_id: str, text: str, emit: Emit) -> dict:
    started = time.monotonic()
    if graph is not None:
        try:
            result = await run_llm_turn(graph, session_id, text, emit)
        except Exception as exc:  # noqa: BLE001 - model quota/key/network errors
            logger.exception("LLM turn failed; using rule-based fallback")
            await emit("⚠️ AI model unavailable — using quick search mode…")
            result = await run_fallback(session_id, text, emit)
            result["content"] = (
                f"_The AI model is unavailable right now ({exc.__class__.__name__}), so this is a quick-mode answer._\n\n"
                + result["content"]
            )
    else:
        result = await run_fallback(session_id, text, emit)
    result["blocks"] = _merge_blocks(result["blocks"])
    logger.info("turn %s done in %.1fs (%d blocks)", session_id, time.monotonic() - started, len(result["blocks"]))
    await save_transcript(session_id, [{"role": "user", "content": text}, {"role": "assistant", **result}])
    return result


async def save_transcript(session_id: str, entries: list[dict]) -> None:
    key = f"transcript:{session_id}"
    try:
        redis = get_redis()
        pipe = redis.pipeline()
        for e in entries:
            pipe.rpush(key, json.dumps(e, default=str))
        pipe.ltrim(key, -100, -1)
        pipe.expire(key, TRANSCRIPT_TTL)
        await pipe.execute()
    except Exception:  # noqa: BLE001 - Redis down: keep it in memory
        _memory_transcripts.setdefault(session_id, []).extend(entries)
        del _memory_transcripts[session_id][:-100]


async def load_transcript(session_id: str) -> list[dict]:
    try:
        raw = await get_redis().lrange(f"transcript:{session_id}", 0, -1)
        if raw:
            return [json.loads(r) for r in raw]
    except Exception:  # noqa: BLE001
        pass
    return _memory_transcripts.get(session_id, [])
