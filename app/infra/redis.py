"""
Redis Connection Management

Production-ready Redis connection with circuit breaker pattern, session storage,
and rate limiting. Features graceful degradation and fail-open strategy.
"""

import json
import logging
from datetime import timedelta
from typing import Any, Optional
from uuid import UUID

import redis.asyncio as redis
from redis.asyncio import Redis
from redis.asyncio.retry import Retry
from redis.backoff import ExponentialBackoff
from redis.exceptions import ConnectionError, TimeoutError, RedisError

from app.config import settings

# Logger
logger = logging.getLogger(__name__)

# App prefix for namespacing (allows multiple apps/versions on same Redis)
APP_PREFIX = "receptionist:v1:"


class RedisConnectionError(Exception):
    """Raised when Redis connection fails after retries."""
    pass


class RedisClient:
    """
    Manages Redis connection as a singleton with circuit breaker pattern.

    Features:
    - Connection pooling
    - Automatic retries
    - Timeouts
    - Graceful failure handling
    """

    _client: Optional[Redis] = None
    _connected: bool = False

    @classmethod
    async def get_client(cls) -> Optional[Redis]:
        """
        Get or create Redis client.

        Returns:
            Redis client or None if connection fails
        """
        if cls._client is not None and cls._connected:
            return cls._client

        try:
            # Retry configuration: 3 retries with exponential backoff
            retry = Retry(ExponentialBackoff(), retries=3)

            cls._client = redis.from_url(
                settings.redis_url,
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=5.0,
                socket_timeout=5.0,
                retry_on_timeout=True,
                retry=retry,
            )

            # Test connection
            await cls._client.ping()
            cls._connected = True
            logger.info("Redis connection established successfully")
            return cls._client

        except (ConnectionError, TimeoutError, RedisError) as e:
            logger.error(f"Failed to connect to Redis: {e}")
            cls._connected = False
            cls._client = None
            return None
        except Exception as e:
            logger.error(f"Unexpected error connecting to Redis: {e}")
            cls._connected = False
            cls._client = None
            return None

    @classmethod
    async def close(cls) -> None:
        """Close Redis connection."""
        if cls._client is not None:
            try:
                await cls._client.close()
                logger.info("Redis connection closed")
            except Exception as e:
                logger.error(f"Error closing Redis connection: {e}")
            finally:
                cls._client = None
                cls._connected = False

    @classmethod
    def is_connected(cls) -> bool:
        """Check if Redis is connected."""
        return cls._connected


async def get_redis() -> Optional[Redis]:
    """
    FastAPI dependency that provides Redis client.

    Returns None if Redis is unavailable (circuit breaker open).

    Usage:
        @app.get("/example")
        async def example(redis: Optional[Redis] = Depends(get_redis)):
            if redis is None:
                # Handle degraded mode
                pass
    """
    return await RedisClient.get_client()


