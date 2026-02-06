"""
Session data models for v2 Multi-Agent Architecture.

Stores full Claude conversation format including tool_use blocks.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4


def _utcnow() -> datetime:
    """Get current UTC time as timezone-aware datetime."""
    return datetime.now(timezone.utc)


@dataclass
class SessionData:
    """
    Complete session data stored in Redis for v2 multi-agent architecture.

    Key changes from v1:
    - Removed: state, previous_state (no more state machine)
    - Removed: current_intent, intent_history (router handles per-message)
    - Removed: shown_slots, selected_slot, awaiting_confirmation (agent handles)
    - Removed: last_bot_question (full history captures this)
    - Added: active_agent, previous_agent (agent tracking)
    - Added: claude_messages (full Claude conversation format with tool_use)
    - Added: router_context (condensed text-only for router)

    The key insight: Claude's context window IS the state.
    We store the full conversation including tool calls and results.
    """

    # Identifiers
    session_id: str = field(default_factory=lambda: str(uuid4()))
    clinic_id: str = ""
    patient_id: Optional[str] = None

    # Agent tracking
    active_agent: Optional[str] = None  # "scheduling", "faq", etc.
    previous_agent: Optional[str] = None  # For agent switching

    # Collected patient data (persists across agents)
    collected_data: dict = field(default_factory=dict)

    # Full Claude conversation history (Anthropic messages format)
    # Includes tool_use and tool_result blocks for full context
    claude_messages: list[dict] = field(default_factory=list)
    max_messages: int = 40  # ~20 turns with tool calls

    # Condensed history for router (text-only, no tool blocks)
    # Used by router to understand context without processing full tool chain
    router_context: list[dict] = field(default_factory=list)
    max_router_context: int = 10

    # Metadata
    message_count: int = 0
    booking_id: Optional[str] = None
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)

    def store_turn(
        self,
        user_message: str,
        assistant_content: Any,
        text_response: str,
    ) -> None:
        """
        Store a complete conversation turn.

        Args:
            user_message: The user's message
            assistant_content: Full assistant response. Can be:
                - str: Simple text response
                - list[dict]: New messages from tool loop (no history, no duplicates)
            text_response: The final text response shown to user
        """
        # Add user message to full history
        self.claude_messages.append({"role": "user", "content": user_message})

        # Add assistant response(s) to full history
        if isinstance(assistant_content, list):
            # New messages from tool loop (no history, no duplicates)
            self.claude_messages.extend(assistant_content)
        else:
            # Simple text response
            self.claude_messages.append({"role": "assistant", "content": text_response})

        # Add to condensed router context (text-only)
        self.router_context.append({"role": "user", "content": user_message})
        self.router_context.append({"role": "assistant", "content": text_response})

        self.message_count += 1
        self.updated_at = _utcnow()
        self._trim()

    def get_claude_messages(self) -> list[dict]:
        """
        Get full message history for Claude agent calls.

        Returns a copy of claude_messages for use in API calls.
        """
        return list(self.claude_messages)

    def get_router_context_str(self) -> str:
        """
        Get condensed context string for router prompt.

        Returns a formatted string with recent conversation and collected data.
        """
        if not self.router_context:
            return "New conversation, no prior context."

        # Get last 6 messages (3 turns)
        recent = self.router_context[-6:]
        lines = []
        for msg in recent:
            role = "Patient" if msg["role"] == "user" else "Receptionist"
            content = msg.get("content", "")
            if isinstance(content, str):
                # Truncate long messages
                content = content[:200]
            lines.append(f"{role}: {content}")

        context = "\n".join(lines)

        # Add collected data summary
        if self.collected_data:
            collected = ", ".join(
                f"{k}: {v}" for k, v in self.collected_data.items() if v
            )
            context += f"\n\nCollected so far: {collected}"

        # Add current agent info
        if self.active_agent:
            context += f"\nCurrently in: {self.active_agent} flow"

        return context

    def merge_entities(self, entities: dict) -> None:
        """
        Merge router-extracted entities into collected data.

        Only updates fields that have non-None values.

        Args:
            entities: Dict of extracted entities from router
        """
        if entities:
            for key, value in entities.items():
                if value is not None:
                    self.collected_data[key] = value

    def _trim(self) -> None:
        """Keep histories within configured limits."""
        if len(self.claude_messages) > self.max_messages:
            self.claude_messages = self.claude_messages[-self.max_messages:]
        if len(self.router_context) > self.max_router_context:
            self.router_context = self.router_context[-self.max_router_context:]

    def to_json(self) -> str:
        """
        Convert to JSON string for Redis storage.

        Handles serialization of datetime and nested dicts.
        """
        data = {
            "session_id": self.session_id,
            "clinic_id": self.clinic_id,
            "patient_id": self.patient_id,
            "active_agent": self.active_agent,
            "previous_agent": self.previous_agent,
            "collected_data": self.collected_data,
            "claude_messages": self._serialize_messages(self.claude_messages),
            "router_context": self.router_context,
            "message_count": self.message_count,
            "booking_id": self.booking_id,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }
        return json.dumps(data)

    def _serialize_messages(self, messages: list[dict]) -> list[dict]:
        """
        Serialize claude_messages for JSON storage.

        Handles potential non-serializable types in tool inputs/outputs.
        """
        serialized = []
        for msg in messages:
            if isinstance(msg.get("content"), list):
                # Message with content blocks (tool_use, tool_result, text)
                serialized_content = []
                for block in msg["content"]:
                    if isinstance(block, dict):
                        serialized_content.append(block)
                    else:
                        # Handle Anthropic SDK objects
                        serialized_content.append(self._block_to_dict(block))
                serialized.append({"role": msg["role"], "content": serialized_content})
            else:
                serialized.append(msg)
        return serialized

    def _block_to_dict(self, block: Any) -> dict:
        """Convert an Anthropic SDK block object to a dict."""
        if hasattr(block, "type"):
            if block.type == "text":
                return {"type": "text", "text": block.text}
            elif block.type == "tool_use":
                return {
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                }
            elif block.type == "tool_result":
                return {
                    "type": "tool_result",
                    "tool_use_id": block.tool_use_id,
                    "content": block.content,
                }
        # Fallback - try to convert to dict
        if hasattr(block, "__dict__"):
            return dict(block.__dict__)
        return {"type": "unknown", "data": str(block)}

    @classmethod
    def from_json(cls, json_str: str) -> "SessionData":
        """Create from JSON string."""
        data = json.loads(json_str)
        return cls(
            session_id=data["session_id"],
            clinic_id=data["clinic_id"],
            patient_id=data.get("patient_id"),
            active_agent=data.get("active_agent"),
            previous_agent=data.get("previous_agent"),
            collected_data=data.get("collected_data", {}),
            claude_messages=data.get("claude_messages", []),
            router_context=data.get("router_context", []),
            message_count=data.get("message_count", 0),
            booking_id=data.get("booking_id"),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
        )

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return json.loads(self.to_json())

    def get_context_for_llm(self) -> dict:
        """
        Get context for LLM prompts.

        Provides backward compatibility with v1 code if needed.
        """
        return {
            "active_agent": self.active_agent,
            "collected": self.collected_data,
            "message_count": self.message_count,
            "booking_id": self.booking_id,
        }
