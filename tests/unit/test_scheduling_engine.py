"""Tests for Scheduling Engine."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

from app.core.scheduling.engine import (
    SchedulingEngine,
    EngineResponse,
)
from app.core.scheduling.calendar_client import (
    TimeSlot,
    BookingResult,
    Provider,
)
from app.core.scheduling.response import ResponseGenerator
from app.core.scheduling.flow import ConversationFlow, FlowAction
from app.core.intelligence.session.models import SessionData
from app.core.intelligence.session.state import BookingState
from app.core.intelligence.intent.types import Intent, IntentResult
from app.core.intelligence.slots.types import ExtractedSlots


class TestSchedulingEngine:
    """Test SchedulingEngine orchestrator."""

    @pytest.fixture
    def mock_calendar_client(self):
        """Create mock calendar client."""
        client = AsyncMock()
        client.list_providers.return_value = [
            Provider(id="doc-1", name="Dr. Smith", specialty="General"),
        ]
        client.find_provider_by_name.return_value = Provider(
            id="doc-1", name="Dr. Smith"
        )
        client.find_available_slots.return_value = [
            TimeSlot(
                slot_id="slot-1",
                provider_id="doc-1",
                provider_name="Dr. Smith",
                start_time="2024-01-15T10:00:00",
                end_time="2024-01-15T10:30:00",
            ),
        ]
        client.create_booking.return_value = BookingResult(
            success=True,
            booking_id="booking-123",
            message="Confirmed",
        )
        return client

    @pytest.fixture
    def mock_response_generator(self):
        """Create mock response generator."""
        generator = MagicMock(spec=ResponseGenerator)
        generator.greeting.return_value = "Hello! How can I help?"
        generator.goodbye.return_value = "Goodbye!"
        generator.handoff.return_value = "Connecting you to staff..."
        generator.out_of_scope.return_value = "I can only help with appointments."
        generator.format_slots.return_value = "Here are available times..."
        generator.confirm_booking.return_value = "Shall I book this?"
        generator.booking_confirmed.return_value = "Your appointment is confirmed!"
        generator.booking_failed.return_value = "Sorry, booking failed."
        generator.generate = AsyncMock(return_value="How can I help you?")
        return generator

    @pytest.fixture
    def mock_flow_manager(self):
        """Create mock flow manager."""
        flow = MagicMock(spec=ConversationFlow)
        flow.process.return_value = FlowAction(
            next_state=BookingState.COLLECT_PROVIDER,
            action_type="collect",
            prompt_for="provider_name",
        )
        return flow

    @pytest.fixture
    def engine(self, mock_calendar_client, mock_response_generator, mock_flow_manager):
        """Create engine with mocks."""
        return SchedulingEngine(
            calendar_client=mock_calendar_client,
            response_generator=mock_response_generator,
            flow_manager=mock_flow_manager,
        )

    # === Response Model Tests ===

    def test_engine_response_to_dict(self):
        """Test EngineResponse conversion."""
        response = EngineResponse(
            message="Hello!",
            session_id="session-123",
            state=BookingState.IDLE,
            intent=Intent.GREETING,
            confidence=0.95,
            processing_time_ms=50.0,
        )

        d = response.to_dict()

        assert d["message"] == "Hello!"
        assert d["session_id"] == "session-123"
        assert d["state"] == "idle"
        assert d["intent"] == "greeting"
        assert d["confidence"] == 0.95

    def test_engine_response_minimal(self):
        """Test minimal response."""
        response = EngineResponse(
            message="Hello!",
            session_id="session-123",
            state=BookingState.IDLE,
        )

        d = response.to_dict()

        assert "intent" not in d
        assert "booking_id" not in d

    # === Process Message Tests ===

    @pytest.mark.asyncio
    @patch("app.core.scheduling.engine.get_session_manager")
    @patch("app.core.scheduling.engine.classify_intent")
    @patch("app.core.scheduling.engine.extract_slots")
    async def test_process_greeting(
        self,
        mock_extract_slots,
        mock_classify_intent,
        mock_get_session_manager,
        engine,
        mock_flow_manager,
        mock_response_generator,
    ):
        """Test processing a greeting message."""
        # Setup mocks
        mock_session = SessionData(
            session_id="session-123",
            clinic_id="clinic-1",
            state=BookingState.IDLE,
        )
        mock_manager = AsyncMock()
        mock_manager.get_or_create.return_value = mock_session
        mock_manager.add_message.return_value = mock_session
        mock_manager.save.return_value = True
        mock_get_session_manager.return_value = mock_manager

        mock_classify_intent.return_value = IntentResult(
            intent=Intent.GREETING, confidence=0.95
        )
        mock_extract_slots.return_value = ExtractedSlots()

        mock_flow_manager.process.return_value = FlowAction(
            next_state=BookingState.IDLE,
            action_type="respond",
            message="greeting",
        )

        # Process message
        response = await engine.process(
            tenant_id="clinic-1",
            message="Hello!",
        )

        assert response.session_id == "session-123"
        assert response.state == BookingState.IDLE
        mock_response_generator.greeting.assert_called_once()

    @pytest.mark.asyncio
    @patch("app.core.scheduling.engine.get_session_manager")
    @patch("app.core.scheduling.engine.classify_intent")
    @patch("app.core.scheduling.engine.extract_slots")
    async def test_process_with_session_id(
        self,
        mock_extract_slots,
        mock_classify_intent,
        mock_get_session_manager,
        engine,
    ):
        """Test processing with existing session ID."""
        mock_session = SessionData(
            session_id="existing-session",
            clinic_id="clinic-1",
            state=BookingState.COLLECT_DATE,
        )
        mock_manager = AsyncMock()
        mock_manager.get_or_create.return_value = mock_session
        mock_manager.add_message.return_value = mock_session
        mock_manager.save.return_value = True
        mock_get_session_manager.return_value = mock_manager

        mock_classify_intent.return_value = IntentResult(
            intent=Intent.PROVIDE_INFO, confidence=0.95
        )
        mock_extract_slots.return_value = ExtractedSlots()

        response = await engine.process(
            tenant_id="clinic-1",
            message="Next Tuesday",
            session_id="existing-session",
        )

        mock_manager.get_or_create.assert_called_with(
            clinic_id="clinic-1",
            session_id="existing-session",
        )

    @pytest.mark.asyncio
    @patch("app.core.scheduling.engine.get_session_manager")
    @patch("app.core.scheduling.engine.classify_intent")
    @patch("app.core.scheduling.engine.extract_slots")
    async def test_process_handoff(
        self,
        mock_extract_slots,
        mock_classify_intent,
        mock_get_session_manager,
        engine,
        mock_flow_manager,
        mock_response_generator,
    ):
        """Test handoff action."""
        mock_session = SessionData(
            session_id="session-123",
            clinic_id="clinic-1",
            state=BookingState.IDLE,
        )
        mock_manager = AsyncMock()
        mock_manager.get_or_create.return_value = mock_session
        mock_manager.add_message.return_value = mock_session
        mock_manager.save.return_value = True
        mock_get_session_manager.return_value = mock_manager

        mock_classify_intent.return_value = IntentResult(
            intent=Intent.HANDOFF, confidence=0.99
        )
        mock_extract_slots.return_value = ExtractedSlots()

        mock_flow_manager.process.return_value = FlowAction(
            next_state=BookingState.HANDED_OFF,
            action_type="handoff",
            message="Transferring to staff",
        )

        response = await engine.process(
            tenant_id="clinic-1",
            message="Let me talk to a human",
        )

        assert response.state == BookingState.HANDED_OFF
        mock_response_generator.handoff.assert_called_once()

    @pytest.mark.asyncio
    @patch("app.core.scheduling.engine.get_session_manager")
    @patch("app.core.scheduling.engine.classify_intent")
    @patch("app.core.scheduling.engine.extract_slots")
    async def test_process_show_slots(
        self,
        mock_extract_slots,
        mock_classify_intent,
        mock_get_session_manager,
        engine,
        mock_flow_manager,
        mock_response_generator,
        mock_calendar_client,
    ):
        """Test showing available slots."""
        mock_session = SessionData(
            session_id="session-123",
            clinic_id="clinic-1",
            state=BookingState.COLLECT_TIME,
            collected_data={"provider_name": "Smith", "date": "2024-01-15"},
        )
        mock_manager = AsyncMock()
        mock_manager.get_or_create.return_value = mock_session
        mock_manager.add_message.return_value = mock_session
        mock_manager.save.return_value = True
        mock_get_session_manager.return_value = mock_manager

        mock_classify_intent.return_value = IntentResult(
            intent=Intent.PROVIDE_INFO, confidence=0.95
        )
        mock_extract_slots.return_value = ExtractedSlots()

        mock_flow_manager.process.return_value = FlowAction(
            next_state=BookingState.SHOWING_SLOTS,
            action_type="show_slots",
            should_search_slots=True,
        )

        response = await engine.process(
            tenant_id="clinic-1",
            message="Show me times",
        )

        assert response.available_slots is not None
        mock_calendar_client.find_available_slots.assert_called()
        mock_response_generator.format_slots.assert_called()

    @pytest.mark.asyncio
    @patch("app.core.scheduling.engine.get_session_manager")
    @patch("app.core.scheduling.engine.classify_intent")
    @patch("app.core.scheduling.engine.extract_slots")
    async def test_process_booking_success(
        self,
        mock_extract_slots,
        mock_classify_intent,
        mock_get_session_manager,
        engine,
        mock_flow_manager,
        mock_response_generator,
        mock_calendar_client,
    ):
        """Test successful booking."""
        mock_session = SessionData(
            session_id="session-123",
            clinic_id="clinic-1",
            state=BookingState.CONFIRM_BOOKING,
            collected_data={
                "provider_name": "Dr. Smith",
                "date": "2024-01-15",
                "time": "10:00",
                "patient_name": "John",
                "slot_id": "slot-1",
            },
        )
        mock_manager = AsyncMock()
        mock_manager.get_or_create.return_value = mock_session
        mock_manager.add_message.return_value = mock_session
        mock_manager.save.return_value = True
        mock_get_session_manager.return_value = mock_manager

        mock_classify_intent.return_value = IntentResult(
            intent=Intent.CONFIRMATION, confidence=0.99
        )
        mock_extract_slots.return_value = ExtractedSlots()

        mock_flow_manager.process.return_value = FlowAction(
            next_state=BookingState.BOOKED,
            action_type="book",
            should_book=True,
        )

        response = await engine.process(
            tenant_id="clinic-1",
            message="Yes, book it",
        )

        assert response.booking_id == "booking-123"
        mock_calendar_client.create_booking.assert_called()
        mock_response_generator.booking_confirmed.assert_called()

    @pytest.mark.asyncio
    @patch("app.core.scheduling.engine.get_session_manager")
    @patch("app.core.scheduling.engine.classify_intent")
    @patch("app.core.scheduling.engine.extract_slots")
    async def test_process_booking_failure(
        self,
        mock_extract_slots,
        mock_classify_intent,
        mock_get_session_manager,
        engine,
        mock_flow_manager,
        mock_response_generator,
        mock_calendar_client,
    ):
        """Test failed booking."""
        mock_session = SessionData(
            session_id="session-123",
            clinic_id="clinic-1",
            state=BookingState.CONFIRM_BOOKING,
            collected_data={
                "provider_name": "Dr. Smith",
                "slot_id": "slot-1",
                "patient_name": "John",
            },
        )
        mock_manager = AsyncMock()
        mock_manager.get_or_create.return_value = mock_session
        mock_manager.add_message.return_value = mock_session
        mock_manager.save.return_value = True
        mock_get_session_manager.return_value = mock_manager

        mock_classify_intent.return_value = IntentResult(
            intent=Intent.CONFIRMATION, confidence=0.99
        )
        mock_extract_slots.return_value = ExtractedSlots()

        mock_flow_manager.process.return_value = FlowAction(
            next_state=BookingState.BOOKED,
            action_type="book",
            should_book=True,
        )

        mock_calendar_client.create_booking.return_value = BookingResult(
            success=False,
            error_code="slot_taken",
            message="Slot no longer available",
        )

        response = await engine.process(
            tenant_id="clinic-1",
            message="Yes",
        )

        assert response.booking_id is None
        mock_response_generator.booking_failed.assert_called()

    # === Helper Method Tests ===

    def test_build_classification_context(self, engine):
        """Test building classification context."""
        session = SessionData(
            session_id="session-123",
            clinic_id="clinic-1",
            state=BookingState.COLLECT_DATE,
            collected_data={"provider_name": "Dr. Smith"},
            last_bot_question="What date works?",
        )
        session.add_turn("assistant", "What date works?")
        session.add_turn("user", "Tomorrow")

        context = engine._build_classification_context(session)

        assert context["state"] == "collect_date"
        assert context["collected"]["provider_name"] == "Dr. Smith"
        assert context["last_bot_question"] == "What date works?"
        assert context["turn_count"] == 2

    def test_get_time_preference_morning(self, engine):
        """Test extracting morning preference."""
        collected = {"time_raw": "morning please"}

        pref = engine._get_time_preference(collected)

        assert pref == "morning"

    def test_get_time_preference_afternoon(self, engine):
        """Test extracting afternoon preference."""
        collected = {"time_raw": "around 2pm"}

        pref = engine._get_time_preference(collected)

        assert pref == "afternoon"

    def test_get_time_preference_none(self, engine):
        """Test no time preference."""
        collected = {}

        pref = engine._get_time_preference(collected)

        assert pref is None

    # === Session Management Tests ===

    @pytest.mark.asyncio
    @patch("app.core.scheduling.engine.get_session_manager")
    async def test_get_session(self, mock_get_session_manager, engine):
        """Test getting session."""
        mock_session = SessionData(
            session_id="session-123",
            clinic_id="clinic-1",
        )
        mock_manager = AsyncMock()
        mock_manager.get.return_value = mock_session
        mock_get_session_manager.return_value = mock_manager

        session = await engine.get_session("clinic-1", "session-123")

        assert session.session_id == "session-123"
        mock_manager.get.assert_called_with("clinic-1", "session-123")

    @pytest.mark.asyncio
    @patch("app.core.scheduling.engine.get_session_manager")
    async def test_reset_session(self, mock_get_session_manager, engine):
        """Test resetting session."""
        mock_session = SessionData(
            session_id="session-123",
            clinic_id="clinic-1",
            state=BookingState.COLLECT_DATE,
            collected_data={"provider_name": "Smith"},
        )
        mock_session.add_turn("user", "hello")
        mock_manager = AsyncMock()
        mock_manager.get.return_value = mock_session
        mock_manager.save.return_value = True
        mock_get_session_manager.return_value = mock_manager

        session = await engine.reset_session("clinic-1", "session-123")

        assert session.state == BookingState.IDLE
        assert session.collected_data == {}
        assert len(session.message_history) == 0
