"""
Intelligence Layer Module - v2 Multi-Agent Architecture

For v2, the main entry points are:
- SessionData, SessionManager: Session management with full Claude message format
- The router and agents handle intent/slot work via tool_use

The v1 components (intent classifier, slot extractor, context builder) have been
removed. All routing and entity extraction is now handled by the router and agents.
"""

# Session Management (v2)
from app.core.intelligence.session.models import SessionData
from app.core.intelligence.session.manager import SessionManager, get_session_manager

__all__ = [
    # Session (v2)
    "SessionData",
    "SessionManager",
    "get_session_manager",
]