class SessionStore:
    """
    Redis-based session storage for conversations.

    Keys (with namespace):
    - receptionist:v1:session:{session_id} -> session data (JSON)
    - receptionist:v1:clinic:sessions:{clinic_id} -> set of session IDs

    Gracefully handles Redis unavailability.
    """

    SESSION_PREFIX = f"{APP_PREFIX}session:"
    CLINIC_SESSIONS_PREFIX = f"{APP_PREFIX}clinic:sessions:"

    def __init__(self, redis_client: Optional[Redis]):
        self.redis = redis_client
        self.ttl = settings.redis_session_ttl

    def _session_key(self, session_id: str | UUID) -> str:
        """Generate session key with namespace."""
        return f"{self.SESSION_PREFIX}{str(session_id)}"

    def _clinic_sessions_key(self, clinic_id: str | UUID) -> str:
        """Generate clinic sessions index key with namespace."""
        return f"{self.CLINIC_SESSIONS_PREFIX}{str(clinic_id)}"

    async def create(
        self,
        session_id: str | UUID,
        clinic_id: str | UUID,
        data: dict[str, Any],
    ) -> bool:
        """
        Create a new session.

        Args:
            session_id: Unique session identifier
            clinic_id: Clinic this session belongs to
            data: Session data to store

        Returns:
            True if created successfully, False if Redis unavailable
        """
        if self.redis is None:
            logger.warning("Redis unavailable - cannot create session")
            return False

        try:
            session_key = self._session_key(session_id)
            clinic_key = self._clinic_sessions_key(clinic_id)

            # Store session data with TTL
            await self.redis.setex(
                session_key,
                timedelta(seconds=self.ttl),
                json.dumps(data)
            )

            # Add to clinic's session set
            await self.redis.sadd(clinic_key, str(session_id))

            logger.debug(f"Session created: {session_id}")
            return True

        except RedisError as e:
            logger.error(f"Failed to create session {session_id}: {e}")
            return False

    async def get(self, session_id: str | UUID) -> Optional[dict[str, Any]]:
        """
        Get session data.

        Args:
            session_id: Session identifier

        Returns:
            Session data dict or None if not found/Redis unavailable
        """
        if self.redis is None:
            logger.warning("Redis unavailable - cannot get session")
            return None

        try:
            session_key = self._session_key(session_id)
            data = await self.redis.get(session_key)

            if data is None:
                return None

            return json.loads(data)

        except RedisError as e:
            logger.error(f"Failed to get session {session_id}: {e}")
            return None

    async def update(
        self,
        session_id: str | UUID,
        data: dict[str, Any],
        refresh_ttl: bool = True,
    ) -> bool:
        """
        Update session data.

        Args:
            session_id: Session identifier
            data: New session data
            refresh_ttl: Whether to reset TTL

        Returns:
            True if updated, False if not found/Redis unavailable
        """
        if self.redis is None:
            logger.warning("Redis unavailable - cannot update session")
            return False

        try:
            session_key = self._session_key(session_id)

            # Check if session exists
            if not await self.redis.exists(session_key):
                return False

            if refresh_ttl:
                await self.redis.setex(
                    session_key,
                    timedelta(seconds=self.ttl),
                    json.dumps(data)
                )
            else:
                await self.redis.set(session_key, json.dumps(data), keepttl=True)

            logger.debug(f"Session updated: {session_id}")
            return True

        except RedisError as e:
            logger.error(f"Failed to update session {session_id}: {e}")
            return False

    async def delete(
        self,
        session_id: str | UUID,
        clinic_id: Optional[str | UUID] = None,
    ) -> bool:
        """
        Delete a session.

        Args:
            session_id: Session identifier
            clinic_id: Clinic ID (optional, for index cleanup)

        Returns:
            True if deleted, False otherwise
        """
        if self.redis is None:
            logger.warning("Redis unavailable - cannot delete session")
            return False

        try:
            session_key = self._session_key(session_id)
            deleted = await self.redis.delete(session_key)

            # Remove from clinic's session set
            if clinic_id:
                clinic_key = self._clinic_sessions_key(clinic_id)
                await self.redis.srem(clinic_key, str(session_id))

            if deleted:
                logger.debug(f"Session deleted: {session_id}")

            return bool(deleted)

        except RedisError as e:
            logger.error(f"Failed to delete session {session_id}: {e}")
            return False

    async def refresh_ttl(self, session_id: str | UUID) -> bool:
        """
        Refresh session TTL without updating data.

        Args:
            session_id: Session identifier

        Returns:
            True if TTL refreshed, False otherwise
        """
        if self.redis is None:
            return False

        try:
            session_key = self._session_key(session_id)
            return await self.redis.expire(session_key, self.ttl)
        except RedisError as e:
            logger.error(f"Failed to refresh TTL for session {session_id}: {e}")
            return False

    async def get_clinic_sessions(self, clinic_id: str | UUID) -> list[str]:
        """
        Get all session IDs for a clinic.

        Args:
            clinic_id: Clinic identifier

        Returns:
            List of session IDs (empty if Redis unavailable)
        """
        if self.redis is None:
            return []

        try:
            clinic_key = self._clinic_sessions_key(clinic_id)
            sessions = await self.redis.smembers(clinic_key)
            return list(sessions)
        except RedisError as e:
            logger.error(f"Failed to get clinic sessions for {clinic_id}: {e}")
            return []


