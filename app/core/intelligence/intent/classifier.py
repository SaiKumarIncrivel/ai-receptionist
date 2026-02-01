"""
LLM-based intent classification using Claude Haiku.

No keyword matching - LLM handles all classification for reliability.
"""

import json
import logging
import time
from typing import Optional

from app.config import settings
from app.infra.claude import ClaudeClient, get_claude_client, ClaudeClientError
from .types import Intent, IntentResult, ConfirmationType

logger = logging.getLogger(__name__)


CLASSIFICATION_PROMPT = """You are an intent classifier for a medical clinic receptionist AI.

Classify the patient's message into ONE intent category.

## Intent Categories

SCHEDULING INTENTS:
- scheduling: Patient wants to BOOK a NEW appointment
- cancellation: Patient wants to CANCEL an existing appointment
- reschedule: Patient wants to CHANGE/MOVE an existing appointment to different time
- check_appointment: Patient wants to VIEW/CHECK their upcoming appointments

CONVERSATION INTENTS:
- confirmation: Patient responding YES or NO to a question (includes "correct", "that's right", "book it", "no", "wrong")
- correction: Patient CORRECTING something bot said ("No, I said Tuesday not Thursday")
- provide_info: Patient answering bot's question (giving name, date, time, doctor preference)

OTHER INTENTS:
- information: Asking about clinic hours, location, insurance, services
- handoff: Wants to speak with a HUMAN staff member
- greeting: Hello, hi, good morning
- goodbye: Bye, thanks, see you
- out_of_scope: Not related to clinic at all
- unknown: Cannot determine intent

## For CONFIRMATION intent, also determine type:
- yes: Affirmative (yes, correct, book it, perfect, sounds good)
- no: Negative (no, wrong, cancel, don't)
- partial: Mixed ("yes but different time")

## Context

{context}

## Patient Message

"{message}"

## Response

Respond with ONLY valid JSON:
{{
    "intent": "<intent>",
    "confidence": <0.0-1.0>,
    "confirmation_type": "<yes/no/partial or null>",
    "reason": "<brief reason if scheduling-related, else null>",
    "urgency": "<low/medium/high if scheduling-related, else null>"
}}"""


class IntentClassifier:
    """
    LLM-based intent classifier using Claude Haiku.

    Haiku is fast (~50ms) and cheap (~$0.25/1M input tokens).
    Falls back to Sonnet for low confidence.
    """

    def __init__(self, claude_client: Optional[ClaudeClient] = None):
        """Initialize classifier.

        Args:
            claude_client: Optional Claude client (for testing)
        """
        self._client = claude_client
        self._confidence_threshold = settings.claude_intent_confidence_threshold

    async def _get_client(self) -> ClaudeClient:
        """Get or create Claude client."""
        if self._client is None:
            self._client = await get_claude_client()
        return self._client

    async def classify(
        self,
        message: str,
        session_context: Optional[dict] = None,
    ) -> IntentResult:
        """
        Classify patient message intent using LLM.

        Args:
            message: Patient's message
            session_context: Current session state for context

        Returns:
            IntentResult with intent and confidence
        """
        message = message.strip()
        start_time = time.time()

        if not message:
            return IntentResult(intent=Intent.UNKNOWN, confidence=1.0)

        # Build context string
        context_str = self._build_context(session_context)

        # Get client
        client = await self._get_client()

        # Use Haiku (fast, cheap)
        result = await self._classify_with_model(
            client=client,
            message=message,
            context=context_str,
            model=settings.claude_intent_model,
        )

        # If very low confidence, try Sonnet
        if result.confidence < self._confidence_threshold:
            logger.debug(f"Haiku confidence {result.confidence:.2f}, trying Sonnet")
            result = await self._classify_with_model(
                client=client,
                message=message,
                context=context_str,
                model=settings.claude_fallback_model,
            )
            result.fallback_used = True

        result.processing_time_ms = (time.time() - start_time) * 1000
        logger.debug(f"Classified intent: {result.intent.value} (confidence: {result.confidence:.2f})")

        return result

    async def _classify_with_model(
        self,
        client: ClaudeClient,
        message: str,
        context: str,
        model: str,
    ) -> IntentResult:
        """Run classification with specified model."""
        prompt = CLASSIFICATION_PROMPT.format(
            context=context or "New conversation, no prior context.",
            message=message,
        )

        try:
            response = await client.generate(
                prompt=prompt,
                model=model,
                max_tokens=150,
                temperature=0,  # Deterministic
                use_fallback_on_error=False,
            )

            return self._parse_response(response.content)

        except ClaudeClientError as e:
            logger.error(f"Claude API error: {e}")
            return IntentResult(intent=Intent.UNKNOWN, confidence=0.0)
        except Exception as e:
            logger.error(f"Classification failed: {e}")
            return IntentResult(intent=Intent.UNKNOWN, confidence=0.0)

    def _build_context(self, session_context: Optional[dict]) -> str:
        """Build context string for the prompt."""
        if not session_context:
            return ""

        parts = []

        if session_context.get("state"):
            parts.append(f"Current state: {session_context['state']}")

        if session_context.get("collected"):
            collected = session_context["collected"]
            items = []
            if collected.get("provider_name"):
                items.append(f"provider={collected['provider_name']}")
            if collected.get("date") or collected.get("date_raw"):
                date_val = collected.get("date") or collected.get("date_raw")
                items.append(f"date={date_val}")
            if collected.get("time") or collected.get("time_raw"):
                time_val = collected.get("time") or collected.get("time_raw")
                items.append(f"time={time_val}")
            if items:
                parts.append(f"Collected: {', '.join(items)}")

        if session_context.get("awaiting_confirmation"):
            parts.append("Bot is WAITING for YES/NO confirmation")

        if session_context.get("last_bot_question"):
            msg = session_context["last_bot_question"][:100]
            parts.append(f'Bot just asked: "{msg}"')

        return "\n".join(parts) if parts else ""

    def _parse_response(self, response: str) -> IntentResult:
        """Parse LLM JSON response."""
        # Clean markdown if present
        response = response.strip()
        if response.startswith("```"):
            lines = response.split("\n")
            # Remove first line (```json or ```)
            lines = lines[1:]
            # Remove last line if it's closing ```
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            response = "\n".join(lines)
        response = response.strip()

        try:
            data = json.loads(response)

            # Parse intent
            intent_str = data.get("intent", "unknown").lower()
            try:
                intent = Intent(intent_str)
            except ValueError:
                intent = Intent.UNKNOWN

            # Parse confirmation_type
            conf_type = None
            if data.get("confirmation_type"):
                try:
                    conf_type = ConfirmationType(data["confirmation_type"].lower())
                except ValueError:
                    pass

            return IntentResult(
                intent=intent,
                confidence=float(data.get("confidence", 0.5)),
                confirmation_type=conf_type,
                reason=data.get("reason"),
                urgency=data.get("urgency"),
                raw_response=response,
            )

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse: {e}\nResponse: {response}")
            return IntentResult(
                intent=Intent.UNKNOWN,
                confidence=0.0,
                raw_response=response,
            )


# Singleton
_classifier: Optional[IntentClassifier] = None


async def get_intent_classifier() -> IntentClassifier:
    """Get singleton IntentClassifier."""
    global _classifier
    if _classifier is None:
        _classifier = IntentClassifier()
    return _classifier


async def classify_intent(
    message: str,
    session_context: Optional[dict] = None,
) -> IntentResult:
    """Convenience function to classify intent."""
    classifier = await get_intent_classifier()
    return await classifier.classify(message, session_context)
