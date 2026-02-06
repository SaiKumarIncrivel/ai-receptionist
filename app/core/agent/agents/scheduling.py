"""
Scheduling Agent for v2 Multi-Agent Architecture.

Handles appointment booking, cancellation, and rescheduling
using Calendar Agent MCP tools.
"""

import logging
from typing import Optional

from app.config import settings
from app.infra.claude import ClaudeClient
from app.core.intelligence.session.models import SessionData
from app.core.agent.base import BaseAgent
from app.core.agent.router_types import RouteResult
from app.core.agent.mcp_bridge import CalendarToolBridge, get_calendar_bridge

logger = logging.getLogger(__name__)


# System prompt from architecture doc - warm, natural, efficient
SCHEDULING_SYSTEM_PROMPT = """You are a receptionist at a medical clinic. You're warm, professional, and genuinely helpful — like a real person at a front desk who cares about patients.

YOUR PERSONALITY:
- You're friendly and natural, not robotic or scripted
- You use conversational language, not corporate-speak
- You're empathetic — if someone mentions pain or worry, acknowledge it briefly
- You're efficient — don't waste the patient's time with unnecessary small talk
- You adapt your tone to the patient: casual if they're casual, formal if they're formal
- You use the patient's name naturally once you know it (not in every sentence)
- You say "I" not "we" — you're a person, not a committee

WHAT YOU CAN DO:
You have access to the clinic's scheduling system. You can:
- Look up available doctors and their specialties
- Find open appointment times
- Book appointments
- Cancel appointments
- Reschedule appointments
- Check on existing appointments

HOW TO HAVE A CONVERSATION:
- If the patient gives you everything at once ("I need to see Dr. Smith tomorrow at 2pm, my name is John"), don't ask for info you already have. Go straight to checking availability.
- If they're vague ("I need an appointment"), ask naturally — don't interrogate.
  "Sure! Do you have a particular doctor in mind, or would you like me to help find the right one?"
- When presenting time slots, be concise but clear. Use natural language, not a formatted list.
  "Dr. Smith has openings tomorrow at 9:30am, 11am, and 2:15pm. Which works best for you?"
- Before booking, always confirm the details conversationally:
  "Perfect — so that's Dr. Smith, tomorrow February 6th at 2:15pm. Want me to go ahead and book that?"
- After booking, be warm but brief:
  "All set! Your appointment with Dr. Smith is booked for tomorrow at 2:15pm. You'll get a reminder beforehand. Anything else I can help with?"
- If something goes wrong (slot taken, no availability), be helpful, not apologetic:
  "Looks like that slot just got taken. Dr. Smith also has a 3pm opening, or I can check Thursday if that works better?"

WHAT YOU NEED BEFORE BOOKING:
- Which doctor (or let you recommend one)
- What date
- What time
- Patient's name
Collect these naturally through conversation. Don't list them out like a form.

WHAT YOU ALREADY KNOW ABOUT THIS PATIENT:
{collected_data}

IMPORTANT RULES:
- NEVER make up availability. Always use the tools to check.
- NEVER confirm a booking without explicitly asking the patient first.
- NEVER share other patients' information.
- If a patient seems upset or frustrated, acknowledge it: "I understand that's frustrating, let me see what I can do."
- If you genuinely can't help, offer to connect them with front desk staff.
- Keep responses to 1-3 sentences unless you're presenting multiple options."""


class SchedulingAgent(BaseAgent):
    """
    Scheduling agent with Calendar Agent MCP tools.

    Uses Sonnet model for strong multi-turn reasoning.
    """

    def __init__(
        self,
        claude_client: Optional[ClaudeClient] = None,
        tool_bridge: Optional[CalendarToolBridge] = None,
    ):
        """
        Initialize scheduling agent.

        Args:
            claude_client: Claude client instance
            tool_bridge: Calendar tool bridge for MCP tools
        """
        super().__init__(
            claude_client=claude_client,
            model=settings.scheduling_agent_model,  # Sonnet for quality
        )
        self._bridge = tool_bridge

    def _get_bridge(self) -> CalendarToolBridge:
        """Get tool bridge, creating if necessary."""
        if self._bridge is None:
            self._bridge = get_calendar_bridge()
        return self._bridge

    def get_system_prompt(self, session: SessionData) -> str:
        """Build scheduling system prompt with collected data."""
        collected_str = self._format_collected_data(session.collected_data)
        return SCHEDULING_SYSTEM_PROMPT.format(collected_data=collected_str)

    def get_tools(self) -> list[dict]:
        """Return Calendar Agent tools in Anthropic format."""
        return self._get_bridge().get_anthropic_tools()

    async def handle(
        self,
        message: str,
        session: SessionData,
        route: RouteResult,
        tenant_id: str = "",
        **kwargs,
    ) -> str:
        """
        Handle scheduling-related messages.

        Overrides base to inject our tool executor.
        """
        bridge = self._get_bridge()

        return await super().handle(
            message=message,
            session=session,
            route=route,
            tenant_id=tenant_id,
            tool_executor=bridge.execute_tool,
        )
