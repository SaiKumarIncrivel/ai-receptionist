"""
Base Agent class for v2 Multi-Agent Architecture.

Provides common tool loop logic for all domain agents.
"""

import json
import logging
from abc import ABC, abstractmethod
from typing import Any, Callable, Optional

from app.config import settings
from app.infra.claude import ClaudeClient
from app.core.intelligence.session.models import SessionData
from app.core.agent.router_types import RouteResult

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    """
    Base class for all domain agents.

    Provides:
    - Claude API integration
    - Tool execution loop
    - Session management
    - Response extraction

    Subclasses implement:
    - get_system_prompt(): Domain-specific system prompt
    - get_tools(): Domain-specific tools (empty list if none)
    """

    def __init__(
        self,
        claude_client: Optional[ClaudeClient] = None,
        model: Optional[str] = None,
    ):
        """
        Initialize the agent.

        Args:
            claude_client: Claude client instance. If None, uses singleton.
            model: Model to use. Defaults to settings.default_agent_model.
        """
        self._client = claude_client
        self._model = model or settings.default_agent_model

    def _get_client(self) -> ClaudeClient:
        """Get Claude client, creating if necessary."""
        if self._client is None:
            self._client = ClaudeClient.get_instance()
        return self._client

    @abstractmethod
    def get_system_prompt(self, session: SessionData) -> str:
        """
        Return domain-specific system prompt.

        Args:
            session: Current session for context injection

        Returns:
            System prompt string with {collected_data} and other placeholders filled
        """
        pass

    def get_tools(self) -> list[dict]:
        """
        Return domain-specific tools in Anthropic format.

        Override in subclasses that need tools.
        Default returns empty list (no tools).
        """
        return []

    async def handle(
        self,
        message: str,
        session: SessionData,
        route: RouteResult,
        tenant_id: str = "",
        tool_executor: Optional[Callable] = None,
    ) -> str:
        """
        Handle a patient message.

        Args:
            message: Patient's message
            session: Current session
            route: Router result with entities
            tenant_id: Clinic/tenant ID for tool calls
            tool_executor: Optional tool executor for tools
                           Callable(tool_name, tool_input, tenant_id) -> dict

        Returns:
            Agent's response text
        """
        # Merge router-extracted entities into session
        session.merge_entities(route.entities)

        # Build messages for Claude
        messages = session.get_claude_messages()
        messages.append({"role": "user", "content": message})

        # Get domain-specific prompt and tools
        system_prompt = self.get_system_prompt(session)
        tools = self.get_tools()

        client = self._get_client()

        try:
            # Make initial Claude call
            response = await client.create_message(
                messages=messages,
                system=system_prompt,
                model=self._model,
                max_tokens=1024,
                tools=tools if tools else None,
            )

            # If tools available and tool_use in response, run tool loop
            if tools and tool_executor and response.stop_reason == "tool_use":
                final_text, full_chain = await self._run_tool_loop(
                    response=response,
                    messages=messages,
                    system_prompt=system_prompt,
                    tools=tools,
                    tool_executor=tool_executor,
                    session=session,
                    tenant_id=tenant_id,
                )
            else:
                # No tools or no tool calls - extract text
                final_text = self._extract_text(response)
                full_chain = [{"role": "assistant", "content": final_text}]

            # Store turn in session
            session.store_turn(message, full_chain, final_text)

            return final_text

        except Exception as e:
            logger.exception(f"Agent handle failed: {e}")
            return self._fallback_response()

    async def _run_tool_loop(
        self,
        response: Any,
        messages: list[dict],
        system_prompt: str,
        tools: list[dict],
        tool_executor: Callable,
        session: SessionData,
        tenant_id: str,
    ) -> tuple[str, list[dict]]:
        """
        Process tool calls until Claude returns final text.

        Args:
            response: Initial Claude response with tool_use
            messages: Current message list (will be extended)
            system_prompt: System prompt for follow-up calls
            tools: Tool definitions
            tool_executor: Callable(name, input, tenant_id) -> dict
            session: Current session
            tenant_id: For tool execution

        Returns:
            (final_text_response, new_messages_only)
        """
        all_messages = list(messages)  # Full context for Claude API calls
        new_messages = []  # Only NEW messages to store in session
        client = self._get_client()
        max_iterations = 10  # Prevent infinite loops

        for _ in range(max_iterations):
            if response.stop_reason != "tool_use":
                break

            # Get tool_use blocks from response
            tool_uses = [b for b in response.content if getattr(b, "type", None) == "tool_use"]

            if not tool_uses:
                break

            # Execute each tool call
            tool_results = []
            for tool_use in tool_uses:
                logger.info(f"Executing tool: {tool_use.name}")

                try:
                    result = await tool_executor(
                        tool_use.name,
                        tool_use.input,
                        tenant_id,
                    )
                except Exception as e:
                    logger.error(f"Tool execution error: {e}")
                    result = {"error": "execution_failed", "message": str(e)}

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": json.dumps(result) if isinstance(result, dict) else str(result),
                })

                # Check for booking_id in result and store in session
                if isinstance(result, dict) and result.get("booking_id"):
                    session.booking_id = result["booking_id"]

            # Serialize assistant response content blocks
            assistant_content = self._serialize_content_blocks(response.content)

            # Append to message chains
            assistant_msg = {"role": "assistant", "content": assistant_content}
            tool_result_msg = {"role": "user", "content": tool_results}

            all_messages.append(assistant_msg)
            all_messages.append(tool_result_msg)
            new_messages.append(assistant_msg)
            new_messages.append(tool_result_msg)

            # Call Claude again with updated messages
            response = await client.create_message(
                messages=all_messages,
                system=system_prompt,
                model=self._model,
                max_tokens=1024,
                tools=tools,
            )

        # Extract final text
        final_text = self._extract_text(response)

        # Add final assistant message to chain
        final_msg = {"role": "assistant", "content": final_text}
        new_messages.append(final_msg)

        return final_text, new_messages

    def _serialize_content_blocks(self, content: list) -> list[dict]:
        """
        Serialize Anthropic content blocks to dicts.

        Anthropic SDK returns objects, but we need dicts for storage and API calls.
        """
        serialized = []
        for block in content:
            if hasattr(block, "type"):
                if block.type == "text":
                    serialized.append({"type": "text", "text": block.text})
                elif block.type == "tool_use":
                    serialized.append({
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    })
            elif isinstance(block, dict):
                serialized.append(block)
        return serialized

    def _extract_text(self, response: Any) -> str:
        """
        Extract text from Claude response.

        Args:
            response: Anthropic response object

        Returns:
            Text content or fallback message
        """
        if response.content:
            for block in response.content:
                if getattr(block, "type", None) == "text":
                    return block.text

        return self._fallback_response()

    def _fallback_response(self) -> str:
        """Return fallback response for error cases."""
        return (
            "I'm having a bit of trouble right now. "
            "Let me connect you with the front desk."
        )

    def _format_collected_data(self, collected: dict) -> str:
        """Format collected data for system prompt injection."""
        if not collected:
            return "Nothing collected yet"

        parts = []
        for key, value in collected.items():
            if value:
                # Convert snake_case to readable format
                readable_key = key.replace("_", " ").title()
                parts.append(f"{readable_key}: {value}")

        return ", ".join(parts) if parts else "Nothing collected yet"
