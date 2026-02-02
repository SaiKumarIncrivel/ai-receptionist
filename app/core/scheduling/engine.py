"""
Scheduling Engine - Main Orchestrator.

Coordinates all components to process user messages
and manage the complete booking flow.
"""

import logging
from dataclasses import dataclass
from typing import Optional
from datetime import datetime, timezone

from app.core.intelligence import (
    classify_intent,
    extract_slots,
    get_session_manager,
    Intent,
    IntentResult,
    ExtractedSlots,
    SessionData,
    BookingState,
)
from app.core.scheduling.calendar_client import (
    CalendarAgentClient,
    get_calendar_client,
    TimeSlot,
    BookingResult,
    Provider,
)
from app.core.scheduling.response import (
    ResponseGenerator,
    ResponseContext,
    get_response_generator,
)
from app.core.scheduling.flow import (
    ConversationFlow,
    FlowAction,
    get_conversation_flow,
)

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    """Get current UTC time as timezone-aware datetime."""
    return datetime.now(timezone.utc)


@dataclass
class EngineResponse:
    """Response from scheduling engine."""

    message: str
    session_id: str
    state: BookingState
    intent: Optional[Intent] = None
    confidence: Optional[float] = None
    booking_id: Optional[str] = None
    available_slots: Optional[list[TimeSlot]] = None
    collected_data: Optional[dict] = None
    processing_time_ms: Optional[float] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for API response."""
        result = {
            "message": self.message,
            "session_id": self.session_id,
            "state": self.state.value,
        }

        if self.intent:
            result["intent"] = self.intent.value
        if self.confidence is not None:
            result["confidence"] = self.confidence
        if self.booking_id:
            result["booking_id"] = self.booking_id
        if self.available_slots:
            result["available_slots"] = [s.to_dict() for s in self.available_slots]
        if self.collected_data:
            result["collected_data"] = self.collected_data
        if self.processing_time_ms is not None:
            result["processing_time_ms"] = self.processing_time_ms

        return result


class SchedulingEngine:
    """
    Main orchestrator for the AI receptionist.

    Coordinates:
    - Intent classification
    - Slot extraction
    - Session management
    - Calendar operations
    - Response generation
    - Conversation flow
    """

    def __init__(
        self,
        calendar_client: Optional[CalendarAgentClient] = None,
        response_generator: Optional[ResponseGenerator] = None,
        flow_manager: Optional[ConversationFlow] = None,
    ):
        """Initialize engine with optional dependencies.

        Args:
            calendar_client: Calendar Agent client
            response_generator: Response generator
            flow_manager: Conversation flow manager
        """
        self._calendar_client = calendar_client
        self._response_generator = response_generator
        self._flow_manager = flow_manager

    def _get_calendar_client(self) -> CalendarAgentClient:
        """Get calendar client."""
        if self._calendar_client is None:
            self._calendar_client = get_calendar_client()
        return self._calendar_client

    def _get_response_generator(self) -> ResponseGenerator:
        """Get response generator."""
        if self._response_generator is None:
            self._response_generator = get_response_generator()
        return self._response_generator

    def _get_flow_manager(self) -> ConversationFlow:
        """Get flow manager."""
        if self._flow_manager is None:
            self._flow_manager = get_conversation_flow()
        return self._flow_manager

    async def process(
        self,
        tenant_id: str,
        message: str,
        session_id: Optional[str] = None,
    ) -> EngineResponse:
        """Process a user message.

        Args:
            tenant_id: Clinic/tenant identifier
            message: User's message
            session_id: Optional existing session ID

        Returns:
            EngineResponse with bot reply and state
        """
        start_time = _utcnow()

        # Get or create session
        session_manager = await get_session_manager()
        session = await session_manager.get_or_create(
            clinic_id=tenant_id,
            session_id=session_id,
        )

        try:
            # Add user message to history
            await session_manager.add_message(
                clinic_id=tenant_id,
                session_id=session.session_id,
                role="user",
                content=message,
            )

            # Classify intent with session context
            context = self._build_classification_context(session)
            intent_result = await classify_intent(message, session_context=context)

            # Extract slots
            slots = await extract_slots(message)

            # Process through flow manager
            flow = self._get_flow_manager()
            action = flow.process(session, intent_result, slots)

            # Execute action and generate response
            response_text, available_slots, booking_id = await self._execute_action(
                tenant_id=tenant_id,
                session=session,
                action=action,
                intent=intent_result,
                slots=slots,
            )

            # Update session state
            session.state = action.next_state
            await session_manager.save(session)

            # Add bot response to history
            await session_manager.add_message(
                clinic_id=tenant_id,
                session_id=session.session_id,
                role="assistant",
                content=response_text,
                intent=intent_result.intent.value,
            )

            # Calculate processing time
            end_time = _utcnow()
            processing_time_ms = (end_time - start_time).total_seconds() * 1000

            return EngineResponse(
                message=response_text,
                session_id=session.session_id,
                state=action.next_state,
                intent=intent_result.intent,
                confidence=intent_result.confidence,
                booking_id=booking_id,
                available_slots=available_slots,
                collected_data=session.collected_data,
                processing_time_ms=processing_time_ms,
            )

        except Exception as e:
            logger.error(f"Error processing message: {e}", exc_info=True)

            # Return error response
            generator = self._get_response_generator()
            error_context = ResponseContext(
                state=session.state,
                user_message=message,
                collected_data=session.collected_data,
                error_message="I encountered an issue processing your request",
            )
            error_response = await generator.generate(error_context)

            return EngineResponse(
                message=error_response,
                session_id=session.session_id,
                state=session.state,
            )

    async def _execute_action(
        self,
        tenant_id: str,
        session: SessionData,
        action: FlowAction,
        intent: IntentResult,
        slots: ExtractedSlots,
    ) -> tuple[str, Optional[list[TimeSlot]], Optional[str]]:
        """Execute the determined action.

        Args:
            tenant_id: Clinic/tenant ID
            session: Session data
            action: Action to execute
            intent: Classified intent
            slots: Extracted slots

        Returns:
            Tuple of (response_text, available_slots, booking_id)
        """
        generator = self._get_response_generator()
        calendar = self._get_calendar_client()
        collected = session.collected_data

        available_slots: Optional[list[TimeSlot]] = None
        available_providers: Optional[list[Provider]] = None
        booking_id: Optional[str] = None

        # Fetch providers if needed
        if action.should_list_providers:
            available_providers = await self._list_providers(tenant_id)

        # Handle pre-defined messages
        if action.message:
            if action.message == "greeting":
                return generator.greeting(), None, None
            elif action.message == "goodbye":
                return generator.goodbye(collected.get("patient_name")), None, None
            elif action.message == "out_of_scope":
                return generator.out_of_scope(), None, None
            elif action.action_type == "handoff":
                return generator.handoff(), None, None

        # Search for available slots if needed
        if action.should_search_slots:
            available_slots = await self._search_slots(
                tenant_id=tenant_id,
                collected=collected,
            )

        # Execute booking if needed
        if action.should_book:
            booking_result = await self._create_booking(
                tenant_id=tenant_id,
                collected=collected,
            )

            if booking_result.success:
                booking_id = booking_result.booking_id
                return (
                    generator.booking_confirmed(
                        booking_id=booking_id or "CONFIRMED",
                        provider_name=collected.get("provider_name", "your doctor"),
                        date=collected.get("date_raw", collected.get("date", "scheduled")),
                        time=collected.get("time_raw", collected.get("time", "scheduled")),
                        patient_name=collected.get("patient_name"),
                    ),
                    available_slots,
                    booking_id,
                )
            else:
                return (
                    generator.booking_failed(
                        reason=booking_result.message,
                        suggestions=booking_result.suggestions,
                    ),
                    available_slots,
                    None,
                )

        # Execute cancellation if needed
        if action.should_cancel:
            cancel_result = await self._cancel_booking(
                tenant_id=tenant_id,
                booking_id=collected.get("booking_id", ""),
            )

            if cancel_result.success:
                return (
                    "Your appointment has been cancelled successfully. Is there anything else I can help you with?",
                    None,
                    None,
                )
            else:
                return (
                    f"I wasn't able to cancel the appointment. {cancel_result.message or 'Please try again or contact the front desk.'}",
                    None,
                    None,
                )

        # Show available slots
        if action.action_type == "show_slots" and available_slots:
            return generator.format_slots(available_slots), available_slots, None

        # Confirmation request
        if action.action_type == "confirm":
            return (
                generator.confirm_booking(
                    provider_name=collected.get("provider_name", ""),
                    date=collected.get("date_raw", collected.get("date", "")),
                    time=collected.get("time_raw", collected.get("time", "")),
                    patient_name=collected.get("patient_name"),
                    reason=collected.get("reason"),
                ),
                available_slots,
                None,
            )

        # Generate contextual response
        context = ResponseContext(
            state=action.next_state,
            user_message="",  # Not needed for collection prompts
            collected_data=collected,
            available_slots=available_slots,
            available_providers=available_providers,
            action=action.action_type,
        )

        response_text = await generator.generate(context, session)
        return response_text, available_slots, booking_id

    async def _search_slots(
        self,
        tenant_id: str,
        collected: dict,
    ) -> list[TimeSlot]:
        """Search for available appointment slots.

        Args:
            tenant_id: Clinic/tenant ID
            collected: Collected booking data

        Returns:
            List of available slots
        """
        calendar = self._get_calendar_client()

        # Get provider ID if we have a name
        provider_id = None
        if collected.get("provider_name"):
            provider = await calendar.find_provider_by_name(
                tenant_id=tenant_id,
                name=collected["provider_name"],
            )
            if provider:
                provider_id = provider.id
                # Store the full provider info
                collected["provider_id"] = provider.id

        # Search for slots
        slots = await calendar.find_available_slots(
            tenant_id=tenant_id,
            provider_id=provider_id,
            date_from=collected.get("date"),
            time_preference=self._get_time_preference(collected),
        )

        return slots

    async def _list_providers(
        self,
        tenant_id: str,
    ) -> list[Provider]:
        """List available providers for the clinic.

        Args:
            tenant_id: Clinic/tenant ID

        Returns:
            List of providers
        """
        calendar = self._get_calendar_client()

        try:
            providers = await calendar.list_providers(tenant_id)
            logger.debug(f"Found {len(providers)} providers for tenant {tenant_id}")
            return providers
        except Exception as e:
            logger.error(f"Failed to list providers: {e}")
            return []

    async def _create_booking(
        self,
        tenant_id: str,
        collected: dict,
    ) -> BookingResult:
        """Create a booking.

        Args:
            tenant_id: Clinic/tenant ID
            collected: Collected booking data

        Returns:
            BookingResult
        """
        calendar = self._get_calendar_client()

        # Get slot ID - in real scenario, user would select from shown slots
        slot_id = collected.get("slot_id", "")

        if not slot_id:
            # If no specific slot, search and use first available
            slots = await self._search_slots(tenant_id, collected)
            if slots:
                slot_id = slots[0].slot_id
                collected["slot_id"] = slot_id
            else:
                return BookingResult(
                    success=False,
                    error_code="no_slots",
                    message="No available slots found for that time",
                )

        return await calendar.create_booking(
            tenant_id=tenant_id,
            slot_id=slot_id,
            patient_name=collected.get("patient_name", ""),
            patient_phone=collected.get("patient_phone"),
            patient_email=collected.get("patient_email"),
            reason=collected.get("reason"),
        )

    async def _cancel_booking(
        self,
        tenant_id: str,
        booking_id: str,
    ) -> BookingResult:
        """Cancel a booking.

        Args:
            tenant_id: Clinic/tenant ID
            booking_id: Booking ID to cancel

        Returns:
            BookingResult
        """
        if not booking_id:
            return BookingResult(
                success=False,
                error_code="no_booking_id",
                message="I couldn't find your booking. Can you provide more details?",
            )

        calendar = self._get_calendar_client()
        return await calendar.cancel_booking(
            tenant_id=tenant_id,
            booking_id=booking_id,
        )

    def _build_classification_context(self, session: SessionData) -> dict:
        """Build context for intent classification.

        Args:
            session: Session data

        Returns:
            Context dict for classifier
        """
        # Get last bot question if any
        last_bot_msg = session.last_bot_question
        if not last_bot_msg:
            for turn in reversed(session.message_history):
                if turn.get("role") == "assistant":
                    last_bot_msg = turn.get("content")
                    break

        return {
            "state": session.state.value,
            "collected": session.collected_data,
            "last_bot_question": last_bot_msg,
            "turn_count": len(session.message_history),
        }

    def _get_time_preference(self, collected: dict) -> Optional[str]:
        """Extract time preference from collected data.

        Args:
            collected: Collected data

        Returns:
            Time preference string or None
        """
        time_raw = collected.get("time_raw", "")
        if not time_raw:
            return None

        time_lower = time_raw.lower()

        if any(word in time_lower for word in ["morning", "am", "early"]):
            return "morning"
        elif any(word in time_lower for word in ["afternoon", "pm", "after lunch"]):
            return "afternoon"
        elif any(word in time_lower for word in ["evening", "late", "after 5"]):
            return "evening"

        return None

    async def get_session(
        self,
        tenant_id: str,
        session_id: str,
    ) -> Optional[SessionData]:
        """Get session data.

        Args:
            tenant_id: Clinic/tenant ID
            session_id: Session ID

        Returns:
            SessionData or None
        """
        session_manager = await get_session_manager()
        return await session_manager.get(tenant_id, session_id)

    async def reset_session(
        self,
        tenant_id: str,
        session_id: str,
    ) -> Optional[SessionData]:
        """Reset a session to initial state.

        Args:
            tenant_id: Clinic/tenant ID
            session_id: Session ID

        Returns:
            Reset SessionData or None
        """
        session_manager = await get_session_manager()
        session = await session_manager.get(tenant_id, session_id)

        if session:
            session.collected_data = {}
            session.state = BookingState.IDLE
            session.message_history = []
            session.intent_history = []
            session.message_count = 0
            await session_manager.save(session)

        return session


# Singleton
_engine: Optional[SchedulingEngine] = None


def get_scheduling_engine() -> SchedulingEngine:
    """Get singleton SchedulingEngine."""
    global _engine
    if _engine is None:
        _engine = SchedulingEngine()
    return _engine


async def process_message(
    tenant_id: str,
    message: str,
    session_id: Optional[str] = None,
) -> EngineResponse:
    """Convenience function to process a message.

    Args:
        tenant_id: Clinic/tenant identifier
        message: User's message
        session_id: Optional session ID

    Returns:
        EngineResponse
    """
    engine = get_scheduling_engine()
    return await engine.process(tenant_id, message, session_id)
