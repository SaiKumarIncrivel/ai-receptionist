"""
Router Types for v2 Multi-Agent Architecture

Contains the RouteResult dataclass returned by the MessageRouter.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RouteResult:
    """
    Result from the message router.

    The router classifies patient messages and extracts entities using a single
    Claude tool_use call, replacing the previous separate intent classifier
    and slot extractor.

    Attributes:
        domain: The routing domain - determines which agent handles the message.
            One of: scheduling, faq, crisis, handoff, greeting, goodbye, out_of_scope
        confidence: Classification confidence from 0.0 to 1.0.
            If below threshold, router retries with Sonnet model.
        sub_intent: More specific intent within the domain.
            For scheduling: book, cancel, reschedule, check, provide_info,
                           confirm_yes, confirm_no, correction, select_option
            For faq: question
        entities: Extracted entities from the message.
            May include: provider_name, date, time, date_raw, time_raw,
                        is_flexible, patient_name, patient_phone, patient_email,
                        reason, appointment_type, booking_id, faq_topic,
                        selected_option
        urgency: Message urgency level - low, medium, or high.
        processing_time_ms: Time taken for routing in milliseconds.
    """

    domain: str
    confidence: float
    sub_intent: str
    entities: dict = field(default_factory=dict)
    urgency: str = "low"
    processing_time_ms: float = 0.0

    @property
    def is_high_confidence(self) -> bool:
        """Check if classification confidence is high (>= 0.7)."""
        return self.confidence >= 0.7

    @property
    def is_scheduling(self) -> bool:
        """Check if routed to scheduling domain."""
        return self.domain == "scheduling"

    @property
    def is_faq(self) -> bool:
        """Check if routed to FAQ domain."""
        return self.domain == "faq"

    @property
    def is_crisis(self) -> bool:
        """Check if crisis detected."""
        return self.domain == "crisis"

    @property
    def needs_agent(self) -> bool:
        """Check if message needs an AI agent (vs deterministic handler)."""
        return self.domain not in ("crisis",)

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "domain": self.domain,
            "confidence": self.confidence,
            "sub_intent": self.sub_intent,
            "entities": self.entities,
            "urgency": self.urgency,
            "processing_time_ms": self.processing_time_ms,
        }
