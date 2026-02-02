"""
Safety Middleware for FastAPI

Automatically applies safety pipeline to all requests and responses.
Integrates with FastAPI's middleware system.
"""

import logging
import time
from typing import Callable, Optional
from uuid import uuid4

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.safety.pipeline import (
    SafetyPipeline,
    PipelineContext,
    PipelineAction,
    get_safety_pipeline,
)

logger = logging.getLogger(__name__)


# ==================================
# Request Context
# ==================================

class SafetyRequestContext:
    """
    Stores safety context for the current request.

    Attached to request.state for access in route handlers.
    """

    def __init__(
        self,
        request_id: str,
        clinic_id: str,
        patient_id: Optional[str] = None,
        session_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ):
        self.request_id = request_id
        self.clinic_id = clinic_id
        self.patient_id = patient_id
        self.session_id = session_id
        self.ip_address = ip_address
        self.user_agent = user_agent
        self.start_time = time.time()

        # Results from safety checks
        self.input_result = None
        self.output_result = None

        # Flags
        self.safety_checked = False
        self.is_safe = True

    def to_pipeline_context(self) -> PipelineContext:
        """Convert to PipelineContext for pipeline processing."""
        return PipelineContext(
            clinic_id=self.clinic_id,
            patient_id=self.patient_id,
            session_id=self.session_id,
            request_id=self.request_id,
            ip_address=self.ip_address,
            user_agent=self.user_agent,
        )

    @property
    def elapsed_ms(self) -> float:
        """Get elapsed time in milliseconds."""
        return (time.time() - self.start_time) * 1000


# ==================================
# Safety Middleware
# ==================================

class SafetyMiddleware(BaseHTTPMiddleware):
    """
    FastAPI middleware that applies safety pipeline to requests.

    Features:
    - Automatic request ID generation
    - Clinic ID extraction from headers/path
    - Input safety checking for POST/PUT/PATCH requests
    - Security headers on all responses
    - Request timing

    Usage:
        app = FastAPI()
        app.add_middleware(
            SafetyMiddleware,
            default_clinic_id="default",
            excluded_paths=["/health", "/metrics"]
        )
    """

    def __init__(
        self,
        app: ASGIApp,
        default_clinic_id: str = "default",
        excluded_paths: Optional[list[str]] = None,
        enable_input_check: bool = True,
        enable_output_check: bool = False,  # Disabled by default (handled in routes)
        clinic_header: str = "X-Clinic-ID",
        patient_header: str = "X-Patient-ID",
        session_header: str = "X-Session-ID",
    ):
        """
        Initialize Safety Middleware.

        Args:
            app: FastAPI application
            default_clinic_id: Default clinic if not specified
            excluded_paths: Paths to skip safety checks
            enable_input_check: Check incoming request bodies
            enable_output_check: Check outgoing response bodies
            clinic_header: Header name for clinic ID
            patient_header: Header name for patient ID
            session_header: Header name for session ID
        """
        super().__init__(app)
        self.default_clinic_id = default_clinic_id
        self.excluded_paths = excluded_paths or [
            "/health",
            "/healthz",
            "/ready",
            "/metrics",
            "/docs",
            "/redoc",
            "/openapi.json",
        ]
        self.enable_input_check = enable_input_check
        self.enable_output_check = enable_output_check
        self.clinic_header = clinic_header
        self.patient_header = patient_header
        self.session_header = session_header

        logger.info(
            f"SafetyMiddleware initialized: "
            f"input_check={enable_input_check}, output_check={enable_output_check}"
        )

    async def dispatch(
        self,
        request: Request,
        call_next: Callable,
    ) -> Response:
        """Process request through safety middleware."""

        # Generate request ID
        request_id = request.headers.get("X-Request-ID", str(uuid4()))

        # Check if path is excluded
        if self._is_excluded_path(request.url.path):
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            return response

        # Extract context from headers
        clinic_id = request.headers.get(self.clinic_header, self.default_clinic_id)
        patient_id = request.headers.get(self.patient_header)
        session_id = request.headers.get(self.session_header)

        # Get client info
        ip_address = self._get_client_ip(request)
        user_agent = request.headers.get("User-Agent", "")

        # Create safety context
        safety_context = SafetyRequestContext(
            request_id=request_id,
            clinic_id=clinic_id,
            patient_id=patient_id,
            session_id=session_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )

        # Attach to request state
        request.state.safety = safety_context
        request.state.request_id = request_id
        request.state.clinic_id = clinic_id

        # Input safety check for mutation requests
        if self.enable_input_check and request.method in ["POST", "PUT", "PATCH"]:
            try:
                # Read body
                body = await request.body()
                if body:
                    body_text = body.decode("utf-8", errors="ignore")

                    # Process through safety pipeline
                    pipeline = get_safety_pipeline(clinic_id)
                    result = pipeline.process_input(
                        body_text,
                        safety_context.to_pipeline_context()
                    )

                    safety_context.input_result = result
                    safety_context.safety_checked = True

                    # Handle blocking actions
                    if not result.can_proceed:
                        return self._create_safety_response(result, request_id)

                    safety_context.is_safe = True

            except Exception as e:
                logger.error(f"Safety input check error: {e}", exc_info=True)
                # Don't block on errors - fail open but log

        # Process request
        try:
            response = await call_next(request)
        except Exception as e:
            logger.error(f"Request processing error: {e}", exc_info=True)
            return JSONResponse(
                status_code=500,
                content={
                    "error": "Internal server error",
                    "request_id": request_id,
                },
                headers=self._get_security_headers(request_id),
            )

        # Add security headers
        for header, value in self._get_security_headers(request_id).items():
            response.headers[header] = value

        # Add timing header
        response.headers["X-Response-Time-Ms"] = str(round(safety_context.elapsed_ms, 2))

        return response

    def _is_excluded_path(self, path: str) -> bool:
        """Check if path should skip safety checks."""
        for excluded in self.excluded_paths:
            if path.startswith(excluded):
                return True
        return False

    def _get_client_ip(self, request: Request) -> str:
        """Extract client IP from request."""
        # Check forwarded headers (for proxies)
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()

        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip

        # Fall back to direct connection
        if request.client:
            return request.client.host

        return "unknown"

    def _get_security_headers(self, request_id: str) -> dict[str, str]:
        """Get security headers to add to response."""
        return {
            "X-Request-ID": request_id,
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "X-XSS-Protection": "1; mode=block",
            "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
            "Cache-Control": "no-store, no-cache, must-revalidate, private",
            "Pragma": "no-cache",
        }

    def _create_safety_response(
        self,
        result,
        request_id: str,
    ) -> JSONResponse:
        """Create response for blocked requests."""

        # Map pipeline actions to HTTP status codes
        status_map = {
            PipelineAction.BLOCK: 400,
            PipelineAction.REQUIRE_CONSENT: 403,
            PipelineAction.REQUIRE_VERIFICATION: 401,
            PipelineAction.ESCALATE_CRISIS: 200,  # Special case - still respond
            PipelineAction.REDIRECT: 400,
        }

        status_code = status_map.get(result.action, 400)

        response_content = {
            "success": False,
            "action": result.action.value,
            "message": result.suggested_response,
            "request_id": request_id,
        }

        # Add crisis resources if applicable
        if result.action == PipelineAction.ESCALATE_CRISIS:
            response_content["crisis_resources"] = result.crisis_resources
            response_content["is_crisis"] = True

        # Add consent info if applicable
        if result.action == PipelineAction.REQUIRE_CONSENT:
            response_content["requires_consent"] = True
            if result.consent_check:
                response_content["missing_consents"] = [
                    c.value for c in result.consent_check.missing_consents
                ]

        return JSONResponse(
            status_code=status_code,
            content=response_content,
            headers=self._get_security_headers(request_id),
        )


