"""
Rate Limiting Middleware

Per-clinic rate limiting with Redis backend, proper headers, bypass logic, and logging.
"""

import logging
from typing import Optional, Tuple

from fastapi import Depends, HTTPException, Request, Response, status
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from app.api.middleware.auth import ClinicContext, get_current_clinic_optional, require_auth
from app.config import settings
from app.infra.redis import get_rate_limiter_store, RateLimiterStore

logger = logging.getLogger(__name__)

# Paths that skip rate limiting (health checks, docs)
RATE_LIMIT_SKIP_PATHS = {
    "/",
    "/health",
    "/health/ready",
    "/health/live",
    "/docs",
    "/redoc",
    "/openapi.json",
}

# Header names
HEADER_LIMIT = "X-RateLimit-Limit"
HEADER_REMAINING = "X-RateLimit-Remaining"
HEADER_USED = "X-RateLimit-Used"
HEADER_RESET = "X-RateLimit-Reset"
HEADER_RETRY_AFTER = "Retry-After"


def should_skip_rate_limit(request: Request) -> bool:
    """
    Check if request should skip rate limiting.

    Skips:
    - Health check endpoints
    - Documentation endpoints
    - OPTIONS requests (CORS preflight)
    """
    # Skip specific paths
    if request.url.path in RATE_LIMIT_SKIP_PATHS:
        return True

    # Skip CORS preflight
    if request.method == "OPTIONS":
        return True

    return False


def should_bypass_for_test_key(clinic: Optional[ClinicContext]) -> bool:
    """
    Check if test keys should bypass rate limiting.

    Only in development mode.
    """
    if clinic is None:
        return False

    # Only bypass in development
    if not settings.is_development:
        return False

    # Check if it's a test tier (could be set when using ar_test_ keys)
    # For now, we check rate_limit_tier
    return clinic.rate_limit_tier == "unlimited"


def add_rate_limit_headers(
    response: Response,
    limit: int,
    remaining: int,
    used: int,
    reset_seconds: int,
) -> None:
    """Add rate limit headers to response."""
    response.headers[HEADER_LIMIT] = str(limit)
    response.headers[HEADER_REMAINING] = str(remaining)
    response.headers[HEADER_USED] = str(used)
    response.headers[HEADER_RESET] = str(reset_seconds)


async def check_rate_limit(
    request: Request,
    clinic: Optional[ClinicContext] = Depends(get_current_clinic_optional),
) -> Tuple[bool, int, int, int, int]:
    """
    Check rate limit for current request.

    Returns:
        Tuple of (allowed, limit, remaining, used, reset_seconds)
    """
    # Skip if path should be skipped
    if should_skip_rate_limit(request):
        return (True, 0, 0, 0, 0)

    # No clinic = no rate limit (unauthenticated)
    if clinic is None:
        return (True, 0, 0, 0, 0)

    # Bypass for test keys in development
    if should_bypass_for_test_key(clinic):
        logger.debug(f"Rate limit bypassed for unlimited tier | Clinic: {clinic.id}")
        return (True, clinic.rate_limit_rpm, clinic.rate_limit_rpm, 0, 60)

    # Get rate limiter store
    store = await get_rate_limiter_store()

    # Use clinic-specific limit from ClinicContext
    identifier = f"clinic:{clinic.id}"

    # Check rate limit - store uses settings.rate_limit_* but we want clinic-specific
    # So we need to override the check with clinic.rate_limit_rpm
    allowed, remaining, reset_seconds = await store.is_allowed(identifier)

    # Recalculate based on clinic's actual limit
    # (store uses global limit, we need per-clinic)
    current_count = await store.get_current_count(identifier)
    clinic_limit = clinic.rate_limit_rpm
    clinic_remaining = max(0, clinic_limit - current_count)
    clinic_allowed = current_count <= clinic_limit
    used = current_count

    return (clinic_allowed, clinic_limit, clinic_remaining, used, reset_seconds)


