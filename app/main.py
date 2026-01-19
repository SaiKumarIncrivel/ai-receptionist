"""
AI Receptionist API

FastAPI application entry point that ties all components together.
"""

import logging
import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

from app.config import settings
from app.api.middleware.auth import clear_clinic_context
from app.api.middleware.rate_limit import RateLimitMiddleware
from app.api.routes import health
from app.infra.database import init_db, close_db
from app.infra.redis import RedisClient


def setup_logging() -> None:
    """Configure logging based on environment."""
    log_level = logging.DEBUG if settings.debug else logging.INFO
    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    logging.basicConfig(
        level=log_level,
        format=log_format,
    )

    # Reduce noise from third-party libraries
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(
        logging.INFO if settings.debug else logging.WARNING
    )


logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Application lifespan manager.

    Handles startup and shutdown events.
    """
    # === STARTUP ===
    setup_logging()
    logger.info(f"Starting {settings.app_name} in {settings.app_env} mode")

    # Set health check start time
    health.set_start_time()

    # Initialize database (only in development - use migrations in production)
    if settings.is_development:
        try:
            await init_db()
            logger.info("Database tables initialized")
        except Exception as e:
            logger.warning(f"Database init skipped: {e}")

    # Test Redis connection
    try:
        redis = await RedisClient.get_client()
        if redis:
            logger.info("Redis connection established")
        else:
            logger.warning("Redis unavailable - running in degraded mode")
    except Exception as e:
        logger.warning(f"Redis connection failed: {e}")

    logger.info(f"Application ready at http://{settings.host}:{settings.port}")

    yield

    # === SHUTDOWN ===
    logger.info("Shutting down application...")

    # Close Redis connection
    await RedisClient.close()
    logger.info("Redis connection closed")

    # Close database connections
    await close_db()
    logger.info("Database connections closed")

    logger.info("Shutdown complete")


app = FastAPI(
    title="AI Receptionist API",
    description="""
    Multi-tenant AI-powered medical appointment scheduling system.

    ## Features
    - 🏥 Multi-tenant clinic support
    - 🤖 AI-powered conversational scheduling
    - 🔒 HIPAA-compliant with audit logging
    - 📅 EHR integration (DrChrono, Google Calendar)
    - 📱 Multi-channel support (Web, SMS, Voice)

    ## Authentication
    All API endpoints require a valid API key in the `X-API-Key` header.

    ## Rate Limiting
    Requests are rate-limited per clinic based on their subscription tier.
    """,
    version="1.0.0",
    docs_url="/docs" if settings.is_development else None,
    redoc_url="/redoc" if settings.is_development else None,
    openapi_url="/openapi.json" if settings.is_development else None,
    lifespan=lifespan,
)

# Middleware execution order (reverse of add order):
# 1. AuthMiddleware - validates API key, sets ClinicContext
# 2. RateLimitMiddleware - uses ClinicContext for per-clinic limits
# 3. CORSMiddleware - handles CORS headers

# CORS middleware (runs last on request, first on response)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rate limit middleware (runs second - needs ClinicContext)
app.add_middleware(RateLimitMiddleware)

# Auth middleware (runs first - sets ClinicContext)
from app.api.middleware.auth import AuthMiddleware
app.add_middleware(AuthMiddleware)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    """Handle Pydantic validation errors."""
    logger.warning(f"Validation error: {exc.errors()}")
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": "Validation error",
            "detail": exc.errors(),
        },
    )


@app.exception_handler(Exception)
async def generic_exception_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    """Handle uncaught exceptions."""
    logger.exception(f"Unhandled exception: {exc}")

    # Don't expose internal errors in production
    detail = str(exc) if settings.is_development else "Internal server error"

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "Internal server error",
            "detail": detail,
        },
    )


@app.middleware("http")
async def request_lifecycle_middleware(request: Request, call_next):
    """
    Middleware for request lifecycle management.

    - Clears clinic context after each request
    - Logs request duration in debug mode
    """
    start_time = time.time()

    try:
        response = await call_next(request)
        return response
    finally:
        # Clear clinic context to prevent leaking between requests
        clear_clinic_context()

        # Log request duration in debug mode
        if settings.debug:
            duration = time.time() - start_time
            logger.debug(
                f"{request.method} {request.url.path} "
                f"completed in {duration:.3f}s"
            )


# Health check routes (no auth required)
app.include_router(health.router)


@app.get("/", tags=["Root"])
async def root() -> dict:
    """
    Root endpoint.

    Returns basic API information.
    """
    return {
        "name": settings.app_name,
        "version": "1.0.0",
        "status": "running",
        "environment": settings.app_env,
        "docs": "/docs" if settings.is_development else None,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.is_development,
        log_level="debug" if settings.debug else "info",
    )