# ==================================
# Dependency Functions
# ==================================

def get_safety_context(request: Request) -> Optional[SafetyRequestContext]:
    """
    FastAPI dependency to get safety context from request.

    Usage:
        @app.post("/chat")
        async def chat(
            message: str,
            safety: SafetyRequestContext = Depends(get_safety_context)
        ):
            if safety and safety.input_result:
                # Use processed text
                text = safety.input_result.processed_text
    """
    return getattr(request.state, "safety", None)


def get_request_id(request: Request) -> str:
    """Get request ID from request state."""
    return getattr(request.state, "request_id", str(uuid4()))


def get_clinic_id(request: Request) -> str:
    """Get clinic ID from request state."""
    return getattr(request.state, "clinic_id", "default")


# ==================================
# Helper Functions
# ==================================

def setup_safety_middleware(
    app: FastAPI,
    default_clinic_id: str = "default",
    **kwargs
) -> None:
    """
    Setup safety middleware on FastAPI app.

    Args:
        app: FastAPI application
        default_clinic_id: Default clinic ID
        **kwargs: Additional middleware options
    """
    app.add_middleware(
        SafetyMiddleware,
        default_clinic_id=default_clinic_id,
        **kwargs
    )
    logger.info("Safety middleware configured")


def create_safe_response(
    content: dict,
    request_id: str,
    status_code: int = 200,
) -> JSONResponse:
    """
    Create a response with security headers.

    Args:
        content: Response content
        request_id: Request ID for tracking
        status_code: HTTP status code

    Returns:
        JSONResponse with security headers
    """
    headers = {
        "X-Request-ID": request_id,
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
    }

    return JSONResponse(
        status_code=status_code,
        content=content,
        headers=headers,
    )
