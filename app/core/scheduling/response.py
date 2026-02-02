"""
Response Generator for AI Receptionist.

Generates natural, conversational responses using LLM
with fallback templates for reliability.
"""

import logging
from dataclasses import dataclass
from typing import Optional

from app.infra.claude import get_claude_client, ClaudeClient
from app.core.intelligence.session.models import SessionData
from app.core.intelligence.session.state import BookingState
from app.core.scheduling.calendar_client import TimeSlot, Provider

logger = logging.getLogger(__name__)


# Response generation prompt
RESPONSE_PROMPT = """You are a friendly, professional AI receptionist for a medical clinic.

Generate a natural, conversational response based on:
- Current state: {state}
- Collected information: {collected}
- Available providers: {providers}
- Available slots: {slots}
- Last user message: {user_message}
- Action needed: {action}

Guidelines:
- Be warm but professional
- Keep responses concise (1-3 sentences)
- If asking for information, ask one thing at a time
- Confirm information back naturally
- Use patient's name if known
- Don't be overly formal or robotic
- If providers list is available, present them to help user choose
- If slots are available, present them for selection

Generate ONLY the response text, no JSON or formatting."""


@dataclass
class ResponseContext:
    """Context for response generation."""

    state: BookingState
    user_message: str
    collected_data: dict
    available_slots: Optional[list[TimeSlot]] = None
    available_providers: Optional[list[Provider]] = None
    action: Optional[str] = None
    error_message: Optional[str] = None
    booking_id: Optional[str] = None


