"""Session data models."""

import json
from dataclasses import dataclass, field
from datetime import datetime, date, time, timezone
from typing import Any, Optional
from uuid import UUID, uuid4


def _utcnow() -> datetime:
    """Get current UTC time as timezone-aware datetime."""
    return datetime.now(timezone.utc)

from app.core.intelligence.intent.types import Intent
from app.core.intelligence.slots.types import ExtractedSlots, AppointmentType
from app.core.intelligence.session.state import BookingState, can_transition


@dataclass
class ConversationTurn:
    """A single turn in the conversation."""

    role: str  # "user" or "assistant"
    content: str
    timestamp: datetime = field(default_factory=_utcnow)
    intent: Optional[Intent] = None
    slots: Optional[ExtractedSlots] = None

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
            "intent": self.intent.value if self.intent else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ConversationTurn":
        """Create from dictionary."""
        return cls(
            role=data["role"],
            content=data["content"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            intent=Intent(data["intent"]) if data.get("intent") else None,
        )


@dataclass
class SessionData:
    """Complete session data stored in Redis."""

    # Identifiers
    session_id: str = field(default_factory=lambda: str(uuid4()))
    clinic_id: str = ""
    patient_id: Optional[str] = None

    # State
    state: BookingState = BookingState.IDLE
    previous_state: Optional[BookingState] = None

    # Accumulated slots from conversation
    collected_data: dict = field(default_factory=dict)

    # Current intent context
    current_intent: Optional[str] = None

    # Intent history
    intent_history: list[str] = field(default_factory=list)

    # Conversation history (last N turns)
    message_history: list[dict] = field(default_factory=list)
    max_history_turns: int = 10

    # Message count
    message_count: int = 0

    # Shown slots from availability search
    shown_slots: list[dict] = field(default_factory=list)

    # Selected slot
    selected_slot: Optional[dict] = None

    # Booking result
    booking_id: Optional[str] = None

    # Awaiting confirmation flag
    awaiting_confirmation: bool = False

    # Last bot question
    last_bot_question: Optional[str] = None

    # Timestamps
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)

    def add_turn(
        self,
        role: str,
        content: str,
        intent: Optional[Intent] = None,
        slots: Optional[ExtractedSlots] = None,
    ) -> None:
        """Add a conversation turn, maintaining max history."""
        turn = {
            "role": role,
            "content": content,
            "timestamp": _utcnow().isoformat(),
            "intent": intent.value if intent else None,
        }
        self.message_history.append(turn)

        # Trim to max size
        if len(self.message_history) > self.max_history_turns:
            self.message_history = self.message_history[-self.max_history_turns:]

        # Track intent
        if intent:
            self.current_intent = intent.value
            self.intent_history.append(intent.value)

        # Merge slots into collected data
        if slots and slots.has_any():
            slot_dict = slots.to_dict()
            for key, value in slot_dict.items():
                if value is not None:
                    self.collected_data[key] = value

        self.message_count += 1
        self.updated_at = _utcnow()

    def transition_to(self, new_state: BookingState) -> bool:
        """Attempt to transition to a new state."""
        if can_transition(self.state, new_state):
            self.previous_state = self.state
            self.state = new_state
            self.updated_at = _utcnow()
            return True
        return False

    def get_context_for_llm(self) -> dict:
        """Get context for LLM prompts."""
        return {
            "state": self.state.value,
            "collected": self.collected_data,
            "awaiting_confirmation": self.awaiting_confirmation,
            "last_bot_question": self.last_bot_question,
            "message_count": self.message_count,
        }

    def to_json(self) -> str:
        """Convert to JSON string for Redis storage."""
        data = {
            "session_id": self.session_id,
            "clinic_id": self.clinic_id,
            "patient_id": self.patient_id,
            "state": self.state.value,
            "previous_state": self.previous_state.value if self.previous_state else None,
            "collected_data": self.collected_data,
            "current_intent": self.current_intent,
            "intent_history": self.intent_history,
            "message_history": self.message_history,
            "message_count": self.message_count,
            "shown_slots": self.shown_slots,
            "selected_slot": self.selected_slot,
            "booking_id": self.booking_id,
            "awaiting_confirmation": self.awaiting_confirmation,
            "last_bot_question": self.last_bot_question,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }
        return json.dumps(data)

    @classmethod
    def from_json(cls, json_str: str) -> "SessionData":
        """Create from JSON string."""
        data = json.loads(json_str)
        return cls(
            session_id=data["session_id"],
            clinic_id=data["clinic_id"],
            patient_id=data.get("patient_id"),
            state=BookingState(data["state"]),
            previous_state=BookingState(data["previous_state"]) if data.get("previous_state") else None,
            collected_data=data.get("collected_data", {}),
            current_intent=data.get("current_intent"),
            intent_history=data.get("intent_history", []),
            message_history=data.get("message_history", []),
            message_count=data.get("message_count", 0),
            shown_slots=data.get("shown_slots", []),
            selected_slot=data.get("selected_slot"),
            booking_id=data.get("booking_id"),
            awaiting_confirmation=data.get("awaiting_confirmation", False),
            last_bot_question=data.get("last_bot_question"),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
        )

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return json.loads(self.to_json())
