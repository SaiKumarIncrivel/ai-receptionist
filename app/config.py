"""
Configuration Management

Uses Pydantic BaseSettings to load configuration from environment variables.
All settings can be overridden via .env file or environment variables.

Environment Variables:
    DATABASE_URL: PostgreSQL connection string (async)
    REDIS_URL: Redis connection string
    SECRET_KEY: Secret key for JWT/session signing
    RATE_LIMIT_REQUESTS: Max requests per window (default: 60)
    RATE_LIMIT_WINDOW: Time window in seconds (default: 60)
    APP_ENV: Environment name (development/staging/production)
    DEBUG: Enable debug mode (default: False)
"""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Database Configuration
    database_url: str = (
        "postgresql+asyncpg://postgres:postgres@localhost:5432/ai_receptionist"
    )
    """PostgreSQL connection URL (async driver).

    Format: postgresql+asyncpg://user:password@host:port/database
    Example: postgresql+asyncpg://postgres:postgres@localhost:5432/ai_receptionist

    Note: Uses asyncpg driver for async SQLAlchemy support.
    """

    # Redis Configuration
    redis_url: str = "redis://localhost:6379/0"
    """Redis connection URL.

    Format: redis://host:port/db
    Example: redis://localhost:6379/0

    Used for session storage and rate limiting.
    """

    # Security
    secret_key: str = "dev-secret-key-change-in-production"
    """Secret key for cryptographic operations.

    Used for:
    - JWT token signing
    - Session encryption
    - CSRF protection

    WARNING: Must be changed in production!
    Generate with: python -c "import secrets; print(secrets.token_urlsafe(32))"
    """

    # Rate Limiting
    rate_limit_requests: int = 60
    """Maximum number of requests allowed per time window.

    Default: 60 requests per minute (1 request/second average)

    This prevents abuse and ensures fair usage across all clinics.
    """

    rate_limit_window: int = 60
    """Time window for rate limiting in seconds.

    Default: 60 seconds (1 minute)

    Combined with rate_limit_requests, this creates a sliding window
    rate limiter (e.g., 60 requests per 60 seconds).
    """

    # Application Environment
    app_env: Literal["development", "staging", "production"] = "development"
    """Current application environment.

    Options:
    - development: Local development, verbose logging, debug enabled
    - staging: Pre-production testing environment
    - production: Live production environment, minimal logging
    """

    debug: bool = False
    """Enable debug mode.

    When True:
    - Detailed error messages in responses
    - Auto-reload on code changes (if using --reload)
    - SQL query logging

    Should be False in production for security.
    """

    # Application Configuration
    app_name: str = "ai-receptionist"
    """Application name."""

    host: str = "0.0.0.0"
    """Host to bind the application server."""

    port: int = 8000
    """Port to bind the application server."""

    # Redis Session Configuration
    redis_session_ttl: int = 1800
    """Redis session TTL in seconds (default: 30 minutes)."""

    # CORS Configuration
    cors_origins: str = "http://localhost:3000"
    """Comma-separated list of allowed CORS origins."""

    # Pydantic configuration
    model_config = SettingsConfigDict(
        env_file=".env",  # Load from .env file if it exists
        env_file_encoding="utf-8",
        case_sensitive=False,  # Allow DATABASE_URL or database_url
        extra="ignore",  # Ignore extra environment variables
    )

    @property
    def is_production(self) -> bool:
        """Check if running in production environment."""
        return self.app_env == "production"

    @property
    def is_development(self) -> bool:
        """Check if running in development environment."""
        return self.app_env == "development"

    @property
    def cors_origins_list(self) -> list[str]:
        """Split cors_origins into a list."""
        return [origin.strip() for origin in self.cors_origins.split(",")]

    @property
    def database_url_sync(self) -> str:
        """Get sync database URL for Alembic migrations."""
        return self.database_url.replace("postgresql+asyncpg://", "postgresql://")


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance.

    Uses lru_cache to ensure settings are loaded only once and reused
    across the application. This improves performance and ensures
    consistency.

    Returns:
        Settings: Cached settings instance

    Example:
        >>> from app.config import get_settings
        >>> settings = get_settings()
        >>> print(settings.database_url)
        postgresql+asyncpg://postgres:postgres@localhost:5432/ai_receptionist
    """
    return Settings()


# Module-level settings instance for easy imports
settings = get_settings()