async def require_rate_limit(
    request: Request,
    clinic: ClinicContext = Depends(get_current_clinic_optional),
) -> None:
    """
    FastAPI dependency that enforces rate limiting.

    Raises HTTPException 429 if rate limit exceeded.

    Usage:
        @app.get("/api/endpoint")
        async def endpoint(
            clinic: ClinicContext = Depends(require_auth),
            _: None = Depends(require_rate_limit),
        ):
            ...
    """
    allowed, limit, remaining, used, reset_seconds = await check_rate_limit(request, clinic)

    # Store in request state for middleware to add headers
    request.state.rate_limit_limit = limit
    request.state.rate_limit_remaining = remaining
    request.state.rate_limit_used = used
    request.state.rate_limit_reset = reset_seconds

    if not allowed:
        # Log warning for monitoring
        client_ip = request.client.host if request.client else "unknown"
        clinic_id = clinic.id if clinic else "unknown"
        logger.warning(
            f"Rate limit exceeded | Clinic: {clinic_id} | "
            f"Limit: {limit} | Used: {used} | IP: {client_ip} | "
            f"Path: {request.url.path}"
        )

        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": "Rate limit exceeded",
                "limit": limit,
                "used": used,
                "retry_after": reset_seconds,
            },
            headers={
                HEADER_LIMIT: str(limit),
                HEADER_REMAINING: "0",
                HEADER_USED: str(used),
                HEADER_RESET: str(reset_seconds),
                HEADER_RETRY_AFTER: str(reset_seconds),
            },
        )


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Middleware that adds rate limit headers to all responses.

    The actual rate limit check is done by the require_rate_limit dependency.
    This middleware just ensures headers are added to responses.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        # Process request
        response = await call_next(request)

        # Add rate limit headers if available in request state
        limit = getattr(request.state, "rate_limit_limit", None)
        remaining = getattr(request.state, "rate_limit_remaining", None)
        used = getattr(request.state, "rate_limit_used", None)
        reset_seconds = getattr(request.state, "rate_limit_reset", None)

        if limit is not None and limit > 0:
            add_rate_limit_headers(response, limit, remaining, used, reset_seconds)

        return response


async def require_auth_with_rate_limit(
    request: Request,
    clinic: ClinicContext = Depends(require_auth),
) -> ClinicContext:
    """
    Combined dependency: authenticate and check rate limit.

    Convenience dependency that does both auth and rate limiting.

    Usage:
        @app.get("/api/endpoint")
        async def endpoint(clinic: ClinicContext = Depends(require_auth_with_rate_limit)):
            # Authenticated and rate-limited
            ...
    """
    # Check rate limit
    allowed, limit, remaining, used, reset_seconds = await check_rate_limit(request, clinic)

    # Store in request state
    request.state.rate_limit_limit = limit
    request.state.rate_limit_remaining = remaining
    request.state.rate_limit_used = used
    request.state.rate_limit_reset = reset_seconds

    if not allowed:
        client_ip = request.client.host if request.client else "unknown"
        logger.warning(
            f"Rate limit exceeded | Clinic: {clinic.id} | "
            f"Tier: {clinic.rate_limit_tier} | Limit: {limit} | "
            f"Used: {used} | IP: {client_ip} | Path: {request.url.path}"
        )

        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": "Rate limit exceeded",
                "limit": limit,
                "used": used,
                "retry_after": reset_seconds,
                "tier": clinic.rate_limit_tier,
            },
            headers={
                HEADER_LIMIT: str(limit),
                HEADER_REMAINING: "0",
                HEADER_USED: str(used),
                HEADER_RESET: str(reset_seconds),
                HEADER_RETRY_AFTER: str(reset_seconds),
            },
        )

    return clinic


async def reset_clinic_rate_limit(clinic_id: str) -> bool:
    """
    Reset rate limit for a clinic.

    Use for admin operations or after upgrading a clinic's tier.

    Args:
        clinic_id: Clinic UUID string

    Returns:
        True if reset successful
    """
    store = await get_rate_limiter_store()
    identifier = f"clinic:{clinic_id}"
    return await store.reset(identifier)
