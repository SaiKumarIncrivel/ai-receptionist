"""Tests for v2 session management."""

import pytest
from unittest.mock import AsyncMock, patch
from datetime import datetime, timezone

from app.core.intelligence.session.manager import SessionManager
from app.core.intelligence.session.models import SessionData


class TestSessionManager:
    """Test Redis session management for v2."""

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
            assert session.active_agent is None
            assert session.collected_data == {}
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
            active_agent="scheduling",
        )
        mock_redis.get = AsyncMock(return_value=existing.to_json())

        with patch(
            "app.core.intelligence.session.manager.get_redis",
            return_value=mock_redis,
        ):
            session = await manager.get("clinic-456", "sess-123")

            assert session is not None
            assert session.session_id == "sess-123"
            assert session.active_agent == "scheduling"

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
    async def test_save_session(self, manager, mock_redis):
        """Test saving session updates Redis."""
        session = SessionData(
            session_id="sess-123",
            clinic_id="clinic-456",
            active_agent="faq",
            collected_data={"patient_name": "John Doe"},
        )

        with patch(
            "app.core.intelligence.session.manager.get_redis",
            return_value=mock_redis,
        ):
            await manager.save(session)
            mock_redis.setex.assert_called_once()

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
    """Test v2 SessionData model."""

    def test_basic_creation(self):
        """Test creating a session with defaults."""
        session = SessionData(
            session_id="test-123",
            clinic_id="clinic-456",
        )

        assert session.session_id == "test-123"
        assert session.clinic_id == "clinic-456"
        assert session.active_agent is None
        assert session.collected_data == {}
        assert session.claude_messages == []
        assert session.router_context == []
        assert session.message_count == 0

    def test_serialization_roundtrip(self):
        """Test JSON serialization/deserialization."""
        session = SessionData(
            session_id="test-123",
            clinic_id="clinic-456",
            active_agent="scheduling",
            collected_data={"provider_name": "Dr. Smith"},
        )

        json_str = session.to_json()
        restored = SessionData.from_json(json_str)

        assert restored.session_id == session.session_id
        assert restored.active_agent == session.active_agent
        assert restored.collected_data == session.collected_data

    def test_store_turn_simple(self):
        """Test storing a simple conversation turn."""
        session = SessionData(
            session_id="test-123",
            clinic_id="clinic-456",
        )

        session.store_turn(
            user_message="Hello",
            assistant_content="Hi, how can I help?",
            text_response="Hi, how can I help?",
        )

        assert session.message_count == 1
        assert len(session.claude_messages) == 2
        assert session.claude_messages[0] == {"role": "user", "content": "Hello"}
        assert session.claude_messages[1] == {"role": "assistant", "content": "Hi, how can I help?"}
        assert len(session.router_context) == 2

    def test_store_turn_with_tool_use(self):
        """Test storing a turn with tool_use blocks."""
        session = SessionData(
            session_id="test-123",
            clinic_id="clinic-456",
        )

        # Simulate a message chain with tool calls
        message_chain = [
            {"role": "assistant", "content": [
                {"type": "text", "text": "Let me check availability."},
                {"type": "tool_use", "id": "tool-1", "name": "find_optimal_slots", "input": {"date": "2024-01-15"}},
            ]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "tool-1", "content": '{"slots": []}'},
            ]},
            {"role": "assistant", "content": "No slots available for that date."},
        ]

        session.store_turn(
            user_message="I need an appointment tomorrow",
            assistant_content=message_chain,
            text_response="No slots available for that date.",
        )

        assert session.message_count == 1
        # User message + 3 messages from chain
        assert len(session.claude_messages) == 4
        # Router context only has text
        assert len(session.router_context) == 2

    def test_merge_entities(self):
        """Test merging entities into collected data."""
        session = SessionData(
            session_id="test-123",
            clinic_id="clinic-456",
            collected_data={"patient_name": "John Doe"},
        )

        session.merge_entities({
            "provider_name": "Dr. Smith",
            "date": "2024-01-15",
            "patient_name": None,  # Should not overwrite
        })

        assert session.collected_data["patient_name"] == "John Doe"
        assert session.collected_data["provider_name"] == "Dr. Smith"
        assert session.collected_data["date"] == "2024-01-15"

    def test_get_router_context_str(self):
        """Test getting router context string."""
        session = SessionData(
            session_id="test-123",
            clinic_id="clinic-456",
            active_agent="scheduling",
            collected_data={"provider_name": "Dr. Smith"},
        )

        session.store_turn(
            user_message="I need an appointment with Dr. Smith",
            assistant_content="Sure, when would you like to come in?",
            text_response="Sure, when would you like to come in?",
        )

        context = session.get_router_context_str()

        assert "Patient: I need an appointment" in context
        assert "Receptionist: Sure" in context
        assert "provider_name: Dr. Smith" in context
        assert "scheduling" in context

    def test_get_context_for_llm(self):
        """Test LLM context generation for v2."""
        session = SessionData(
            session_id="test-123",
            clinic_id="clinic-456",
            active_agent="scheduling",
            collected_data={"provider_name": "Dr. Smith", "date": "2024-01-15"},
            booking_id="booking-789",
        )

        context = session.get_context_for_llm()

        assert context["active_agent"] == "scheduling"
        assert context["collected"]["provider_name"] == "Dr. Smith"
        assert context["booking_id"] == "booking-789"

    def test_max_history_limit(self):
        """Test history is limited to max messages."""
        session = SessionData(
            session_id="test-123",
            clinic_id="clinic-456",
            max_messages=4,  # Small limit for testing
            max_router_context=2,
        )

        for i in range(5):
            session.store_turn(
                user_message=f"Message {i}",
                assistant_content=f"Response {i}",
                text_response=f"Response {i}",
            )

        # Should be trimmed to max
        assert len(session.claude_messages) == 4
        assert len(session.router_context) == 2
        assert session.message_count == 5

    def test_serialization_with_tool_blocks(self):
        """Test JSON serialization preserves tool_use blocks."""
        session = SessionData(
            session_id="test-123",
            clinic_id="clinic-456",
        )

        session.claude_messages = [
            {"role": "user", "content": "Book an appointment"},
            {"role": "assistant", "content": [
                {"type": "text", "text": "Let me check."},
                {"type": "tool_use", "id": "t1", "name": "find_slots", "input": {"date": "2024-01-15"}},
            ]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "t1", "content": '{"slots": []}'},
            ]},
        ]

        json_str = session.to_json()
        restored = SessionData.from_json(json_str)

        assert len(restored.claude_messages) == 3
        assert restored.claude_messages[1]["content"][1]["name"] == "find_slots"
        assert restored.claude_messages[2]["content"][0]["tool_use_id"] == "t1"

    def test_empty_router_context_str(self):
        """Test router context string for new session."""
        session = SessionData(
            session_id="test-123",
            clinic_id="clinic-456",
        )

        context = session.get_router_context_str()

        assert "New conversation" in context
