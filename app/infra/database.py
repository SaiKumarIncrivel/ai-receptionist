"""
Database Connection and Session Management

Provides async SQLAlchemy 2.0 engine, session factory, and dependencies
for database operations.
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.config import settings
from app.models.database import Base


# Create async engine
engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    poolclass=NullPool,
    future=True,
)

# Create session factory
async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency that provides a database session.

    Automatically handles:
    - Session creation
    - Commit on success
    - Rollback on exception
    - Session cleanup

    Usage:
        @app.get("/example")
        async def example(db: AsyncSession = Depends(get_db)):
            result = await db.execute(select(Patient))
            patients = result.scalars().all()
            return patients

    Yields:
        AsyncSession: Database session
    """
    session = async_session_factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


@asynccontextmanager
async def get_db_context() -> AsyncGenerator[AsyncSession, None]:
    """
    Context manager for database sessions outside FastAPI.

    Use this in background jobs, CLI scripts, or anywhere outside
    the FastAPI request lifecycle.

    Usage:
        async with get_db_context() as db:
            result = await db.execute(select(Patient))
            patients = result.scalars().all()

    Yields:
        AsyncSession: Database session
    """
    session = async_session_factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def init_db() -> None:
    """
    Create all database tables.

    WARNING: This is for development only. In production, use Alembic
    migrations to manage schema changes.

    Usage:
        await init_db()
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    """
    Close all database connections.

    Should be called during application shutdown to gracefully close
    all connection pools.

    Usage:
        await close_db()
    """
    await engine.dispose()


async def check_db_health() -> bool:
    """
    Check database connectivity for health checks.

    Returns:
        bool: True if database is accessible, False otherwise

    Usage:
        healthy = await check_db_health()
        if not healthy:
            return {"status": "unhealthy", "database": "unreachable"}
    """
    try:
        async with get_db_context() as db:
            await db.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