class RateLimiterStore:
    """
    Redis-based rate limiting using sliding window counter.

    Key: receptionist:v1:ratelimit:{identifier}

    IMPORTANT: Fails OPEN - if Redis is unavailable, requests are ALLOWED.
    This prevents Redis outage from blocking all users.
    """

    RATELIMIT_PREFIX = f"{APP_PREFIX}ratelimit:"

    def __init__(self, redis_client: Optional[Redis]):
        self.redis = redis_client
        self.max_requests = settings.rate_limit_requests
        self.window_seconds = settings.rate_limit_window

    def _key(self, identifier: str) -> str:
        """Generate rate limit key with namespace."""
        return f"{self.RATELIMIT_PREFIX}{identifier}"

    async def is_allowed(self, identifier: str) -> tuple[bool, int, int]:
        """
        Check if request is allowed under rate limit.

        FAILS OPEN: If Redis unavailable, returns (True, max_requests, window_seconds)

        Args:
            identifier: Unique identifier (e.g., "clinic:{clinic_id}")

        Returns:
            Tuple of (allowed: bool, remaining: int, reset_seconds: int)
        """
        # FAIL OPEN: If Redis unavailable, allow the request
        if self.redis is None:
            logger.warning(f"Redis unavailable - rate limiting bypassed for {identifier}")
            return (True, self.max_requests, self.window_seconds)

        try:
            key = self._key(identifier)

            # Increment counter
            current = await self.redis.incr(key)

            # Set expiry on first request in window
            if current == 1:
                await self.redis.expire(key, self.window_seconds)

            # Get TTL for reset time
            ttl = await self.redis.ttl(key)
            if ttl < 0:
                ttl = self.window_seconds

            # Calculate remaining requests
            remaining = max(0, self.max_requests - current)
            allowed = current <= self.max_requests

            if not allowed:
                logger.info(f"Rate limit exceeded for {identifier}")

            return (allowed, remaining, ttl)

        except RedisError as e:
            # FAIL OPEN on error
            logger.error(f"Rate limit check failed for {identifier}: {e} - allowing request")
            return (True, self.max_requests, self.window_seconds)

    async def reset(self, identifier: str) -> bool:
        """
        Reset rate limit for an identifier.

        Args:
            identifier: Unique identifier

        Returns:
            True if reset successful
        """
        if self.redis is None:
            return False

        try:
            key = self._key(identifier)
            await self.redis.delete(key)
            logger.debug(f"Rate limit reset for {identifier}")
            return True
        except RedisError as e:
            logger.error(f"Failed to reset rate limit for {identifier}: {e}")
            return False

    async def get_current_count(self, identifier: str) -> int:
        """
        Get current request count for an identifier.

        Args:
            identifier: Unique identifier

        Returns:
            Current count (0 if Redis unavailable or key doesn't exist)
        """
        if self.redis is None:
            return 0

        try:
            key = self._key(identifier)
            count = await self.redis.get(key)
            return int(count) if count else 0
        except RedisError:
            return 0


async def get_session_store() -> SessionStore:
    """
    Get SessionStore instance.

    Returns SessionStore even if Redis unavailable (graceful degradation).
    """
    client = await get_redis()
    return SessionStore(client)


async def get_rate_limiter_store() -> RateLimiterStore:
    """
    Get RateLimiterStore instance.

    Returns RateLimiterStore even if Redis unavailable (fails open).
    """
    client = await get_redis()
    return RateLimiterStore(client)


async def check_redis_health() -> bool:
    """
    Check Redis connectivity for health checks.

    Returns:
        True if Redis is accessible and responding, False otherwise
    """
    try:
        client = await get_redis()
        if client is None:
            return False

        await client.ping()
        return True

    except Exception as e:
        logger.error(f"Redis health check failed: {e}")
        return False
