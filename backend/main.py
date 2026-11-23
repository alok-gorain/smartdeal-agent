"""SmartDeal Agent API."""

import logging
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from api.router import api_router
from core.config import settings
from core.database import engine
from core.llm import model_chain
from core.logging_config import setup_logging
from core.redis_client import close_redis, ping
from services.platforms.registry import adapter_status

setup_logging(settings.log_level)
logger = logging.getLogger("smartdeal")


async def _make_checkpointer(stack: AsyncExitStack):
    """Postgres checkpointer in production (conversations survive restarts), memory otherwise."""
    if settings.is_postgres:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        saver = await stack.enter_async_context(AsyncPostgresSaver.from_conn_string(settings.checkpointer_url))
        await saver.setup()
        return saver
    from langgraph.checkpoint.memory import InMemorySaver

    return InMemorySaver()


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with AsyncExitStack() as stack:
        app.state.graph = None
        if settings.llm_enabled:
            from agents.orchestrator import build_graph

            try:
                checkpointer = await _make_checkpointer(stack)
                app.state.graph = build_graph(checkpointer)
                logger.info("Agent ready (models, in order: %s)", ", ".join(model_chain()))
            except Exception:  # noqa: BLE001
                logger.exception("Could not start the LLM agent; using quick search mode")
        else:
            logger.warning("GOOGLE_API_KEY not set: chat runs in rule-based quick search mode")
        active = [a["slug"] for a in adapter_status() if a["enabled"]]
        logger.info("Active store adapters: %s", ", ".join(active) or "none")
        yield
    await close_redis()
    await engine.dispose()


app = FastAPI(
    title="SmartDeal Agent API",
    description="Agentic price comparison across Indian e-commerce stores.",
    version="1.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router)


@app.get("/health", tags=["health"])
async def health():
    db_ok = True
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        db_ok = False
    return {
        "status": "ok" if db_ok else "degraded",
        "database": db_ok,
        "redis": await ping(),
        "llm": "gemini" if app.state.graph is not None else "quick-search mode",
        "models": model_chain() if app.state.graph is not None else [],
    }
