"""
Scheduling Module

Provides the scheduling engine, calendar integration, response generation,
and conversation flow management for the AI receptionist.

Usage:
    from app.core.scheduling import (
        process_message,
        get_scheduling_engine,
        get_calendar_client,
        get_response_generator,
    )

    # Process a chat message
    response = await process_message(
        tenant_id="clinic-123",
        message="I want to see Dr. Smith tomorrow",
    )
    print(response.message)  # Bot's response
    print(response.session_id)  # Session ID for continuity
"""

# Calendar Client
from app.core.scheduling.calendar_client import (
    CalendarAgentClient,
    get_calendar_client,
    TimeSlot,
    BookingResult,
    Provider,
)

# Response Generator
from app.core.scheduling.response import (
    ResponseGenerator,
    ResponseContext,
    get_response_generator,
)

# Conversation Flow
from app.core.scheduling.flow import (
    ConversationFlow,
    FlowAction,
    get_conversation_flow,
)

# Scheduling Engine (main orchestrator)
from app.core.scheduling.engine import (
    SchedulingEngine,
    EngineResponse,
    get_scheduling_engine,
    process_message,
)

__all__ = [
    # Calendar Client
    "CalendarAgentClient",
    "get_calendar_client",
    "TimeSlot",
    "BookingResult",
    "Provider",
    # Response Generator
    "ResponseGenerator",
    "ResponseContext",
    "get_response_generator",
    # Conversation Flow
    "ConversationFlow",
    "FlowAction",
    "get_conversation_flow",
    # Scheduling Engine
    "SchedulingEngine",
    "EngineResponse",
    "get_scheduling_engine",
    "process_message",
]
