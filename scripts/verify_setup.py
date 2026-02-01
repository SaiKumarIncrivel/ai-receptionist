#!/usr/bin/env python3
"""
Setup Verification Script

Validates all configuration and connections before running the application.
Run this after setting up your .env file to ensure everything is configured correctly.

Usage:
    python scripts/verify_setup.py
"""

import asyncio
import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Load environment variables
from dotenv import load_dotenv
load_dotenv()


def print_header(title: str) -> None:
    """Print section header."""
    print(f"\n{'='*60}")
    print(f" {title}")
    print(f"{'='*60}")


def print_result(name: str, success: bool, message: str = "") -> None:
    """Print check result."""
    status = "[PASS]" if success else "[FAIL]"
    color = "\033[92m" if success else "\033[91m"
    reset = "\033[0m"
    msg = f" - {message}" if message else ""
    print(f"  {color}{status}{reset} {name}{msg}")


def check_env_file() -> bool:
    """Check if .env file exists."""
    env_path = project_root / ".env"
    exists = env_path.exists()
    if not exists:
        print_result(".env file", False, "File not found. Copy .env.example to .env")
    else:
        print_result(".env file", True, "Found")
    return exists


def check_required_vars() -> dict[str, bool]:
    """Check required environment variables."""
    results = {}

    required = [
        ("ANTHROPIC_API_KEY", "Required for Claude API"),
        ("DATABASE_URL", "Required for PostgreSQL"),
        ("REDIS_URL", "Required for Redis"),
        ("SECRET_KEY", "Required for security"),
    ]

    for var, description in required:
        value = os.getenv(var, "")

        # Check if set and not placeholder
        if not value:
            print_result(var, False, f"Not set - {description}")
            results[var] = False
        elif var == "ANTHROPIC_API_KEY" and value == "your-api-key-here":
            print_result(var, False, "Still using placeholder value")
            results[var] = False
        elif var == "SECRET_KEY" and value == "dev-secret-key-change-in-production":
            print_result(var, True, "Using dev key (change for production!)")
            results[var] = True
        else:
            # Mask sensitive values
            if "KEY" in var or "SECRET" in var or "PASSWORD" in var:
                masked = f"{value[:8]}...{value[-4:]}" if len(value) > 12 else "***"
            else:
                masked = value
            print_result(var, True, f"Set ({masked})")
            results[var] = True

    return results


def check_optional_vars() -> None:
    """Check optional environment variables."""
    optional = [
        ("APP_ENV", "development"),
        ("DEBUG", "false"),
        ("PORT", "8000"),
        ("CLAUDE_INTENT_MODEL", "claude-3-5-haiku-20241022"),
        ("CALENDAR_AGENT_URL", "http://localhost:8001"),
    ]

    for var, default in optional:
        value = os.getenv(var, default)
        print_result(var, True, f"{value}")


async def check_postgres() -> bool:
    """Verify PostgreSQL connection."""
    try:
        from app.infra.database import check_db_health
        healthy = await check_db_health()

        if healthy:
            print_result("PostgreSQL", True, "Connection successful")
        else:
            print_result("PostgreSQL", False, "Connection failed")
        return healthy

    except Exception as e:
        print_result("PostgreSQL", False, str(e)[:50])
        return False


async def check_redis() -> bool:
    """Verify Redis connection."""
    try:
        from app.infra.redis import check_redis_health
        healthy = await check_redis_health()

        if healthy:
            print_result("Redis", True, "Connection successful")
        else:
            print_result("Redis", False, "Connection failed (will use fallback)")
        return healthy

    except Exception as e:
        print_result("Redis", False, str(e)[:50])
        return False


