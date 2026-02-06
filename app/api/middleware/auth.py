"""
API Key Authentication Middleware

Production-ready authentication with Redis caching, ContextVar pattern,
and security best practices.
"""

import hashlib
import hmac
import json
import logging
import secrets
from contextvars import ContextVar
from typing import Optional
from uuid import UUID

from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import settings
from app.infra.database import get_db
from app.infra.redis import get_redis, APP_PREFIX
from app.models.database import Clinic

logger = logging.getLogger(__name__)

# API Key header scheme
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

# ContextVar for clinic context (accessible anywhere without passing)
_clinic_context: ContextVar[Optional["ClinicContext"]] = ContextVar(
    "clinic_context",
    default=None
)

# Redis cache settings
AUTH_CACHE_PREFIX = f"{APP_PREFIX}auth:"
AUTH_CACHE_TTL = 300  # 5 minutes


class ClinicContext:
    """
    Authenticated clinic context.

    Available anywhere via get_current_clinic() after authentication.
    """

    def __init__(
        self,
        id: UUID,
        name: str,
        slug: str,
        timezone: str,
        status: str,
        rate_limit_tier: str,
        rate_limit_rpm: int,
        ehr_provider: Optional[str] = None,
        settings: Optional[dict] = None,
    ):
        self.id = id
        self.name = name
        self.slug = slug
        self.timezone = timezone
        self.status = status
        self.rate_limit_tier = rate_limit_tier
        self.rate_limit_rpm = rate_limit_rpm
        self.ehr_provider = ehr_provider
        self.settings = settings or {}

    @classmethod
    def from_clinic(cls, clinic: Clinic) -> "ClinicContext":
        """Create context from Clinic model."""
        return cls(
            id=clinic.id,
            name=clinic.name,
            slug=clinic.slug,
            timezone=clinic.timezone,
            status=clinic.status.value,
            rate_limit_tier=clinic.rate_limit_tier,
            rate_limit_rpm=clinic.rate_limit_rpm,
            ehr_provider=clinic.ehr_provider,
            settings=clinic.settings,
        )

    def to_cache_dict(self) -> dict:
        """Convert to dict for Redis caching."""
        return {
            "id": str(self.id),
            "name": self.name,
            "slug": self.slug,
            "timezone": self.timezone,
            "status": self.status,
            "rate_limit_tier": self.rate_limit_tier,
            "rate_limit_rpm": self.rate_limit_rpm,
            "ehr_provider": self.ehr_provider,
            "settings": self.settings,
        }

    @classmethod
    def from_cache_dict(cls, data: dict) -> "ClinicContext":
        """Create context from cached dict."""
        return cls(
            id=UUID(data["id"]),
            name=data["name"],
            slug=data["slug"],
            timezone=data["timezone"],
            status=data["status"],
            rate_limit_tier=data["rate_limit_tier"],
            rate_limit_rpm=data["rate_limit_rpm"],
            ehr_provider=data.get("ehr_provider"),
            settings=data.get("settings", {}),
        )

    def __repr__(self) -> str:
        return f"<ClinicContext(id={self.id}, name='{self.name}', tier='{self.rate_limit_tier}')>"


def generate_api_key(environment: str = "live") -> str:
    """
    Generate a new API key.

    Format: ar_{environment}_{32 random bytes as base64}

    Args:
        environment: "live" for production, "test" for sandbox

    Returns:
        New API key string
    """
    if environment not in ("live", "test"):
        raise ValueError("environment must be 'live' or 'test'")

    random_bytes = secrets.token_urlsafe(32)
    return f"ar_{environment}_{random_bytes}"


def hash_api_key(api_key: str) -> str:
    """
    Hash an API key for storage.

    Uses SHA-256.
    """
    return hashlib.sha256(api_key.encode()).hexdigest()


def mask_api_key(api_key: str) -> str:
    """
    Mask API key for logging.

    Shows: ar_live_abc...xyz (prefix + first 3 chars + last 3 chars)
    """
    if len(api_key) < 15:
        return "***"

    # ar_live_ is 8 chars, show 3 more + ... + last 3
    prefix_end = 11  # ar_live_abc
    return f"{api_key[:prefix_end]}...{api_key[-3:]}"


def verify_api_key_format(api_key: str) -> bool:
    """
    Verify API key has correct format.

    Valid formats: ar_live_* or ar_test_*
    """
    return api_key.startswith("ar_live_") or api_key.startswith("ar_test_")


