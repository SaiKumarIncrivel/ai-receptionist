"""
Chat API Endpoint.

Handles conversational messages for AI receptionist.
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Header, status
from pydantic import BaseModel, Field

from app.core.scheduling.engine import (
    SchedulingEngine,
    EngineResponse,
    get_scheduling_engine,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["Chat"])


class ChatRequest(BaseModel):
    """Chat message request."""

    message: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="User's message",
        examples=["I'd like to schedule an appointment with Dr. Smith"],
    )
    session_id: Optional[str] = Field(
        default=None,
        description="Existing session ID for conversation continuity",
        examples=["550e8400-e29b-41d4-a716-446655440000"],
    )


class ChatResponse(BaseModel):
    """Chat response."""

    message: str = Field(
        ...,
        description="Bot's response message",
    )
    session_id: str = Field(
        ...,
        description="Session ID for continuing conversation",
    )
    state: str = Field(
        ...,
        description="Current conversation state",
    )
    intent: Optional[str] = Field(
        default=None,
        description="Detected intent from user message",
    )
    confidence: Optional[float] = Field(
        default=None,
        description="Confidence score of intent classification",
    )
    booking_id: Optional[str] = Field(
        default=None,
        description="Booking ID if appointment was created",
    )
    collected_data: Optional[dict] = Field(
        default=None,
        description="Data collected so far in the conversation",
    )
    available_slots: Optional[list[dict]] = Field(
        default=None,
        description="Available appointment slots if searching",
    )
    processing_time_ms: Optional[float] = Field(
        default=None,
        description="Processing time in milliseconds",
    )


class ErrorResponse(BaseModel):
    """Error response."""

    error: str
    detail: Optional[str] = None


@router.post(
    "",
    response_model=ChatResponse,
    status_code=status.HTTP_200_OK,
    summary="Send a chat message",
    description="Send a message to the AI receptionist and get a response.",
    responses={
        200: {"description": "Successful response"},
        400: {"model": ErrorResponse, "description": "Invalid request"},
        401: {"model": ErrorResponse, "description": "Unauthorized"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
async def chat(
    request: ChatRequest,
    x_tenant_id: str = Header(
        ...,
        alias="X-Tenant-ID",
        description="Clinic/tenant identifier",
    ),
) -> ChatResponse:
    """
    Process a chat message.

    Sends the user's message through the scheduling engine which:
    - Classifies the intent
    - Extracts relevant information (slots)
    - Manages conversation state
    - Generates an appropriate response

    The session_id should be preserved across requests to maintain
    conversation context.
    """
    if not x_tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X-Tenant-ID header is required",
        )

    try:
        engine = get_scheduling_engine()
        response: EngineResponse = await engine.process(
            tenant_id=x_tenant_id,
            message=request.message,
            session_id=request.session_id,
        )

        return ChatResponse(
            message=response.message,
            session_id=response.session_id,
            state=response.state.value,
            intent=response.intent.value if response.intent else None,
            confidence=response.confidence,
            booking_id=response.booking_id,
            collected_data=response.collected_data,
            available_slots=[s.to_dict() for s in response.available_slots]
            if response.available_slots
            else None,
            processing_time_ms=response.processing_time_ms,
        )

    except Exception as e:
        logger.exception(f"Error processing chat message: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process message",
        )


@router.get(
    "/session/{session_id}",
    response_model=dict,
    summary="Get session data",
    description="Retrieve the current state of a conversation session.",
    responses={
        200: {"description": "Session data"},
        404: {"model": ErrorResponse, "description": "Session not found"},
    },
)
async def get_session(
    session_id: str,
    x_tenant_id: str = Header(
        ...,
        alias="X-Tenant-ID",
        description="Clinic/tenant identifier",
    ),
) -> dict:
    """Get session information."""
    engine = get_scheduling_engine()
    session = await engine.get_session(x_tenant_id, session_id)

    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found",
        )

    return {
        "session_id": session.session_id,
        "clinic_id": session.clinic_id,
        "state": session.state.value,
        "collected_data": session.collected_data,
        "turn_count": len(session.turns),
        "created_at": session.created_at.isoformat(),
        "updated_at": session.updated_at.isoformat(),
    }


@router.delete(
    "/session/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Reset a session",
    description="Reset a conversation session to initial state.",
)
async def reset_session(
    session_id: str,
    x_tenant_id: str = Header(
        ...,
        alias="X-Tenant-ID",
        description="Clinic/tenant identifier",
    ),
) -> None:
    """Reset session to initial state."""
    engine = get_scheduling_engine()
    session = await engine.reset_session(x_tenant_id, session_id)

    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found",
        )
