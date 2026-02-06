"""
Message Router for v2 Multi-Agent Architecture

Uses a single Claude tool_use call to classify patient messages and extract
entities, replacing the previous separate IntentClassifier and SlotExtractor.
"""

import logging
import time
from datetime import datetime, timedelta
from typing import Any, Optional

from app.config import settings
from app.infra.claude import ClaudeClient, ClaudeClientError
from app.core.agent.router_types import RouteResult

logger = logging.getLogger(__name__)


# Router tool schema - forces structured output via tool_use
ROUTE_MESSAGE_TOOL = {
    "name": "route_message",
    "description": "Classify patient message and extract key information for routing to the appropriate agent.",
    "input_schema": {
        "type": "object",
        "properties": {
            "domain": {
                "type": "string",
                "enum": [
                    "scheduling",
                    "faq",
                    "crisis",
                    "handoff",
                    "greeting",
                    "goodbye",
                    "out_of_scope",
                ],
                "description": "The domain this message belongs to",
            },
            "confidence": {
                "type": "number",
                "minimum": 0,
                "maximum": 1,
                "description": "Confidence in the classification from 0.0 to 1.0",
            },
            "sub_intent": {
                "type": "string",
                "enum": [
                    "book",
                    "cancel",
                    "reschedule",
                    "check",
                    "provide_info",
                    "confirm_yes",
                    "confirm_no",
                    "correction",
                    "select_option",
                    "question",
                ],
                "description": "More specific intent within the domain",
            },
            "entities": {
                "type": "object",
                "properties": {
                    "provider_name": {
                        "type": "string",
                        "description": "Doctor/provider name (e.g., 'Smith', 'Dr. Patel')",
                    },
                    "date": {
                        "type": "string",
                        "description": "Appointment date in ISO format YYYY-MM-DD",
                    },
                    "time": {
                        "type": "string",
                        "description": "Appointment time in 24h format HH:MM",
                    },
                    "date_raw": {
                        "type": "string",
                        "description": "Original date text as spoken (e.g., 'next Tuesday')",
                    },
                    "time_raw": {
                        "type": "string",
                        "description": "Original time text as spoken (e.g., '2pm', 'morning')",
                    },
                    "is_flexible": {
                        "type": "boolean",
                        "description": "Whether the time is flexible/approximate",
                    },
                    "patient_name": {
                        "type": "string",
                        "description": "Patient's full name",
                    },
                    "patient_phone": {
                        "type": "string",
                        "description": "Patient's phone number",
                    },
                    "patient_email": {
                        "type": "string",
                        "description": "Patient's email address",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Reason for appointment (e.g., 'back pain', 'checkup')",
                    },
                    "appointment_type": {
                        "type": "string",
                        "description": "Type of appointment (e.g., 'follow_up', 'new_patient')",
                    },
                    "booking_id": {
                        "type": "string",
                        "description": "Existing booking ID for cancellation/reschedule",
                    },
                    "faq_topic": {
                        "type": "string",
                        "description": "Topic of FAQ question (e.g., 'hours', 'insurance')",
                    },
                    "selected_option": {
                        "type": "string",
                        "description": "Which option patient picked (e.g., '1', 'first', '3pm')",
                    },
                },
                "description": "Extracted entities from the message",
            },
            "urgency": {
                "type": "string",
                "enum": ["low", "medium", "high"],
                "description": "Urgency level of the message",
            },
        },
        "required": ["domain", "confidence", "sub_intent"],
    },
}


def _build_router_system_prompt(session_context: str) -> str:
    """
    Build the router system prompt with injected date context.

    Uses the exact prompt from the v2 architecture document.
    """
    today = datetime.now()
    tomorrow = today + timedelta(days=1)

    # Calculate next Monday
    days_until_monday = (7 - today.weekday()) % 7
    if days_until_monday == 0:
        days_until_monday = 7
    next_monday = today + timedelta(days=days_until_monday)

    return f"""You are the intake router for a medical clinic's AI receptionist system.

Your ONLY job is to classify the patient's message and extract any relevant information.
You do NOT write a response to the patient. You only analyze their message.

DOMAINS:
- scheduling: Patient wants to BOOK, CANCEL, RESCHEDULE, or CHECK an appointment.
  This includes any message that mentions doctors, appointments, availability, times, or dates
  in the context of wanting to see someone.
- faq: Patient is ASKING A QUESTION about the clinic - hours, location, insurance accepted,
  services offered, parking, what to bring, policies, costs. They want information, not an appointment.
- crisis: Patient is expressing self-harm, suicidal thoughts, or acute emotional/psychological
  distress. Err on the side of caution - if in doubt, classify as crisis.
- handoff: Patient explicitly asks to speak with a real person, human, manager, supervisor,
  or front desk staff. Must be explicit - frustration alone is not a handoff request.
- greeting: Patient is saying hello, hi, good morning, etc. This is ONLY for the very first
  message or a standalone greeting with no other content.
- goodbye: Patient is ending the conversation - bye, thanks, that's all, etc.
- out_of_scope: Message is completely unrelated to healthcare or the clinic. Recipes, weather,
  homework, etc.

SUB-INTENTS (for scheduling domain):
- book: Wants a new appointment
- cancel: Wants to cancel an existing appointment
- reschedule: Wants to move an existing appointment
- check: Wants to know about an upcoming appointment
- provide_info: Answering a question the receptionist asked (giving name, date, time, doctor)
- confirm_yes: Confirming something (yes, correct, book it, sounds good, perfect)
- confirm_no: Rejecting something (no, wrong, that's not right, change it)
- correction: Correcting a misunderstanding (no I said Tuesday, not Dr. Smith - Dr. Patel)
- select_option: Picking from options shown (the first one, option 2, the 3pm one, Dr. Smith)

SUB-INTENTS (for faq domain):
- question: General question about the clinic

ENTITY EXTRACTION:
Extract ONLY what is explicitly stated. Never guess or infer.
- Dates: Convert relative dates using today = {today.strftime('%Y-%m-%d')} ({today.strftime('%A')})
  "tomorrow" = {tomorrow.strftime('%Y-%m-%d')}, "next Monday" = {next_monday.strftime('%Y-%m-%d')}, etc.
- Times: Convert to 24h format. "2pm" = "14:00", "morning" = flexible
- Names: Extract as spoken. "Dr. Smith" -> "Smith", "Doctor Jane Smith" -> "Jane Smith"
- Phone: Extract any phone number format
- If something is ambiguous, omit it. Better to ask than to guess wrong.

CONVERSATION CONTEXT:
{session_context}

Use the context to understand what the patient is responding to. If the receptionist just asked
"what time works for you?" and the patient says "3pm", that's provide_info, not a new booking request."""