async def get_cached_clinic(key_hash: str) -> Optional[ClinicContext]:
    """
    Get clinic context from Redis cache.

    Returns None if not cached or Redis unavailable.
    """
    try:
        redis = await get_redis()
        if redis is None:
            logger.debug("Redis unavailable for auth cache lookup")
            return None

        cache_key = f"{AUTH_CACHE_PREFIX}{key_hash}"
        data = await redis.get(cache_key)

        if data is None:
            return None

        return ClinicContext.from_cache_dict(json.loads(data))

    except Exception as e:
        logger.warning(f"Failed to get auth cache: {e}")
        return None


async def set_cached_clinic(key_hash: str, context: ClinicContext) -> None:
    """
    Cache clinic context in Redis.

    Silently fails if Redis unavailable.
    """
    try:
        redis = await get_redis()
        if redis is None:
            return

        cache_key = f"{AUTH_CACHE_PREFIX}{key_hash}"
        await redis.setex(cache_key, AUTH_CACHE_TTL, json.dumps(context.to_cache_dict()))
        logger.debug(f"Cached auth for clinic {context.id}")

    except Exception as e:
        logger.warning(f"Failed to set auth cache: {e}")


async def invalidate_cached_clinic(key_hash: str) -> None:
    """
    Invalidate cached clinic context.

    Call when API key is regenerated or clinic is modified.
    """
    try:
        redis = await get_redis()
        if redis is None:
            return

        cache_key = f"{AUTH_CACHE_PREFIX}{key_hash}"
        await redis.delete(cache_key)

    except Exception as e:
        logger.warning(f"Failed to invalidate auth cache: {e}")


async def get_clinic_by_api_key(
    api_key: str,
    db: AsyncSession,
) -> Optional[Clinic]:
    """
    Look up clinic by API key hash.

    Uses constant-time comparison for security.
    """
    key_hash = hash_api_key(api_key)

    # Query clinic by hash
    result = await db.execute(
        select(Clinic).where(
            Clinic.api_key_hash == key_hash,
            Clinic.is_deleted == False,
        )
    )

    clinic = result.scalar_one_or_none()

    if clinic is None:
        return None

    # Constant-time comparison (prevents timing attacks)
    if not hmac.compare_digest(clinic.api_key_hash, key_hash):
        return None

    return clinic


def get_current_clinic() -> ClinicContext:
    """
    Get current clinic context.

    Use this anywhere in your code after authentication.
    Raises RuntimeError if called without authentication.

    Usage:
        from app.api.middleware.auth import get_current_clinic

        async def some_function():
            clinic = get_current_clinic()
            print(clinic.id)
    """
    context = _clinic_context.get()
    if context is None:
        raise RuntimeError("No clinic context - called outside authenticated request")
    return context


def get_current_clinic_optional() -> Optional[ClinicContext]:
    """
    Get current clinic context or None.

    Use when authentication is optional.
    """
    return _clinic_context.get()


def _set_clinic_context(context: Optional[ClinicContext]) -> None:
    """Set clinic context (internal use)."""
    _clinic_context.set(context)


def set_clinic_context(context: Optional[ClinicContext]) -> None:
    """Set clinic context (public API for middleware)."""
    _clinic_context.set(context)


