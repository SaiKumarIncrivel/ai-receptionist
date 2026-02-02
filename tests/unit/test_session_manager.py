"""Tests for session management."""

import pytest
from unittest.mock import AsyncMock, patch
from datetime import datetime

from app.core.intelligence.session.manager import SessionManager
from app.core.intelligence.session.models import SessionData
from app.core.intelligence.session.state import BookingState, can_transition


class TestSessionManager:
    """Test Redis session management."""

    @pytest.fixture
    def mock_redis(self):
        """Create mock Redis client."""
        mock = AsyncMock()
        mock.get = AsyncMock(return_value=None)
        mock.setex = AsyncMock()
        mock.set = AsyncMock()
        mock.delete = AsyncMock(return_value=1)
        mock.expire = AsyncMock(return_value=True)
        return mock

    @pytest.fixture
    def manager(self):
        """Create session manager."""
        return SessionManager()

    @pytest.mark.asyncio
    async def test_create_session(self, manager, mock_redis):
        """Test session creation."""
        with patch(
            "app.core.intelligence.session.manager.get_redis",
            return_value=mock_redis,
        ):
            session = await manager.create(clinic_id="clinic-123")

            assert session.session_id is not None
            assert session.clinic_id == "clinic-123"
            assert session.state == BookingState.IDLE
            mock_redis.setex.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_session_fallback(self, manager):
        """Test session creation with Redis unavailable."""
        with patch(
            "app.core.intelligence.session.manager.get_redis",
            return_value=None,
        ):
            session = await manager.create(clinic_id="clinic-123")

            assert session.session_id is not None
            assert session.clinic_id == "clinic-123"
            # Check in-memory fallback
            assert session.session_id in manager._in_memory_fallback

    @pytest.mark.asyncio
    async def test_get_existing(self, manager, mock_redis):
        """Test getting existing session."""
        existing = SessionData(
            session_id="sess-123",
            clinic_id="clinic-456",
            state=BookingState.COLLECT_DATE,
        )
        mock_redis.get = AsyncMock(return_value=existing.to_json())

        with patch(
            "app.core.intelligence.session.manager.get_redis",
            return_value=mock_redis,
        ):
            session = await manager.get("clinic-456", "sess-123")

            assert session is not None
            assert session.session_id == "sess-123"
            assert session.state == BookingState.COLLECT_DATE

    @pytest.mark.asyncio
    async def test_get_nonexistent(self, manager, mock_redis):
        """Test getting non-existent session."""
        mock_redis.get = AsyncMock(return_value=None)

        with patch(
            "app.core.intelligence.session.manager.get_redis",
            return_value=mock_redis,
        ):
            session = await manager.get("clinic-456", "nonexistent")

            assert session is None

    @pytest.mark.asyncio
    async def test_get_or_create_existing(self, manager, mock_redis):
        """Test get_or_create with existing session."""
        existing = SessionData(
            session_id="existing-123",
            clinic_id="clinic-123",
        )
        mock_redis.get = AsyncMock(return_value=existing.to_json())

        with patch(
            "app.core.intelligence.session.manager.get_redis",
            return_value=mock_redis,
        ):
            session = await manager.get_or_create("clinic-123", "existing-123")

            assert session.session_id == "existing-123"
            mock_redis.expire.assert_called_once()  # TTL refreshed

    @pytest.mark.asyncio
    async def test_get_or_create_new(self, manager, mock_redis):
        """Test get_or_create creates new if not found."""
        mock_redis.get = AsyncMock(return_value=None)

        with patch(
            "app.core.intelligence.session.manager.get_redis",
            return_value=mock_redis,
        ):
            session = await manager.get_or_create("clinic-123", "nonexistent")

            assert session.session_id is not None
            assert session.session_id != "nonexistent"

    @pytest.mark.asyncio
    async def test_update_state_valid(self, manager, mock_redis):
        """Test valid state update."""
        existing = SessionData(
            session_id="sess-123",
            clinic_id="clinic-456",
            state=BookingState.IDLE,
        )
        mock_redis.get = AsyncMock(return_value=existing.to_json())

        with patch(
            "app.core.intelligence.session.manager.get_redis",
            return_value=mock_redis,
        ):
            updated = await manager.update_state(
                "clinic-456", "sess-123", BookingState.COLLECT_PROVIDER
            )

            assert updated is not None
            assert updated.state == BookingState.COLLECT_PROVIDER
            assert updated.previous_state == BookingState.IDLE

    @pytest.mark.asyncio
    async def test_update_state_invalid(self, manager, mock_redis):
        """Test invalid state transition is rejected."""
        existing = SessionData(
            session_id="sess-123",
            clinic_id="clinic-456",
            state=BookingState.IDLE,
        )
        mock_redis.get = AsyncMock(return_value=existing.to_json())

        with patch(
            "app.core.intelligence.session.manager.get_redis",
            return_value=mock_redis,
        ):
            # IDLE -> BOOKED is not valid
            updated = await manager.update_state(
                "clinic-456", "sess-123", BookingState.BOOKED
            )

            assert updated is None

    @pytest.mark.asyncio
    async def test_update_collected(self, manager, mock_redis):
        """Test updating collected data."""
        existing = SessionData(
            session_id="sess-123",
            clinic_id="clinic-456",
        )
        mock_redis.get = AsyncMock(return_value=existing.to_json())

        with patch(
            "app.core.intelligence.session.manager.get_redis",
            return_value=mock_redis,
        ):
            updated = await manager.update_collected(
                "clinic-456",
                "sess-123",
                {"provider_name": "Dr. Smith", "date_raw": "Tuesday"},
            )

            assert updated is not None
            assert updated.collected_data["provider_name"] == "Dr. Smith"
            assert updated.collected_data["date_raw"] == "Tuesday"

    @pytest.mark.asyncio
    async def test_delete_session(self, manager, mock_redis):
        """Test session deletion."""
        with patch(
            "app.core.intelligence.session.manager.get_redis",
            return_value=mock_redis,
        ):
            result = await manager.delete("clinic-456", "sess-123")

            assert result is True
            mock_redis.delete.assert_called_once()


