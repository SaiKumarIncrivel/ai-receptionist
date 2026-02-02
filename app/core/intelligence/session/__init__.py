"""Session management module."""

from .state import (
    BookingState,
    can_transition,
    get_valid_transitions,
    is_terminal_state,
    is_collecting_state,
)
from .models import SessionData, ConversationTurn
from .manager import SessionManager, get_session_manager

__all__ = [
    # State machine
    "BookingState",
    "can_transition",
    "get_valid_transitions",
    "is_terminal_state",
    "is_collecting_state",
    # Models
    "SessionData",
    "ConversationTurn",
    # Manager
    "SessionManager",
    "get_session_manager",
]