async def require_auth(
    request: Request,
    api_key: Optional[str] = Security(api_key_header),
    db: AsyncSession = Depends(get_db),
) -> ClinicContext:
    """
    FastAPI dependency that requires API key authentication.

    Flow:
    1. Check API key format
    2. Try Redis cache
    3. If not cached, query database
    4. Cache result in Redis
    5. Set ClinicContext

    Raises:
        HTTPException 401: No API key provided
        HTTPException 403: Invalid API key
        HTTPException 503: Service unavailable (both Redis and DB down)

    Usage:
        @app.get("/protected")
        async def protected(clinic: ClinicContext = Depends(require_auth)):
            print(clinic.name)
    """
    # Get client info for logging
    client_ip = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent", "unknown")[:100]

    # Check if API key provided
    if not api_key:
        logger.warning(f"Auth failed: No API key provided | IP: {client_ip} | UA: {user_agent}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key required",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    # Validate format
    if not verify_api_key_format(api_key):
        masked = mask_api_key(api_key) if len(api_key) > 5 else "***"
        logger.warning(f"Auth failed: Invalid key format | Key: {masked} | IP: {client_ip} | UA: {user_agent}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key format",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    masked_key = mask_api_key(api_key)
    key_hash = hash_api_key(api_key)

    # Try cache first
    context = await get_cached_clinic(key_hash)

    if context is not None:
        # Check if clinic is active
        if context.status != "active":
            logger.warning(f"Auth failed: Clinic suspended | Clinic: {context.id} | IP: {client_ip} | UA: {user_agent}")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Clinic is {context.status}",
            )

        logger.debug(f"Auth success (cached) | Clinic: {context.id} | IP: {client_ip} | UA: {user_agent}")
        _set_clinic_context(context)
        request.state.clinic = context
        return context

    # Cache miss - query database
    try:
        clinic = await get_clinic_by_api_key(api_key, db)
    except Exception as e:
        logger.error(f"Database error during auth: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service unavailable",
        )

    if clinic is None:
        logger.warning(f"Auth failed: Invalid API key | Key: {masked_key} | IP: {client_ip} | UA: {user_agent}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key",
        )

    # Check if clinic is active
    if clinic.status.value != "active":
        logger.warning(f"Auth failed: Clinic {clinic.status.value} | Clinic: {clinic.id} | IP: {client_ip} | UA: {user_agent}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Clinic is {clinic.status.value}",
        )

    # Create context
    context = ClinicContext.from_clinic(clinic)

    # Cache for next time
    await set_cached_clinic(key_hash, context)

    # Set context
    _set_clinic_context(context)
    request.state.clinic = context

    logger.debug(f"Auth success | Clinic: {context.id} | Tier: {context.rate_limit_tier} | IP: {client_ip} | UA: {user_agent}")
    return context


async def optional_auth(
    request: Request,
    api_key: Optional[str] = Security(api_key_header),
    db: AsyncSession = Depends(get_db),
) -> Optional[ClinicContext]:
    """
    FastAPI dependency for optional authentication.

    Returns None if no valid API key provided (doesn't raise error).

    Usage:
        @app.get("/public-or-private")
        async def endpoint(clinic: Optional[ClinicContext] = Depends(optional_auth)):
            if clinic:
                # Authenticated request
            else:
                # Anonymous request
    """
    if not api_key:
        return None

    try:
        return await require_auth(request, api_key, db)
    except HTTPException:
        return None


def clear_clinic_context() -> None:
    """
    Clear clinic context.

    Called at end of request to prevent context leaking.
    """
    _clinic_context.set(None)


class AuthMiddleware(BaseHTTPMiddleware):
    """
    Authentication middleware.

    Validates API keys and sets ClinicContext for downstream middleware.
    Must run BEFORE RateLimitMiddleware.
    """

    # Paths that skip authentication
    SKIP_AUTH_PATHS: set[str] = {
        "/",
        "/health",
        "/health/ready",
        "/health/live",
        "/health/detailed",
        "/docs",
        "/redoc",
        "/openapi.json",
    }

    async def dispatch(self, request: Request, call_next):
        # Skip auth for health/docs endpoints
        if request.url.path in self.SKIP_AUTH_PATHS:
            return await call_next(request)

        # Development bypass: allow ar_test_dev key in development mode
        api_key = request.headers.get("X-API-Key")
        if settings.is_development and api_key == "ar_test_dev":
            # Create a mock clinic context for development
            from uuid import UUID
            dev_context = ClinicContext(
                id=UUID("00000000-0000-0000-0000-000000000001"),
                name="Development Clinic",
                slug="dev-clinic",
                timezone="America/New_York",
                status="active",
                rate_limit_tier="enterprise",
                rate_limit_rpm=1000,
            )
            set_clinic_context(dev_context)
            request.state.clinic = dev_context
            logger.debug("Dev auth bypass enabled")
            return await call_next(request)

        # Get API key from header

        if not api_key:
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"error": "Missing API key", "detail": "X-API-Key header required"},
            )

        # Validate and authenticate
        try:
            # Import here to avoid circular import
            from app.infra.database import get_db_context

            async with get_db_context() as db:
                clinic = await get_clinic_by_api_key(api_key, db)

            if not clinic:
                return JSONResponse(
                    status_code=status.HTTP_403_FORBIDDEN,
                    content={"error": "Invalid API key", "detail": "API key not found or inactive"},
                )

            # Check if clinic is active
            if clinic.status.value != "active":
                return JSONResponse(
                    status_code=status.HTTP_403_FORBIDDEN,
                    content={"error": "Clinic inactive", "detail": f"Clinic is {clinic.status.value}"},
                )

            # Create and set context
            context = ClinicContext.from_clinic(clinic)
            set_clinic_context(context)
            request.state.clinic = context

            # Log successful auth
            client_ip = request.client.host if request.client else "unknown"
            logger.debug(f"Auth success (middleware) | Clinic: {context.id} | IP: {client_ip}")

        except Exception as e:
            logger.error(f"Auth middleware error: {e}")
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={"error": "Authentication failed", "detail": "Internal error during authentication"},
            )

        return await call_next(request)