async def check_anthropic() -> bool:
    """Verify Anthropic API key works."""
    api_key = os.getenv("ANTHROPIC_API_KEY", "")

    if not api_key or api_key == "your-api-key-here":
        print_result("Anthropic API", False, "API key not configured")
        return False

    try:
        from anthropic import AsyncAnthropic

        client = AsyncAnthropic(api_key=api_key)

        # Make a minimal API call to verify the key
        response = await client.messages.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=10,
            messages=[{"role": "user", "content": "Hi"}]
        )

        await client.close()

        print_result("Anthropic API", True, "Key validated successfully")
        return True

    except Exception as e:
        error_msg = str(e)
        if "authentication" in error_msg.lower() or "api_key" in error_msg.lower():
            print_result("Anthropic API", False, "Invalid API key")
        elif "rate" in error_msg.lower():
            print_result("Anthropic API", True, "Key valid (rate limited)")
            return True
        else:
            print_result("Anthropic API", False, error_msg[:50])
        return False


async def check_calendar_agent() -> bool:
    """Check if Calendar Agent is reachable."""
    url = os.getenv("CALENDAR_AGENT_URL", "http://localhost:8001")

    try:
        import httpx

        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{url}/health")

            if response.status_code == 200:
                print_result("Calendar Agent", True, f"Reachable at {url}")
                return True
            else:
                print_result("Calendar Agent", False, f"Responded with {response.status_code}")
                return False

    except Exception as e:
        print_result("Calendar Agent", False, f"Not reachable at {url}")
        return False


def check_dependencies() -> bool:
    """Check if required Python packages are installed."""
    required_packages = [
        "fastapi",
        "uvicorn",
        "pydantic",
        "pydantic_settings",
        "sqlalchemy",
        "asyncpg",
        "redis",
        "httpx",
        "anthropic",
    ]

    missing = []
    for package in required_packages:
        try:
            __import__(package.replace("-", "_"))
        except ImportError:
            missing.append(package)

    if missing:
        print_result("Python packages", False, f"Missing: {', '.join(missing)}")
        return False
    else:
        print_result("Python packages", True, "All required packages installed")
        return True


async def main():
    """Run all verification checks."""
    print("\n" + "="*60)
    print(" AI Receptionist - Setup Verification")
    print("="*60)

    all_passed = True
    critical_failed = False

    # Check .env file
    print_header("Environment File")
    if not check_env_file():
        all_passed = False
        critical_failed = True

    # Check dependencies
    print_header("Python Dependencies")
    if not check_dependencies():
        all_passed = False
        critical_failed = True

    # Check required variables
    print_header("Required Environment Variables")
    var_results = check_required_vars()
    if not all(var_results.values()):
        all_passed = False
        if not var_results.get("ANTHROPIC_API_KEY"):
            critical_failed = True

    # Check optional variables
    print_header("Optional Environment Variables")
    check_optional_vars()

    # Check services (only if we have the required config)
    print_header("Service Connections")

    # PostgreSQL
    if var_results.get("DATABASE_URL"):
        if not await check_postgres():
            all_passed = False
    else:
        print_result("PostgreSQL", False, "Skipped - DATABASE_URL not set")

    # Redis
    if var_results.get("REDIS_URL"):
        if not await check_redis():
            pass  # Redis failure is non-critical (graceful degradation)
    else:
        print_result("Redis", False, "Skipped - REDIS_URL not set")

    # Anthropic
    if var_results.get("ANTHROPIC_API_KEY"):
        if not await check_anthropic():
            all_passed = False
            critical_failed = True
    else:
        print_result("Anthropic API", False, "Skipped - ANTHROPIC_API_KEY not set")

    # Calendar Agent (optional - separate service)
    await check_calendar_agent()  # Non-critical

    # Summary
    print_header("Summary")

    if critical_failed:
        print("\n  \033[91mCRITICAL: Some required services failed.\033[0m")
        print("  Please fix the issues above before running the application.")
        print("\n  Quick fixes:")
        if not var_results.get("ANTHROPIC_API_KEY"):
            print("  1. Get an API key from https://console.anthropic.com/")
            print("     Add to .env: ANTHROPIC_API_KEY=sk-ant-...")
        print()
        return 1
    elif not all_passed:
        print("\n  \033[93mWARNING: Some optional checks failed.\033[0m")
        print("  The application may run with limited functionality.")
        print()
        return 0
    else:
        print("\n  \033[92mAll checks passed!\033[0m")
        print("  You can start the application with:")
        print("    uvicorn app.main:app --reload")
        print()
        return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
