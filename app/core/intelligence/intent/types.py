"""Intent types for conversation classification."""

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class Intent(str, Enum):
    """Patient intent categories."""

    # Scheduling actions
    SCHEDULING = "scheduling"          # Book new appointment
    CANCELLATION = "cancellation"      # Cancel existing
    RESCHEDULE = "reschedule"          # Change existing
    CHECK_APPOINTMENT = "check_appointment"  # View upcoming appointments

    # Conversation flow
    CONFIRMATION = "confirmation"      # Yes/no/correct response
    CORRECTION = "correction"          # "No, I said Tuesday not Thursday"
    PROVIDE_INFO = "provide_info"      # Answering bot's question

    # Other
    INFORMATION = "information"        # Hours, location, insurance questions
    HANDOFF = "handoff"                # Wants human agent
    GREETING = "greeting"              # Hello, hi
    GOODBYE = "goodbye"                # Bye, thanks
    OUT_OF_SCOPE = "out_of_scope"      # Not related to clinic

    # Fallback
    UNKNOWN = "unknown"


class ConfirmationType(str, Enum):
    """Types of confirmation responses."""

    YES = "yes"           # Affirmative
    NO = "no"             # Negative
    PARTIAL = "partial"   # "yes but can we change the time?"


@dataclass
class IntentResult:
    """Result of intent classification."""

    intent: Intent
    confidence: float  # 0.0 - 1.0

    # For confirmation intent
    confirmation_type: Optional[ConfirmationType] = None

    # Extracted context from the message
    reason: Optional[str] = None         # "back pain", "annual physical"
    urgency: Optional[str] = None        # "low", "medium", "high"

    # Raw LLM output for debugging
    raw_response: Optional[str] = None

    # Whether fallback model was used
    fallback_used: bool = False

    # Processing time
    processing_time_ms: float = 0.0

    @property
    def is_high_confidence(self) -> bool:
        """Check if classification is high confidence."""
        return self.confidence >= 0.7

    @property
    def is_booking_related(self) -> bool:
        """Check if intent is related to appointments."""
        return self.intent in {
            Intent.SCHEDULING,
            Intent.CANCELLATION,
            Intent.RESCHEDULE,
            Intent.CHECK_APPOINTMENT,
        }

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "intent": self.intent.value,
            "confidence": self.confidence,
            "confirmation_type": self.confirmation_type.value if self.confirmation_type else None,
            "reason": self.reason,
            "urgency": self.urgency,
            "fallback_used": self.fallback_used,
            "processing_time_ms": self.processing_time_ms,
        }