class TestSessionData:
    """Test SessionData model."""

    def test_serialization_roundtrip(self):
        """Test JSON serialization/deserialization."""
        session = SessionData(
            session_id="test-123",
            clinic_id="clinic-456",
            state=BookingState.COLLECT_DATE,
            collected_data={"provider_name": "Dr. Smith"},
        )

        json_str = session.to_json()
        restored = SessionData.from_json(json_str)

        assert restored.session_id == session.session_id
        assert restored.state == session.state
        assert restored.collected_data == session.collected_data

    def test_add_turn(self):
        """Test adding conversation turns."""
        session = SessionData(
            session_id="test-123",
            clinic_id="clinic-456",
        )

        session.add_turn("user", "Hello")
        session.add_turn("assistant", "How can I help?")

        assert len(session.message_history) == 2
        assert session.message_count == 2
        assert session.message_history[0]["role"] == "user"
        assert session.message_history[1]["role"] == "assistant"

    def test_add_turn_with_intent(self):
        """Test adding turn with intent tracking."""
        from app.core.intelligence.intent.types import Intent

        session = SessionData(
            session_id="test-123",
            clinic_id="clinic-456",
        )

        session.add_turn("user", "I need an appointment", intent=Intent.SCHEDULING)

        assert session.current_intent == "scheduling"
        assert "scheduling" in session.intent_history

    def test_transition_to_valid(self):
        """Test valid state transition."""
        session = SessionData(state=BookingState.IDLE)

        success = session.transition_to(BookingState.COLLECT_PROVIDER)

        assert success is True
        assert session.state == BookingState.COLLECT_PROVIDER
        assert session.previous_state == BookingState.IDLE

    def test_transition_to_invalid(self):
        """Test invalid state transition."""
        session = SessionData(state=BookingState.COMPLETED)

        success = session.transition_to(BookingState.COLLECT_PROVIDER)

        assert success is False
        assert session.state == BookingState.COMPLETED  # Unchanged

    def test_get_context_for_llm(self):
        """Test LLM context generation."""
        session = SessionData(
            session_id="test-123",
            clinic_id="clinic-456",
            state=BookingState.CONFIRM_BOOKING,
            collected_data={"provider_name": "Dr. Smith", "date_raw": "Tuesday"},
            awaiting_confirmation=True,
        )

        context = session.get_context_for_llm()

        assert context["state"] == "confirm_booking"
        assert context["awaiting_confirmation"] is True
        assert "provider_name" in context["collected"]

    def test_max_history_limit(self):
        """Test history is limited to max turns."""
        session = SessionData(max_history_turns=3)

        for i in range(5):
            session.add_turn("user", f"Message {i}")

        assert len(session.message_history) == 3
        assert session.message_count == 5


class TestBookingState:
    """Test booking state transitions."""

    def test_valid_transitions_from_idle(self):
        """Test valid transitions from IDLE."""
        assert can_transition(BookingState.IDLE, BookingState.COLLECT_PROVIDER)
        assert can_transition(BookingState.IDLE, BookingState.COLLECT_DATE)
        assert can_transition(BookingState.IDLE, BookingState.HANDED_OFF)

    def test_invalid_transitions_from_idle(self):
        """Test invalid transitions from IDLE."""
        assert not can_transition(BookingState.IDLE, BookingState.BOOKED)
        assert not can_transition(BookingState.IDLE, BookingState.COMPLETED)

    def test_terminal_state(self):
        """Test COMPLETED is terminal."""
        assert not can_transition(BookingState.COMPLETED, BookingState.IDLE)
        assert not can_transition(BookingState.COMPLETED, BookingState.COLLECT_DATE)

    def test_booking_flow(self):
        """Test typical booking flow transitions."""
        # IDLE -> COLLECT_DATE -> COLLECT_TIME -> SEARCHING -> SHOWING_SLOTS -> CONFIRM -> BOOKED
        assert can_transition(BookingState.IDLE, BookingState.COLLECT_DATE)
        assert can_transition(BookingState.COLLECT_DATE, BookingState.COLLECT_TIME)
        assert can_transition(BookingState.COLLECT_TIME, BookingState.SEARCHING)
        assert can_transition(BookingState.SEARCHING, BookingState.SHOWING_SLOTS)
        assert can_transition(BookingState.SHOWING_SLOTS, BookingState.CONFIRM_BOOKING)
        assert can_transition(BookingState.CONFIRM_BOOKING, BookingState.BOOKED)
        assert can_transition(BookingState.BOOKED, BookingState.COMPLETED)