class ResponseGenerator:
    """
    LLM-based response generator with fallback templates.

    Uses Claude for natural conversation, falls back to
    templates if LLM fails or for speed-critical responses.
    """

    def __init__(self, claude_client: Optional[ClaudeClient] = None):
        """Initialize generator.

        Args:
            claude_client: Claude client (uses singleton if not provided)
        """
        self._claude_client = claude_client

    async def _get_client(self) -> ClaudeClient:
        """Get Claude client."""
        if self._claude_client is None:
            self._claude_client = await get_claude_client()
        return self._claude_client

    async def generate(
        self,
        context: ResponseContext,
        session: Optional[SessionData] = None,
    ) -> str:
        """Generate response based on context.

        Args:
            context: Response context
            session: Optional session for conversation history

        Returns:
            Generated response text
        """
        # Use templates for specific states (faster, more reliable)
        template_response = self._try_template(context)
        if template_response:
            return template_response

        # Use LLM for dynamic responses
        try:
            client = await self._get_client()

            # Format slots for prompt
            slots_text = "None available"
            if context.available_slots:
                slots_text = self._format_slots_for_prompt(context.available_slots)

            # Format providers for prompt
            providers_text = "None available"
            if context.available_providers:
                providers_text = self._format_providers_for_prompt(context.available_providers)

            prompt = RESPONSE_PROMPT.format(
                state=context.state.value,
                collected=self._format_collected(context.collected_data),
                providers=providers_text,
                slots=slots_text,
                user_message=context.user_message,
                action=context.action or "respond naturally",
            )

            response = await client.generate(
                prompt=prompt,
                max_tokens=200,
                temperature=0.7,
            )

            return response.content.strip()

        except Exception as e:
            logger.warning(f"LLM response generation failed: {e}")
            return self._fallback_response(context)

    def _try_template(self, context: ResponseContext) -> Optional[str]:
        """Try to use a template response.

        Returns template if appropriate, None otherwise.
        """
        state = context.state
        collected = context.collected_data
        patient_name = collected.get("patient_name", "")
        name_prefix = f"{patient_name}, " if patient_name else ""

        # Error responses
        if context.error_message:
            return f"I apologize, but {context.error_message}. Would you like to try a different option?"

        # State-specific templates
        if state == BookingState.IDLE:
            return None  # Use LLM for initial greeting handling

        elif state == BookingState.COLLECT_PROVIDER:
            # Use dynamic provider list if available
            if context.available_providers:
                return self.format_providers(context.available_providers, name_prefix)
            return f"{name_prefix}Which doctor would you like to see?"

        elif state == BookingState.COLLECT_DATE:
            provider = collected.get("provider_name", "the doctor")
            return f"Great! When would you like to see {provider}?"

        elif state == BookingState.COLLECT_TIME:
            date_str = collected.get("date_raw", collected.get("date", "that day"))
            return f"What time works best for you on {date_str}?"

        elif state == BookingState.COLLECT_PATIENT_INFO:
            if collected.get("patient_name"):
                return f"{name_prefix}What's the best phone number to reach you?"
            return "May I have your name for the appointment?"

        elif state == BookingState.COLLECT_REASON:
            return f"{name_prefix}What's the reason for your visit today?"

        elif state == BookingState.BOOKED:
            return None  # Use booking_confirmed() method

        elif state == BookingState.CANCELLED:
            return "Your appointment has been cancelled. Is there anything else I can help you with?"

        elif state == BookingState.HANDED_OFF:
            return "I'll connect you with a staff member who can better assist you. Please hold."

        return None  # Use LLM for other states

    def _fallback_response(self, context: ResponseContext) -> str:
        """Generate fallback response when LLM fails."""
        state = context.state

        fallbacks = {
            BookingState.IDLE: "Hello! I can help you schedule an appointment. What brings you in today?",
            BookingState.COLLECT_PROVIDER: "Which doctor would you like to see?",
            BookingState.COLLECT_DATE: "What date works for you?",
            BookingState.COLLECT_TIME: "What time would you prefer?",
            BookingState.COLLECT_PATIENT_INFO: "May I have your name and phone number?",
            BookingState.COLLECT_REASON: "What's the reason for your visit?",
            BookingState.CONFIRM_BOOKING: "Would you like me to book this appointment?",
            BookingState.SHOWING_SLOTS: "Here are the available times. Which works for you?",
        }

        return fallbacks.get(
            state,
            "I'm here to help. Could you tell me more about what you need?",
        )

    def _format_collected(self, collected: dict) -> str:
        """Format collected data for prompt."""
        if not collected:
            return "Nothing collected yet"

        parts = []
        for key, value in collected.items():
            if value:
                # Make keys more readable
                readable_key = key.replace("_", " ").title()
                parts.append(f"{readable_key}: {value}")

        return ", ".join(parts) if parts else "Nothing collected yet"

    def _format_slots_for_prompt(self, slots: list[TimeSlot]) -> str:
        """Format slots for LLM prompt."""
        if not slots:
            return "No slots available"

        lines = []
        for slot in slots[:5]:  # Limit to 5 for prompt brevity
            lines.append(
                f"- {slot.provider_name}: {slot.start_time} ({slot.duration_minutes} min)"
            )
        return "\n".join(lines)

    def _format_providers_for_prompt(self, providers: list[Provider]) -> str:
        """Format providers for LLM prompt."""
        if not providers:
            return "No providers available"

        lines = []
        for provider in providers[:10]:  # Limit to 10 for prompt brevity
            specialty_part = f" ({provider.specialty})" if provider.specialty else ""
            lines.append(f"- {provider.name}{specialty_part}")
        return "\n".join(lines)

    # === Convenience Methods ===

    def greeting(self, clinic_name: Optional[str] = None) -> str:
        """Generate greeting response.

        Args:
            clinic_name: Optional clinic name to include

        Returns:
            Greeting text
        """
        if clinic_name:
            return f"Hello! Thank you for calling {clinic_name}. I'm your AI assistant and I can help you schedule an appointment. How can I help you today?"
        return "Hello! I'm your AI assistant and I can help you schedule an appointment. How can I help you today?"

    def goodbye(self, patient_name: Optional[str] = None) -> str:
        """Generate goodbye response.

        Args:
            patient_name: Optional patient name

        Returns:
            Goodbye text
        """
        if patient_name:
            return f"Thank you, {patient_name}! Take care and we'll see you soon. Goodbye!"
        return "Thank you for calling! Take care and have a great day. Goodbye!"

    def handoff(self, reason: Optional[str] = None) -> str:
        """Generate handoff response.

        Args:
            reason: Optional reason for handoff

        Returns:
            Handoff text
        """
        base = "I'll connect you with a staff member who can better assist you."
        if reason:
            return f"I understand you need help with {reason}. {base} Please hold."
        return f"{base} Please hold."

    def format_providers(
        self,
        providers: list[Provider],
        name_prefix: str = "",
    ) -> str:
        """Format provider list for user display.

        Args:
            providers: List of available providers
            name_prefix: Optional patient name prefix

        Returns:
            Formatted provider list
        """
        if not providers:
            return f"{name_prefix}Which doctor would you like to see?"

        intro = f"{name_prefix}Which doctor would you like to see? Here are our available providers:"
        lines = [intro]

        for provider in providers:
            specialty_part = f" ({provider.specialty})" if provider.specialty else ""
            lines.append(f"  - {provider.name}{specialty_part}")

        lines.append("\nJust let me know who you'd prefer!")
        return "\n".join(lines)

    def format_slots(
        self,
        slots: list[TimeSlot],
        intro: Optional[str] = None,
    ) -> str:
        """Format available slots for user display.

        Args:
            slots: List of available slots
            intro: Optional intro text

        Returns:
            Formatted slot list
        """
        if not slots:
            return "I'm sorry, there are no available slots for that time. Would you like to try a different date or time?"

        intro = intro or "Here are the available times:"
        lines = [intro]

        for i, slot in enumerate(slots, 1):
            # Parse time for display
            time_display = slot.start_time
            if "T" in time_display:
                # Extract just the time part from ISO format
                time_display = time_display.split("T")[1][:5]

            lines.append(
                f"{i}. {slot.provider_name} - {time_display}"
            )

        lines.append("\nWhich one would you like?")
        return "\n".join(lines)

    def confirm_booking(
        self,
        provider_name: str,
        date: str,
        time: str,
        patient_name: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> str:
        """Generate booking confirmation request.

        Args:
            provider_name: Doctor/provider name
            date: Appointment date
            time: Appointment time
            patient_name: Patient name
            reason: Visit reason

        Returns:
            Confirmation request text
        """
        parts = [f"Let me confirm the details:"]
        parts.append(f"- Doctor: {provider_name}")
        parts.append(f"- Date: {date}")
        parts.append(f"- Time: {time}")

        if patient_name:
            parts.append(f"- Patient: {patient_name}")
        if reason:
            parts.append(f"- Reason: {reason}")

        parts.append("\nShall I book this appointment for you?")
        return "\n".join(parts)

    def booking_confirmed(
        self,
        booking_id: str,
        provider_name: str,
        date: str,
        time: str,
        patient_name: Optional[str] = None,
    ) -> str:
        """Generate booking confirmed response.

        Args:
            booking_id: Booking confirmation ID
            provider_name: Doctor/provider name
            date: Appointment date
            time: Appointment time
            patient_name: Patient name

        Returns:
            Confirmation text
        """
        name_part = f", {patient_name}" if patient_name else ""
        return (
            f"Your appointment is confirmed{name_part}!\n\n"
            f"📅 {date} at {time}\n"
            f"👨‍⚕️ {provider_name}\n"
            f"📋 Confirmation #: {booking_id}\n\n"
            f"We'll send you a reminder before your appointment. "
            f"Is there anything else I can help you with?"
        )

    def booking_failed(
        self,
        reason: Optional[str] = None,
        suggestions: Optional[list[str]] = None,
    ) -> str:
        """Generate booking failed response.

        Args:
            reason: Failure reason
            suggestions: Suggested actions

        Returns:
            Failure response text
        """
        base = "I'm sorry, I wasn't able to complete the booking."

        if reason:
            base += f" {reason}"

        if suggestions:
            base += "\n\nHere are some options:\n"
            for suggestion in suggestions:
                base += f"- {suggestion}\n"
            base += "\nWhat would you like to do?"
        else:
            base += " Would you like to try a different time or doctor?"

        return base

    def out_of_scope(self) -> str:
        """Response for out-of-scope requests."""
        return (
            "I'm specifically designed to help with scheduling appointments. "
            "For other questions, please speak with our front desk staff. "
            "Is there an appointment I can help you with?"
        )

    def clarification(self, what: str) -> str:
        """Request clarification from user.

        Args:
            what: What needs clarification

        Returns:
            Clarification request text
        """
        return f"I want to make sure I understand correctly. Could you clarify {what}?"


# Singleton
_generator: Optional[ResponseGenerator] = None


def get_response_generator() -> ResponseGenerator:
    """Get singleton ResponseGenerator."""
    global _generator
    if _generator is None:
        _generator = ResponseGenerator()
    return _generator
