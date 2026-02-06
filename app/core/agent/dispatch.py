"""
Dispatcher for v2 Multi-Agent Architecture.

Main orchestrator that replaces SchedulingEngine.
Routes messages to appropriate agents based on router decision.
Integrates with safety pipeline for input/output processing.
"""

import logging
import time
from dataclasses import dataclass
from typing import Optional

from app.config import settings
from app.infra.claude import ClaudeClient
from app.core.agent.router import MessageRouter, get_router
from app.core.agent.router_types import RouteResult
from app.core.agent.agents.scheduling import SchedulingAgent
from app.core.agent.agents.faq import FAQAgent
from app.core.agent.agents.conversation import ConversationAgent
from app.core.agent.agents.handoff import HandoffAgent
from app.core.agent.handlers.crisis import CrisisHandler
from app.core.intelligence.session.manager import SessionManager, get_session_manager
from app.core.intelligence.session.models import SessionData

logger = logging.getLogger(__name__)


@dataclass
class DispatchResponse:
    """
    Response from the dispatch system.

    Backward-compatible with EngineResponse - maps to ChatResponse fields.
    """

    message: str
    session_id: str
    domain: str  # Maps to 'state' in API for backward compat
    sub_intent: Optional[str] = None  # Maps to 'intent' in API
    confidence: Optional[float] = None
    booking_id: Optional[str] = None
    collected_data: Optional[dict] = None
    processing_time_ms: Optional[float] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for API response."""
        result = {
            "message": self.message,
            "session_id": self.session_id,
            "state": self.domain,  # Map domain -> state for API compat
        }
        if self.sub_intent:
            result["intent"] = self.sub_intent
        if self.confidence is not None:
            result["confidence"] = self.confidence
        if self.booking_id:
            result["booking_id"] = self.booking_id
        if self.collected_data:
            result["collected_data"] = self.collected_data
        if self.processing_time_ms is not None:
            result["processing_time_ms"] = self.processing_time_ms
        return result


class Dispatcher:
    """
    Main orchestrator for v2 multi-agent architecture.

    Replaces SchedulingEngine with a cleaner, agent-based approach.

    Flow:
    1. Get or create session
    2. Safety pipeline (input) - PII, crisis, sanitization
    3. If crisis detected by safety -> crisis handler (skip router)
    4. Route message via router
    5. Dispatch to correct agent based on domain
    6. Safety pipeline (output) - PII scrubbing
    7. Save session
    8. Return response
    """

    def __init__(self):
        """Initialize dispatcher with lazy-loaded components."""
        self._claude: Optional[ClaudeClient] = None
        self._router: Optional[MessageRouter] = None
        self._session_mgr: Optional[SessionManager] = None

        # Agents (lazy initialized)
        self._scheduling_agent: Optional[SchedulingAgent] = None
        self._faq_agent: Optional[FAQAgent] = None
        self._conversation_agent: Optional[ConversationAgent] = None
        self._handoff_agent: Optional[HandoffAgent] = None

        # Deterministic handler (always available)
        self._crisis_handler = CrisisHandler()

        # Safety pipeline (lazy initialized)
        self._safety_pipelines: dict = {}

    # === Lazy Initialization ===

    def _get_claude(self) -> ClaudeClient:
        """Get Claude client."""
        if self._claude is None:
            self._claude = ClaudeClient.get_instance()
        return self._claude

    def _get_router(self) -> MessageRouter:
        """Get message router."""
        if self._router is None:
            self._router = get_router()
        return self._router

    async def _get_session_manager(self) -> SessionManager:
        """Get session manager."""
        if self._session_mgr is None:
            self._session_mgr = await get_session_manager()
        return self._session_mgr

    def _get_scheduling_agent(self) -> SchedulingAgent:
        """Get scheduling agent."""
        if self._scheduling_agent is None:
            self._scheduling_agent = SchedulingAgent(claude_client=self._get_claude())
        return self._scheduling_agent

    def _get_faq_agent(self) -> FAQAgent:
        """Get FAQ agent."""
        if self._faq_agent is None:
            self._faq_agent = FAQAgent(claude_client=self._get_claude())
        return self._faq_agent

    def _get_conversation_agent(self) -> ConversationAgent:
        """Get conversation agent."""
        if self._conversation_agent is None:
            self._conversation_agent = ConversationAgent(claude_client=self._get_claude())
        return self._conversation_agent

    def _get_handoff_agent(self) -> HandoffAgent:
        """Get handoff agent."""
        if self._handoff_agent is None:
            self._handoff_agent = HandoffAgent(claude_client=self._get_claude())
        return self._handoff_agent

    def _get_safety_pipeline(self, tenant_id: str):
        """
        Get safety pipeline for tenant.

        Imports here to avoid circular dependencies and allow
        running without safety module in tests.
        """
        if tenant_id not in self._safety_pipelines:
            try:
                from app.safety.pipeline import SafetyPipeline
                self._safety_pipelines[tenant_id] = SafetyPipeline(clinic_id=tenant_id)
            except ImportError:
                logger.warning("Safety pipeline not available, using pass-through")
                self._safety_pipelines[tenant_id] = None
        return self._safety_pipelines[tenant_id]

    # === Main Processing ===

    async def process(
        self,
        tenant_id: str,
        message: str,
        session_id: Optional[str] = None,
    ) -> DispatchResponse:
        """
        Process a patient message through the full v2 pipeline.

        Args:
            tenant_id: Clinic/tenant identifier
            message: Patient's message
            session_id: Optional existing session ID

        Returns:
            DispatchResponse with message, session_id, and metadata
        """
        start_time = time.time()

        # 1. Get or create session
        session_mgr = await self._get_session_manager()
        session = await session_mgr.get_or_create(
            clinic_id=tenant_id,
            session_id=session_id,
        )

        try:
            # 2. Safety pipeline (input)
            clean_message = message
            crisis_detected = False

            safety = self._get_safety_pipeline(tenant_id)
            if safety:
                try:
                    from app.safety.pipeline import PipelineContext

                    ctx = PipelineContext(
                        clinic_id=tenant_id,
                        patient_id=session.patient_id,
                        session_id=session.session_id,
                    )
                    input_result = safety.process_input(message, ctx)

                    # Check for crisis
                    if input_result.has_crisis:
                        crisis_detected = True

                    # Check if we can proceed
                    if not input_result.can_proceed:
                        if crisis_detected:
                            response_text = self._crisis_handler.respond(message, session)
                        else:
                            response_text = (
                                input_result.suggested_response
                                or "I'm not able to help with that. Is there something else I can assist with?"
                            )

                        return await self._build_response(
                            session=session,
                            session_mgr=session_mgr,
                            response_text=response_text,
                            domain="blocked" if not crisis_detected else "crisis",
                            sub_intent=None,
                            confidence=None,
                            start_time=start_time,
                        )

                    # Use sanitized text
                    clean_message = input_result.processed_text

                except Exception as e:
                    logger.warning(f"Safety pipeline error (continuing): {e}")

            # 3. Route message
            router = self._get_router()
            route = await router.route(
                message=clean_message,
                session_context=session.get_router_context_str(),
            )

            # 4. Override with crisis if safety detected it
            if crisis_detected:
                route = RouteResult(
                    domain="crisis",
                    confidence=1.0,
                    sub_intent="question",
                    entities={},
                    urgency="high",
                )

            # 5. Dispatch to agent
            response_text = await self._dispatch_to_agent(
                route=route,
                session=session,
                message=clean_message,
                tenant_id=tenant_id,
            )

            # 6. Safety pipeline (output)
            if safety and response_text:
                try:
                    from app.safety.pipeline import PipelineContext

                    ctx = PipelineContext(
                        clinic_id=tenant_id,
                        patient_id=session.patient_id,
                        session_id=session.session_id,
                    )
                    output_result = safety.process_output(response_text, ctx)

                    if not output_result.can_send:
                        response_text = (
                            output_result.fallback_response
                            or "I apologize, but I need to rephrase that. How else can I help you?"
                        )
                    else:
                        response_text = output_result.processed_text

                except Exception as e:
                    logger.warning(f"Output safety error (continuing): {e}")

            # 7. Build and return response
            return await self._build_response(
                session=session,
                session_mgr=session_mgr,
                response_text=response_text,
                domain=route.domain,
                sub_intent=route.sub_intent,
                confidence=route.confidence,
                start_time=start_time,
            )

        except Exception as e:
            logger.exception(f"Error processing message: {e}")

            # Return safe fallback
            return DispatchResponse(
                message="I'm having some trouble right now. Let me connect you with the front desk.",
                session_id=session.session_id,
                domain="error",
                processing_time_ms=(time.time() - start_time) * 1000,
            )

    async def _dispatch_to_agent(
        self,
        route: RouteResult,
        session: SessionData,
        message: str,
        tenant_id: str,
    ) -> str:
        """
        Dispatch to the appropriate agent based on route domain.

        Args:
            route: Router result
            session: Current session
            message: Patient's message
            tenant_id: Clinic/tenant ID

        Returns:
            Agent's response text
        """
        # Track agent switching
        if route.domain in ("scheduling", "faq") and route.domain != session.active_agent:
            session.previous_agent = session.active_agent
            session.active_agent = route.domain

        match route.domain:
            case "scheduling":
                agent = self._get_scheduling_agent()
                return await agent.handle(
                    message=message,
                    session=session,
                    route=route,
                    tenant_id=tenant_id,
                )

            case "faq":
                agent = self._get_faq_agent()
                return await agent.handle(
                    message=message,
                    session=session,
                    route=route,
                    tenant_id=tenant_id,
                )

            case "crisis":
                # Deterministic - no AI
                return self._crisis_handler.respond(message, session)

            case "handoff":
                agent = self._get_handoff_agent()
                return await agent.handle(
                    message=message,
                    session=session,
                    route=route,
                    tenant_id=tenant_id,
                )

            case "greeting" | "goodbye" | "out_of_scope":
                agent = self._get_conversation_agent()
                return await agent.handle(
                    message=message,
                    session=session,
                    route=route,
                    tenant_id=tenant_id,
                )

            case _:
                # Unknown domain - use conversation agent
                logger.warning(f"Unknown domain: {route.domain}, using conversation agent")
                agent = self._get_conversation_agent()
                return await agent.handle(
                    message=message,
                    session=session,
                    route=route,
                    tenant_id=tenant_id,
                )

    async def _build_response(
        self,
        session: SessionData,
        session_mgr: SessionManager,
        response_text: str,
        domain: str,
        sub_intent: Optional[str],
        confidence: Optional[float],
        start_time: float,
    ) -> DispatchResponse:
        """Build response and save session."""
        # Save session
        await session_mgr.save(session)

        # Calculate processing time
        processing_time_ms = (time.time() - start_time) * 1000

        return DispatchResponse(
            message=response_text,
            session_id=session.session_id,
            domain=session.active_agent or domain,
            sub_intent=sub_intent,
            confidence=confidence,
            booking_id=session.booking_id,
            collected_data=session.collected_data if session.collected_data else None,
            processing_time_ms=processing_time_ms,
        )

    # === Session Management (for API compatibility) ===

    async def get_session(
        self,
        tenant_id: str,
        session_id: str,
    ) -> Optional[SessionData]:
        """
        Get session by ID.

        Args:
            tenant_id: Clinic/tenant identifier
            session_id: Session identifier

        Returns:
            SessionData or None if not found
        """
        session_mgr = await self._get_session_manager()
        return await session_mgr.get(clinic_id=tenant_id, session_id=session_id)

    async def reset_session(
        self,
        tenant_id: str,
        session_id: str,
    ) -> Optional[SessionData]:
        """
        Reset session to initial state.

        Args:
            tenant_id: Clinic/tenant identifier
            session_id: Session identifier

        Returns:
            Reset SessionData or None if not found
        """
        session_mgr = await self._get_session_manager()
        return await session_mgr.reset(clinic_id=tenant_id, session_id=session_id)


# Singleton
_dispatcher: Optional[Dispatcher] = None


def get_dispatcher() -> Dispatcher:
    """Get singleton Dispatcher."""
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = Dispatcher()
    return _dispatcher
