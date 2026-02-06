"""
Conversation Agent for v2 Multi-Agent Architecture.

Handles greetings, goodbyes, and out-of-scope messages.
No tools needed - just Claude being natural.
"""

import logging
from typing import Optional

from app.config import settings
from app.infra.claude import ClaudeClient
from app.core.intelligence.session.models import SessionData
from app.core.agent.base import BaseAgent
from app.core.agent.router_types import RouteResult

logger = logging.getLogger(__name__)


# System prompt from architecture doc
CONVERSATION_SYSTEM_PROMPT = """You are a receptionist at a medical clinic. You're handling the social parts of the conversation — greetings, goodbyes, and off-topic messages.

YOUR PERSONALITY:
- Warm and genuine, like a real person at a desk
- Brief — don't over-explain what you can do unless the patient seems lost
- Natural — match the patient's energy

CURRENT CONTEXT:
This is a {message_type} message.

FOR GREETINGS:
- Keep it simple and warm. "Hi there! How can I help you today?" is fine.
- If it's a returning patient and you know their name, use it naturally.
  "Hey Sarah! What can I do for you?"
- Don't list all your capabilities unprompted. Let them tell you what they need.
- If they seem unsure, a gentle nudge: "I can help you book an appointment, answer questions about the clinic, or pretty much anything else. What's on your mind?"

FOR GOODBYES:
- Match their energy. If they say "thanks bye!", keep it light: "Bye! Take care."
- If they just finished booking, tie it together: "See you on Thursday! Take care."
- Don't be over-the-top: no "Thank you SO much for choosing our clinic! We look forward to serving you!" — that's corporate, not human.

FOR OUT-OF-SCOPE:
- Be honest and light about it. "Ha, I wish I could help with that, but I'm really just the scheduling person here. Anything clinic-related I can help with?"
- Don't lecture about what you can and can't do. One sentence, redirect naturally.
- If they persist with off-topic, stay friendly: "I'm honestly not the best help for that, but I'm here whenever you need anything clinic-related."

WHAT YOU KNOW ABOUT THIS PATIENT:
{collected_data}"""


class ConversationAgent(BaseAgent):
    """
    Conversation agent for social interactions.

    Handles greetings, goodbyes, and out-of-scope messages.
    Uses Haiku model - simple responses don't need Sonnet.
    """

    def __init__(self, claude_client: Optional[ClaudeClient] = None):
        """Initialize conversation agent."""
        super().__init__(
            claude_client=claude_client,
            model=settings.default_agent_model,  # Haiku
        )

    def get_system_prompt(self, session: SessionData) -> str:
        """Build conversation system prompt."""
        # This will be overridden in handle() with message_type
        collected_str = self._format_collected_data(session.collected_data)
        return CONVERSATION_SYSTEM_PROMPT.format(
            message_type="conversation",
            collected_data=collected_str,
        )

    def get_tools(self) -> list[dict]:
        """No tools for conversation agent."""
        return []

    async def handle(
        self,
        message: str,
        session: SessionData,
        route: RouteResult,
        tenant_id: str = "",
        **kwargs,
    ) -> str:
        """Handle conversation messages with context-specific prompt."""
        # Merge entities from router
        session.merge_entities(route.entities)

        # Build messages
        messages = session.get_claude_messages()
        messages.append({"role": "user", "content": message})

        # Build prompt with correct message_type
        collected_str = self._format_collected_data(session.collected_data)
        system_prompt = CONVERSATION_SYSTEM_PROMPT.format(
            message_type=route.domain,
            collected_data=collected_str,
        )

        client = self._get_client()

        try:
            response = await client.create_message(
                messages=messages,
                system=system_prompt,
                model=self._model,
                max_tokens=1024,
            )

            final_text = self._extract_text(response)
            session.store_turn(message, final_text, final_text)
            return final_text

        except Exception as e:
            logger.exception(f"Conversation agent failed: {e}")
            return self._fallback_response()
