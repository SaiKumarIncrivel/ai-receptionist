"""
Crisis Handler for v2 Multi-Agent Architecture.

DETERMINISTIC ONLY. NO AI. NO VARIATION.

This is the ONE exception to the "AI generates everything" rule.
When a patient is in crisis, we don't risk Claude generating
an inappropriate or variable response.

The response is medically and legally safe, providing:
- Immediate acknowledgment
- 988 Suicide & Crisis Lifeline info
- Multiple contact methods
- Option to connect with clinic staff
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


class CrisisHandler:
    """
    Deterministic crisis response handler.

    NO AI. NO VARIATION. Patient safety is paramount.

    This handler returns the same safe, helpful response every time
    a crisis is detected. This ensures:
    - Consistent, medically appropriate messaging
    - Legal compliance
    - No risk of AI hallucination or inappropriate tone
    - Immediate access to professional crisis resources
    """

    # Fixed response - tested, approved, safe
    CRISIS_RESPONSE = (
        "I hear you, and I want you to know that help is available right now. "
        "Please reach out to the 988 Suicide & Crisis Lifeline — "
        "you can call or text 988 anytime, 24/7. "
        "You can also chat at 988lifeline.org. "
        "Would you like me to connect you with someone at the clinic who can help?"
    )

    def respond(self, message: str, session: Any = None) -> str:
        """
        Return deterministic crisis response.

        Args:
            message: Patient's message (logged but not processed)
            session: Session data (for logging context)

        Returns:
            Fixed crisis response with 988 Lifeline information
        """
        # Log the crisis detection (for safety audit)
        session_id = getattr(session, "session_id", "unknown") if session else "unknown"
        logger.warning(
            f"Crisis response triggered for session={session_id}. "
            f"Providing 988 Lifeline resources."
        )

        return self.CRISIS_RESPONSE
