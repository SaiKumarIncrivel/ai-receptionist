"""
Health Check Endpoints

Provides health, readiness, and liveness probes for monitoring,
load balancers, and Kubernetes.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.config import settings
from app.infra.database import check_db_health
from app.infra.redis import check_redis_health

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/health", tags=["Health"])

# Track application start time for uptime calculation
_start_time: Optional[datetime] = None


def set_start_time() -> None:
    """Set application start time. Called once on startup."""
    global _start_time
    _start_time = datetime.now(timezone.utc)


def get_uptime_seconds() -> Optional[float]:
    """Get application uptime in seconds."""
    if _start_time is None:
        return None
    return (datetime.now(timezone.utc) - _start_time).total_seconds()


class HealthResponse(BaseModel):
    """Basic health check response."""
    status: str
    timestamp: datetime
    version: str
    environment: str


class ReadyResponse(BaseModel):
    """Readiness check response with dependency status."""
    status: str
    timestamp: datetime
    checks: dict[str, str]


class LiveResponse(BaseModel):
    """Liveness check response."""
    status: str
    timestamp: datetime
    uptime_seconds: Optional[float] = None


class DetailedHealthResponse(BaseModel):
    """Detailed health check with all system info."""
    status: str
    timestamp: datetime
    version: str
    environment: str
    uptime_seconds: Optional[float]
    checks: dict[str, str]
    config: dict[str, str]


@router.get(
    "",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    summary="Basic health check",
    description="Returns 200 if the application is running. Does not check dependencies.",
)
async def health() -> HealthResponse:
    """
    Basic health check.

    Always returns 200 if the application is running.
    Use /health/ready for dependency checks.
    """
    return HealthResponse(
        status="healthy",
        timestamp=datetime.now(timezone.utc),
        version="1.0.0",
        environment=settings.app_env,
    )


@router.get(
    "/ready",
    response_model=ReadyResponse,
    summary="Readiness probe",
    description="Checks database and Redis connectivity. Returns 503 if any dependency is unavailable.",
    responses={
        200: {"description": "All dependencies are ready"},
        503: {"description": "One or more dependencies are unavailable"},
    },
)
async def ready() -> ReadyResponse:
    """
    Readiness probe for load balancers and Kubernetes.

    Checks:
    - PostgreSQL database connectivity
    - Redis connectivity

    Returns 503 if any check fails.
    """
    checks = {}
    all_ok = True

    # Check database
    try:
        db_ok = await check_db_health()
        checks["database"] = "ok" if db_ok else "failed"
        if not db_ok:
            all_ok = False
            logger.warning("Readiness check: Database unhealthy")
    except Exception as e:
        checks["database"] = "error"
        all_ok = False
        logger.error(f"Readiness check: Database error - {e}")

    # Check Redis
    try:
        redis_ok = await check_redis_health()
        checks["redis"] = "ok" if redis_ok else "failed"
        if not redis_ok:
            all_ok = False
            logger.warning("Readiness check: Redis unhealthy")
    except Exception as e:
        checks["redis"] = "error"
        all_ok = False
        logger.error(f"Readiness check: Redis error - {e}")

    response = ReadyResponse(
        status="ready" if all_ok else "not_ready",
        timestamp=datetime.now(timezone.utc),
        checks=checks,
    )

    # Return 503 if not ready
    if not all_ok:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=response.model_dump(mode="json"),
        )

    return response


@router.get(
    "/live",
    response_model=LiveResponse,
    status_code=status.HTTP_200_OK,
    summary="Liveness probe",
    description="Returns 200 if the process is alive. Used for container restart decisions.",
)
async def live() -> LiveResponse:
    """
    Liveness probe for Kubernetes.

    Always returns 200 if the process is running.
    Kubernetes uses this to decide if the container should be restarted.
    """
    return LiveResponse(
        status="alive",
        timestamp=datetime.now(timezone.utc),
        uptime_seconds=get_uptime_seconds(),
    )


@router.get(
    "/detailed",
    response_model=DetailedHealthResponse,
    summary="Detailed health check",
    description="Returns detailed system health. Only available in development.",
    include_in_schema=settings.is_development,
)
async def detailed() -> DetailedHealthResponse:
    """
    Detailed health check with system info.

    Only available in development mode for debugging.
    """
    if not settings.is_development:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Not found",
        )

    checks = {}

    # Check database
    try:
        db_ok = await check_db_health()
        checks["database"] = "ok" if db_ok else "failed"
    except Exception as e:
        checks["database"] = f"error: {str(e)[:50]}"

    # Check Redis
    try:
        redis_ok = await check_redis_health()
        checks["redis"] = "ok" if redis_ok else "failed"
    except Exception as e:
        checks["redis"] = f"error: {str(e)[:50]}"

    # Safe config info (no secrets)
    config = {
        "app_name": settings.app_name,
        "environment": settings.app_env,
        "debug": str(settings.debug),
        "rate_limit_rpm": str(settings.rate_limit_requests),
    }

    all_ok = all(v == "ok" for v in checks.values())

    return DetailedHealthResponse(
        status="healthy" if all_ok else "degraded",
        timestamp=datetime.now(timezone.utc),
        version="1.0.0",
        environment=settings.app_env,
        uptime_seconds=get_uptime_seconds(),
        checks=checks,
        config=config,
    )
