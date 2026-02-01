"""
Conversation Flow Manager.

Manages the state machine for booking conversations,
determining next states and actions based on intent and collected data.
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

from app.core.intelligence.intent.types import Intent, ConfirmationType, IntentResult
from app.core.intelligence.slots.types import ExtractedSlots
from app.core.intelligence.session.models import SessionData
from app.core.intelligence.session.state import (
    BookingState,
    can_transition,
    is_terminal_state,
)

logger = logging.getLogger(__name__)


@dataclass
class FlowAction:
    """Action determined by flow manager."""

    next_state: BookingState
    action_type: str  # collect, confirm, book, cancel, show_slots, handoff, respond
    prompt_for: Optional[str] = None  # What to ask for next
    message: Optional[str] = None  # Pre-defined message to send
    should_search_slots: bool = False  # Whether to search for available slots
    should_book: bool = False  # Whether to attempt booking
    should_cancel: bool = False  # Whether to cancel booking
    metadata: dict = field(default_factory=dict)


class ConversationFlow:
    """
    State machine manager for booking conversations.

    Determines the next state and action based on:
    - Current state
    - Detected intent
    - Extracted slots
    - What information is still needed
    """

    # Required fields for booking
    REQUIRED_FIELDS = ["provider_name", "date", "time", "patient_name"]
    OPTIONAL_FIELDS = ["patient_phone", "reason"]

    def __init__(self):
        """Initialize flow manager."""
        pass

    def process(
        self,
        session: SessionData,
        intent: IntentResult,
        slots: ExtractedSlots,
    ) -> FlowAction:
        """Process user input and determine next action.

        Args:
            session: Current session data
            intent: Classified intent
            slots: Extracted slots

        Returns:
            FlowAction with next state and action
        """
        current_state = session.state
        collected = session.collected_data

        # Merge new slots into collected data
        self._merge_slots(collected, slots)

        # Handle special intents first (these override state flow)
        if intent.intent == Intent.HANDOFF:
            return FlowAction(
                next_state=BookingState.HANDED_OFF,
                action_type="handoff",
                message="Transferring to staff",
            )

        if intent.intent == Intent.GOODBYE:
            return FlowAction(
                next_state=BookingState.IDLE,
                action_type="respond",
                message="goodbye",
            )

        if intent.intent == Intent.OUT_OF_SCOPE:
            return FlowAction(
                next_state=current_state,  # Stay in current state
                action_type="respond",
                message="out_of_scope",
            )

        if intent.intent == Intent.GREETING and current_state == BookingState.IDLE:
            return FlowAction(
                next_state=BookingState.IDLE,
                action_type="respond",
                message="greeting",
            )

        # Handle cancellation intent
        if intent.intent == Intent.CANCELLATION:
            return self._handle_cancellation(session, slots)

        # Handle confirmation/rejection during confirmation state
        if current_state == BookingState.CONFIRM_BOOKING:
            return self._handle_confirmation(session, intent)

        # Handle scheduling flow
        if intent.intent in (
            Intent.SCHEDULING,
            Intent.PROVIDE_INFO,
            Intent.CORRECTION,
        ):
            return self._handle_scheduling(session, collected, slots)

        # Handle reschedule as new scheduling
        if intent.intent == Intent.RESCHEDULE:
            # Clear previous booking data and start fresh
            session.collected_data = {}
            self._merge_slots(session.collected_data, slots)
            return self._handle_scheduling(session, session.collected_data, slots)

        # Default: try to continue scheduling flow
        return self._handle_scheduling(session, collected, slots)

    def _merge_slots(self, collected: dict, slots: ExtractedSlots) -> None:
        """Merge extracted slots into collected data."""
        slot_dict = slots.to_dict()
        for key, value in slot_dict.items():
            if value is not None:
                collected[key] = value

    def _handle_scheduling(
        self,
        session: SessionData,
        collected: dict,
        slots: ExtractedSlots,
    ) -> FlowAction:
        """Handle scheduling flow - collect info and book.

        Args:
            session: Session data
            collected: Collected data dict
            slots: Newly extracted slots

        Returns:
            FlowAction for next step
        """
        # Check what we still need
        missing = self._get_missing_fields(collected)

        if not missing:
            # We have everything - ready to confirm
            return FlowAction(
                next_state=BookingState.CONFIRM_BOOKING,
                action_type="confirm",
                should_search_slots=True,  # Verify slot is still available
            )

        # Determine what to collect next
        next_field = missing[0]
        next_state = self._field_to_state(next_field)

        # If we have provider and date but not specific slot, show available slots
        if (
            next_field == "time"
            and collected.get("provider_name")
            and (collected.get("date") or collected.get("date_raw"))
        ):
            return FlowAction(
                next_state=BookingState.SHOWING_SLOTS,
                action_type="show_slots",
                should_search_slots=True,
                prompt_for="time",
            )

        return FlowAction(
            next_state=next_state,
            action_type="collect",
            prompt_for=next_field,
        )

    def _handle_confirmation(
        self,
        session: SessionData,
        intent: IntentResult,
    ) -> FlowAction:
        """Handle user response to booking confirmation.

        Args:
            session: Session data
            intent: User's intent

        Returns:
            FlowAction for booking or correction
        """
        if intent.intent == Intent.CONFIRMATION:
            if intent.confirmation_type == ConfirmationType.YES:
                return FlowAction(
                    next_state=BookingState.BOOKED,
                    action_type="book",
                    should_book=True,
                )
            elif intent.confirmation_type == ConfirmationType.NO:
                # User rejected - ask what to change
                return FlowAction(
                    next_state=BookingState.COLLECT_PROVIDER,
                    action_type="collect",
                    prompt_for="correction",
                    message="What would you like to change?",
                )

        # Partial confirmation or unclear - ask again
        return FlowAction(
            next_state=BookingState.CONFIRM_BOOKING,
            action_type="confirm",
            message="I need a clear yes or no. Would you like to book this appointment?",
        )

    def _handle_cancellation(
        self,
        session: SessionData,
        slots: ExtractedSlots,
    ) -> FlowAction:
        """Handle cancellation request.

        Args:
            session: Session data
            slots: Extracted slots (may contain booking ID or patient info)

        Returns:
            FlowAction for cancellation flow
        """
        collected = session.collected_data

        # Check if we have enough to identify the booking
        if collected.get("booking_id"):
            return FlowAction(
                next_state=BookingState.CANCELLED,
                action_type="cancel",
                should_cancel=True,
            )

        # Need patient info to look up booking
        if not collected.get("patient_name"):
            return FlowAction(
                next_state=BookingState.COLLECT_PATIENT_INFO,
                action_type="collect",
                prompt_for="patient_name",
                message="To cancel your appointment, I'll need to look it up. What name is the appointment under?",
            )

        # Have name but no booking ID - would need to search
        return FlowAction(
            next_state=BookingState.CANCELLED,
            action_type="cancel",
            should_cancel=True,
            metadata={"needs_lookup": True},
        )

    def _get_missing_fields(self, collected: dict) -> list[str]:
        """Get list of required fields that are missing.

        Args:
            collected: Currently collected data

        Returns:
            List of missing field names
        """
        missing = []
        for field in self.REQUIRED_FIELDS:
            value = collected.get(field)
            # Also check raw variants for date/time
            if field == "date" and not value:
                value = collected.get("date_raw")
            if field == "time" and not value:
                value = collected.get("time_raw")

            if not value:
                missing.append(field)

        return missing

    def _field_to_state(self, field: str) -> BookingState:
        """Map field name to collection state.

        Args:
            field: Field name

        Returns:
            Corresponding BookingState
        """
        mapping = {
            "provider_name": BookingState.COLLECT_PROVIDER,
            "date": BookingState.COLLECT_DATE,
            "time": BookingState.COLLECT_TIME,
            "patient_name": BookingState.COLLECT_PATIENT_INFO,
            "patient_phone": BookingState.COLLECT_PATIENT_INFO,
            "reason": BookingState.COLLECT_REASON,
        }
        return mapping.get(field, BookingState.IDLE)

    def get_progress(self, collected: dict) -> dict:
        """Get progress summary for current booking.

        Args:
            collected: Collected data

        Returns:
            Progress dict with collected/missing info
        """
        missing = self._get_missing_fields(collected)
        total = len(self.REQUIRED_FIELDS)
        completed = total - len(missing)

        return {
            "total_required": total,
            "completed": completed,
            "missing": missing,
            "percent": int((completed / total) * 100) if total > 0 else 0,
            "collected": {
                k: v for k, v in collected.items() if v is not None
            },
        }

    def can_proceed_to_booking(self, collected: dict) -> bool:
        """Check if we have enough info to attempt booking.

        Args:
            collected: Collected data

        Returns:
            True if all required fields are present
        """
        return len(self._get_missing_fields(collected)) == 0

    def reset_flow(self, session: SessionData) -> FlowAction:
        """Reset the conversation flow to start.

        Args:
            session: Session to reset

        Returns:
            FlowAction for fresh start
        """
        session.collected_data = {}
        session.state = BookingState.IDLE

        return FlowAction(
            next_state=BookingState.IDLE,
            action_type="respond",
            message="greeting",
        )


# Singleton
_flow: Optional[ConversationFlow] = None


def get_conversation_flow() -> ConversationFlow:
    """Get singleton ConversationFlow."""
    global _flow
    if _flow is None:
        _flow = ConversationFlow()
    return _flow
