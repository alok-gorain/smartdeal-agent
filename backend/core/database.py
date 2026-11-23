"""Async SQLAlchemy engine and session helpers."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from core.config import settings


def make_engine(url: str | None = None, *, null_pool: bool = False) -> AsyncEngine:
    url = url or settings.database_url
    kwargs: dict = {"pool_pre_ping": True}
    if null_pool or url.startswith("sqlite"):
        kwargs = {"poolclass": NullPool}
    else:
        kwargs.update(pool_size=10, max_overflow=10)
    return create_async_engine(url, **kwargs)


engine = make_engine()
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency."""
    async with SessionLocal() as session:
        yield session


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Session for code outside request handlers (agent tools, services)."""
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def task_session() -> AsyncIterator[AsyncSession]:
    """Session for Celery tasks.

    Each task runs in its own event loop (asyncio.run), so it gets a fresh
    engine without a connection pool that could outlive the loop.
    """
    task_engine = make_engine(null_pool=True)
    maker = async_sessionmaker(task_engine, expire_on_commit=False)
    try:
        async with maker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
    finally:
        await task_engine.dispose()
