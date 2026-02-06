"""
Handoff Agent for v2 Multi-Agent Architecture.

Handles transfer requests to human staff.
Claude writes the handoff message, system triggers the transfer.
"""

import logging
from typing import Optional

from app.config import settings
from app.infra.claude import ClaudeClient
from app.core.intelligence.session.models import SessionData
from app.core.agent.base import BaseAgent

logger = logging.getLogger(__name__)


# System prompt from architecture doc
HANDOFF_SYSTEM_PROMPT = """You are a receptionist at a medical clinic. The patient has asked to speak with a real person on the staff.

YOUR JOB:
- Acknowledge their request warmly
- Let them know you're connecting them
- If you know WHY they want a human (from conversation context), briefly note it so the staff member has context
- Keep it to 1-2 sentences

EXAMPLES OF GOOD RESPONSES:
- "Absolutely, let me connect you with someone at the front desk. One moment."
- "Of course! I'll get a staff member on the line. They'll be able to help with your insurance question."
- "Sure thing — transferring you now. They'll have our conversation for context."

DON'T:
- Try to solve the problem yourself
- Ask "are you sure?"
- Apologize excessively
- Be slow about it — they asked, just do it

WHAT YOU KNOW ABOUT THIS PATIENT:
{collected_data}

CONVERSATION CONTEXT:
{conversation_context}"""


class HandoffAgent(BaseAgent):
    """
    Handoff agent for human transfer requests.

    Uses Haiku model - simple handoff messages don't need Sonnet.
    """

    def __init__(self, claude_client: Optional[ClaudeClient] = None):
        """Initialize handoff agent."""
        super().__init__(
            claude_client=claude_client,
            model=settings.default_agent_model,  # Haiku
        )

    def get_system_prompt(self, session: SessionData) -> str:
        """Build handoff system prompt with context."""
        collected_str = self._format_collected_data(session.collected_data)
        conversation_context = session.get_router_context_str()

        return HANDOFF_SYSTEM_PROMPT.format(
            collected_data=collected_str,
            conversation_context=conversation_context,
        )

    def get_tools(self) -> list[dict]:
        """No tools for handoff agent."""
        return []
