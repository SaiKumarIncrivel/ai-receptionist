"""
Domain Agents for v2 Multi-Agent Architecture.

Each agent handles a specific domain:
- SchedulingAgent: Appointment booking with Calendar Agent tools
- FAQAgent: Clinic information questions
- ConversationAgent: Greetings, goodbyes, out-of-scope
- HandoffAgent: Transfer to human staff
"""

from app.core.agent.agents.scheduling import SchedulingAgent
from app.core.agent.agents.faq import FAQAgent
from app.core.agent.agents.conversation import ConversationAgent
from app.core.agent.agents.handoff import HandoffAgent

__all__ = [
    "SchedulingAgent",
    "FAQAgent",
    "ConversationAgent",
    "HandoffAgent",
]
