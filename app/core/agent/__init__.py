"""
Agent Module - v2 Multi-Agent Architecture

This module contains the v2 agent-based architecture for the AI Receptionist:
- Router: Message routing with tool_use for structured output
- Agents: Domain-specific agents (scheduling, faq, conversation, handoff)
- Handlers: Deterministic handlers (crisis)
- Dispatch: Main orchestrator
- MCP Bridge: Tool bridge for Calendar Agent
"""

from app.core.agent.router_types import RouteResult
from app.core.agent.router import MessageRouter, get_router
from app.core.agent.base import BaseAgent
from app.core.agent.dispatch import Dispatcher, DispatchResponse, get_dispatcher
from app.core.agent.mcp_bridge import CalendarToolBridge, get_calendar_bridge

# Agents
from app.core.agent.agents.scheduling import SchedulingAgent
from app.core.agent.agents.faq import FAQAgent
from app.core.agent.agents.conversation import ConversationAgent
from app.core.agent.agents.handoff import HandoffAgent

# Handlers
from app.core.agent.handlers.crisis import CrisisHandler

__all__ = [
    # Router
    "RouteResult",
    "MessageRouter",
    "get_router",
    # Base
    "BaseAgent",
    # Dispatch
    "Dispatcher",
    "DispatchResponse",
    "get_dispatcher",
    # MCP Bridge
    "CalendarToolBridge",
    "get_calendar_bridge",
    # Agents
    "SchedulingAgent",
    "FAQAgent",
    "ConversationAgent",
    "HandoffAgent",
    # Handlers
    "CrisisHandler",
]