class MessageRouter:
    """
    Routes patient messages to the appropriate domain agent.

    Uses a single Claude tool_use call with forced tool_choice to get
    guaranteed structured output, replacing the previous separate
    IntentClassifier and SlotExtractor.
    """

    _instance: Optional["MessageRouter"] = None

    def __init__(self, claude_client: Optional[ClaudeClient] = None):
        """
        Initialize the router.

        Args:
            claude_client: Claude client instance. If None, uses singleton.
        """
        self._client = claude_client
        self._model = settings.router_model
        self._fallback_model = settings.router_fallback_model
        self._confidence_threshold = settings.router_confidence_threshold

    @classmethod
    def get_instance(cls) -> "MessageRouter":
        """Get singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset singleton instance (useful for testing)."""
        cls._instance = None

    def _get_client(self) -> ClaudeClient:
        """Get Claude client, creating if necessary."""
        if self._client is None:
            self._client = ClaudeClient.get_instance()
        return self._client

    async def route(
        self,
        message: str,
        session_context: str = "",
    ) -> RouteResult:
        """
        Route a patient message to the appropriate domain.

        Args:
            message: The patient's message
            session_context: Condensed conversation context for the router

        Returns:
            RouteResult with domain, sub_intent, entities, and confidence
        """
        start_time = time.time()

        # Try with primary model (Haiku - fast)
        result = await self._route_with_model(
            message=message,
            session_context=session_context,
            model=self._model,
        )

        # If low confidence, retry with fallback model (Sonnet - more accurate)
        if result.confidence < self._confidence_threshold:
            logger.info(
                f"Low confidence ({result.confidence:.2f}), retrying with fallback model"
            )
            result = await self._route_with_model(
                message=message,
                session_context=session_context,
                model=self._fallback_model,
            )

        result.processing_time_ms = (time.time() - start_time) * 1000

        logger.info(
            f"Routed message to domain={result.domain}, "
            f"sub_intent={result.sub_intent}, "
            f"confidence={result.confidence:.2f}, "
            f"time={result.processing_time_ms:.0f}ms"
        )

        return result

    async def _route_with_model(
        self,
        message: str,
        session_context: str,
        model: str,
    ) -> RouteResult:
        """
        Route using a specific model.

        Args:
            message: The patient's message
            session_context: Conversation context
            model: Model to use for routing

        Returns:
            RouteResult from the tool_use response
        """
        client = self._get_client()
        system_prompt = _build_router_system_prompt(session_context)

        try:
            response = await client.create_message(
                messages=[{"role": "user", "content": message}],
                system=system_prompt,
                model=model,
                max_tokens=500,
                temperature=0.0,
                tools=[ROUTE_MESSAGE_TOOL],
                tool_choice={"type": "tool", "name": "route_message"},
            )

            # Extract tool input from response
            # With forced tool_choice, content[0] should be a tool_use block
            if response.content and len(response.content) > 0:
                tool_block = response.content[0]
                if hasattr(tool_block, "input"):
                    return self._parse_tool_result(tool_block.input)

            # Fallback if no tool use found
            logger.warning("No tool_use block in router response, using default")
            return self._default_result()

        except ClaudeClientError as e:
            logger.error(f"Router Claude call failed: {e}")
            return self._default_result()
        except Exception as e:
            logger.exception(f"Unexpected router error: {e}")
            return self._default_result()

    def _parse_tool_result(self, tool_input: dict) -> RouteResult:
        """
        Parse the tool_use input into a RouteResult.

        Args:
            tool_input: The input dict from Claude's tool_use block

        Returns:
            RouteResult with parsed values
        """
        return RouteResult(
            domain=tool_input.get("domain", "out_of_scope"),
            confidence=tool_input.get("confidence", 0.0),
            sub_intent=tool_input.get("sub_intent", "question"),
            entities=tool_input.get("entities", {}),
            urgency=tool_input.get("urgency", "low"),
        )

    def _default_result(self) -> RouteResult:
        """Return a safe default result for error cases."""
        return RouteResult(
            domain="out_of_scope",
            confidence=0.0,
            sub_intent="question",
            entities={},
            urgency="low",
        )


# Singleton accessor
def get_router() -> MessageRouter:
    """Get router singleton instance."""
    return MessageRouter.get_instance()
