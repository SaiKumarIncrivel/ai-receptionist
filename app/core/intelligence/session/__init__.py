"""
Session management module for v2 multi-agent architecture.

v2 Changes:
- Removed BookingState state machine (Claude handles flow)
- Removed ConversationTurn (replaced by full Claude message format)
- SessionData now stores full claude_messages with tool_use blocks
"""

from .models import SessionData
from .manager import SessionManager, get_session_manager

__all__ = [
    # Models
    "SessionData",
    # Manager
    "SessionManager",
    "get_session_manager",
]
