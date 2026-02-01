"""
LLM-based entity extraction using Claude Haiku.

Extracts: provider names, dates, times, appointment types, reasons.
"""

import json
import logging
import time
from datetime import date, time as time_type
from typing import Optional

from app.config import settings
from app.infra.claude import ClaudeClient, get_claude_client, ClaudeClientError
from .types import ExtractedSlots, AppointmentType

logger = logging.getLogger(__name__)


EXTRACTION_PROMPT = """Extract appointment information from this patient message.

## What to Extract

- provider_name: Doctor's name if mentioned (e.g., "Dr. Smith" -> "Smith", "Doctor Johnson" -> "Johnson")
- date: Date if mentioned (ISO format YYYY-MM-DD, relative to today: {today})
- time: Time if mentioned (24-hour format HH:MM, e.g., "2pm" -> "14:00")
- date_raw: Original text for date reference (e.g., "next Tuesday", "January 15")
- time_raw: Original text for time reference (e.g., "2pm", "morning", "around 3")
- is_flexible: true if time is approximate ("around", "about", "sometime", "morning/afternoon")
- appointment_type: Type of visit (checkup, consultation, follow_up, urgent, new_patient, specialist, sick_visit, physical, other)
- reason: Reason for visit if mentioned (e.g., "back pain", "annual physical", "flu symptoms")
- patient_name: Patient's name if they say it
- patient_phone: Phone number if mentioned

## Message

"{message}"

## Response

Respond with ONLY valid JSON (use null for fields not mentioned):
{{
    "provider_name": "<name or null>",
    "date": "<YYYY-MM-DD or null>",
    "time": "<HH:MM or null>",
    "date_raw": "<original text or null>",
    "time_raw": "<original text or null>",
    "is_flexible": <true/false>,
    "appointment_type": "<type or null>",
    "reason": "<reason or null>",
    "patient_name": "<name or null>",
    "patient_phone": "<phone or null>"
}}"""


class SlotExtractor:
    """LLM-based slot extraction using Claude Haiku."""

    def __init__(self, claude_client: Optional[ClaudeClient] = None):
        """Initialize extractor.

        Args:
            claude_client: Optional Claude client (for testing)
        """
        self._client = claude_client

    async def _get_client(self) -> ClaudeClient:
        """Get or create Claude client."""
        if self._client is None:
            self._client = await get_claude_client()
        return self._client

    async def extract(
        self,
        message: str,
        conversation_context: Optional[list[dict]] = None,
    ) -> ExtractedSlots:
        """
        Extract slots from patient message.

        Args:
            message: Patient's message
            conversation_context: Recent conversation for context

        Returns:
            ExtractedSlots with any found entities
        """
        message = message.strip()
        start_time = time.time()

        if not message:
            return ExtractedSlots()

        # Build prompt with today's date
        today = date.today().isoformat()
        prompt = self._build_prompt(message, today, conversation_context)

        client = await self._get_client()

        try:
            response = await client.generate(
                prompt=prompt,
                model=settings.claude_intent_model,
                max_tokens=200,
                temperature=0,
                use_fallback_on_error=True,
            )

            result = self._parse_response(response.content)
            result.processing_time_ms = (time.time() - start_time) * 1000
            result.raw_response = response.content

            logger.debug(
                f"Extracted slots: date={result.date}, time={result.time}, "
                f"provider={result.provider_name}"
            )

            return result

        except ClaudeClientError as e:
            logger.error(f"Claude API error: {e}")
            return ExtractedSlots()
        except Exception as e:
            logger.error(f"Extraction failed: {e}")
            return ExtractedSlots()

    def _build_prompt(
        self,
        message: str,
        today: str,
        context: Optional[list[dict]] = None,
    ) -> str:
        """Build extraction prompt."""
        base_prompt = EXTRACTION_PROMPT.format(today=today, message=message)

        if context:
            context_lines = ["Recent conversation:"]
            for turn in context[-3:]:  # Last 3 turns
                role = turn.get("role", "unknown")
                content = turn.get("content", "")[:150]
                context_lines.append(f"- {role}: {content}")
            context_lines.append("")
            return "\n".join(context_lines) + base_prompt

        return base_prompt

    def _parse_response(self, response: str) -> ExtractedSlots:
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

            # Parse date
            parsed_date = None
            if data.get("date"):
                try:
                    parsed_date = date.fromisoformat(data["date"])
                except ValueError:
                    logger.warning(f"Invalid date format: {data['date']}")

            # Parse time
            parsed_time = None
            if data.get("time"):
                try:
                    parsed_time = time_type.fromisoformat(data["time"])
                except ValueError:
                    logger.warning(f"Invalid time format: {data['time']}")

            # Parse appointment type
            appt_type = None
            if data.get("appointment_type"):
                try:
                    appt_type = AppointmentType(data["appointment_type"].lower())
                except ValueError:
                    appt_type = AppointmentType.OTHER

            return ExtractedSlots(
                provider_name=data.get("provider_name"),
                date=parsed_date,
                time=parsed_time,
                date_raw=data.get("date_raw"),
                time_raw=data.get("time_raw"),
                is_flexible=data.get("is_flexible", False),
                appointment_type=appt_type,
                reason=data.get("reason"),
                patient_name=data.get("patient_name"),
                patient_phone=data.get("patient_phone"),
            )

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse: {e}\nResponse: {response}")
            return ExtractedSlots()


# Singleton
_extractor: Optional[SlotExtractor] = None


async def get_slot_extractor() -> SlotExtractor:
    """Get singleton SlotExtractor."""
    global _extractor
    if _extractor is None:
        _extractor = SlotExtractor()
    return _extractor


async def extract_slots(
    message: str,
    context: Optional[list[dict]] = None,
) -> ExtractedSlots:
    """Convenience function to extract slots."""
    extractor = await get_slot_extractor()
    return await extractor.extract(message, context)
