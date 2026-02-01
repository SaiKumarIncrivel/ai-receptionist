"""Build LLM context from session state."""

import logging
from datetime import datetime
from typing import Optional

from app.core.intelligence.session.models import SessionData
from app.core.intelligence.session.state import BookingState, is_collecting_state

logger = logging.getLogger(__name__)


class ContextBuilder:
    """
    Builds structured context for LLM prompts.

    Combines session state, conversation history, and
    extracted slots into a coherent context string.
    """

    def __init__(self, max_history_turns: int = 5):
        """Initialize context builder.

        Args:
            max_history_turns: Maximum conversation turns to include
        """
        self.max_history_turns = max_history_turns

    def build(
        self,
        session: SessionData,
        include_slots: bool = True,
        include_history: bool = True,
        include_state: bool = True,
    ) -> str:
        """
        Build LLM context from session.

        Args:
            session: Session data
            include_slots: Include collected data
            include_history: Include conversation history
            include_state: Include current state info

        Returns:
            Formatted context string
        """
        parts = []

        # Current date/time
        parts.append(f"Current date: {datetime.now().strftime('%A, %B %d, %Y')}")

        # Session metadata
        parts.append(f"Turn count: {session.message_count}")

        # Current state
        if include_state:
            parts.append(f"\n### Current State")
            parts.append(f"State: {self._describe_state(session.state)}")
            if session.current_intent:
                parts.append(f"Current Intent: {session.current_intent}")

        # Collected data
        if include_slots and session.collected_data:
            parts.append(f"\n### Collected Information")
            parts.append(self._format_collected(session.collected_data))

        # Awaiting confirmation
        if session.awaiting_confirmation:
            parts.append(f"\n### Awaiting Confirmation")
            if session.last_bot_question:
                parts.append(f"Last question: {session.last_bot_question}")

        # Conversation history
        if include_history and session.message_history:
            parts.append(f"\n### Recent Conversation")

            recent = session.message_history[-self.max_history_turns:]
            for turn in recent:
                role = "User" if turn.get("role") == "user" else "Assistant"
                content = turn.get("content", "")[:200]
                if len(turn.get("content", "")) > 200:
                    content += "..."
                parts.append(f"{role}: {content}")

        return "\n".join(parts)

    def build_system_prompt(
        self,
        session: SessionData,
        clinic_name: str = "the clinic",
    ) -> str:
        """
        Build system prompt for response generation.

        Args:
            session: Session data
            clinic_name: Name of the clinic

        Returns:
            System prompt string
        """
        state_instructions = self._get_state_instructions(session.state)
        missing_info = self._get_missing_info(session)

        prompt = f"""You are a friendly and professional AI receptionist for {clinic_name}.
Your role is to help patients schedule, reschedule, or cancel appointments.

Current date: {datetime.now().strftime('%A, %B %d, %Y')}
Current conversation state: {session.state.value}
{state_instructions}

Guidelines:
- Be warm, empathetic, and professional
- Keep responses concise (1-2 sentences when possible)
- Never provide medical advice
- If asked about symptoms, recommend scheduling an appointment
- If the patient seems distressed, offer to connect them with a staff member
"""

        if missing_info:
            prompt += f"\nInformation still needed: {', '.join(missing_info)}"

        if session.awaiting_confirmation:
            prompt += "\nIMPORTANT: You are waiting for the patient to confirm. Ask for a yes/no response."

        return prompt

    def get_context_for_intent(self, session: SessionData) -> dict:
        """
        Get minimal context for intent classification.

        Args:
            session: Session data

        Returns:
            Context dictionary for classifier
        """
        return {
            "state": session.state.value,
            "collected": session.collected_data,
            "awaiting_confirmation": session.awaiting_confirmation,
            "last_bot_question": session.last_bot_question,
            "message_count": session.message_count,
        }

    def _describe_state(self, state: BookingState) -> str:
        """Get human-readable state description."""
        descriptions = {
            BookingState.IDLE: "Ready to help",
            BookingState.COLLECT_PROVIDER: "Asking which doctor/provider",
            BookingState.COLLECT_DATE: "Asking for preferred date",
            BookingState.COLLECT_TIME: "Asking for preferred time",
            BookingState.COLLECT_PATIENT_INFO: "Collecting patient information",
            BookingState.COLLECT_REASON: "Asking for reason for visit",
            BookingState.SEARCHING: "Searching for available slots",
            BookingState.SHOWING_SLOTS: "Showing available appointment times",
            BookingState.CONFIRM_BOOKING: "Confirming appointment details",
            BookingState.BOOKED: "Appointment confirmed",
            BookingState.CANCELLED: "Booking cancelled",
            BookingState.HANDED_OFF: "Transferred to staff",
            BookingState.COMPLETED: "Conversation ended",
            BookingState.ERROR: "Error occurred",
        }
        return descriptions.get(state, state.value)

    def _format_collected(self, collected: dict) -> str:
        """Format collected data for context."""
        parts = []

        if collected.get("provider_name"):
            parts.append(f"- Provider: {collected['provider_name']}")

        if collected.get("date") or collected.get("date_raw"):
            date_val = collected.get("date") or collected.get("date_raw")
            parts.append(f"- Date: {date_val}")

        if collected.get("time") or collected.get("time_raw"):
            time_val = collected.get("time") or collected.get("time_raw")
            parts.append(f"- Time: {time_val}")

        if collected.get("appointment_type"):
            parts.append(f"- Type: {collected['appointment_type']}")

        if collected.get("reason"):
            parts.append(f"- Reason: {collected['reason']}")

        if collected.get("patient_name"):
            parts.append(f"- Patient: {collected['patient_name']}")

        if collected.get("is_flexible"):
            parts.append("- Flexible on timing: Yes")

        return "\n".join(parts) if parts else "None collected yet"

    def _get_state_instructions(self, state: BookingState) -> str:
        """Get state-specific instructions for the bot."""
        instructions = {
            BookingState.IDLE: "Greet the patient and ask how you can help.",
            BookingState.COLLECT_PROVIDER: "Ask if they have a preferred doctor or provider.",
            BookingState.COLLECT_DATE: "Ask for their preferred date.",
            BookingState.COLLECT_TIME: "Ask for their preferred time.",
            BookingState.COLLECT_PATIENT_INFO: "Collect necessary patient information (name, phone).",
            BookingState.COLLECT_REASON: "Ask for the reason for their visit.",
            BookingState.SEARCHING: "Let them know you're checking availability.",
            BookingState.SHOWING_SLOTS: "Present the available appointment times.",
            BookingState.CONFIRM_BOOKING: "Confirm the appointment details and ask for final confirmation.",
            BookingState.BOOKED: "Confirm the booking was successful and provide details.",
            BookingState.CANCELLED: "Acknowledge the cancellation.",
            BookingState.HANDED_OFF: "Let them know a staff member will assist.",
            BookingState.COMPLETED: "Thank them and wish them well.",
            BookingState.ERROR: "Apologize and offer to connect them with a staff member.",
        }
        return instructions.get(state, "")

    def _get_missing_info(self, session: SessionData) -> list[str]:
        """Determine what information is still needed for booking."""
        collected = session.collected_data
        missing = []

        # For scheduling states, check what's missing
        if is_collecting_state(session.state) or session.state == BookingState.IDLE:
            if not collected.get("date") and not collected.get("date_raw"):
                if not collected.get("is_flexible"):
                    missing.append("preferred date")

            if not collected.get("time") and not collected.get("time_raw"):
                if not collected.get("is_flexible"):
                    missing.append("preferred time")

            if not collected.get("patient_name"):
                missing.append("patient name")

        return missing


# Singleton
_builder: Optional[ContextBuilder] = None


def get_context_builder() -> ContextBuilder:
    """Get singleton ContextBuilder."""
    global _builder
    if _builder is None:
        _builder = ContextBuilder()
    return _builder


def build_context(session: SessionData, **kwargs) -> str:
    """Convenience function to build context."""
    return get_context_builder().build(session, **kwargs)


def build_system_prompt(session: SessionData, clinic_name: str = "the clinic") -> str:
    """Convenience function to build system prompt."""
    return get_context_builder().build_system_prompt(session, clinic_name)
