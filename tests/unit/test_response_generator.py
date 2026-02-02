"""Tests for Response Generator."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from dataclasses import dataclass

from app.core.scheduling.response import (
    ResponseGenerator,
    ResponseContext,
)
from app.core.scheduling.calendar_client import TimeSlot
from app.core.intelligence.session.state import BookingState


@dataclass
class MockClaudeResponse:
    """Mock Claude response."""
    content: str
    model: str = "claude-3-5-haiku-20241022"


class TestResponseGenerator:
    """Test ResponseGenerator."""

    @pytest.fixture
    def mock_claude_client(self):
        """Create mock Claude client."""
        return AsyncMock()

    @pytest.fixture
    def generator(self, mock_claude_client):
        """Create generator with mock client."""
        return ResponseGenerator(claude_client=mock_claude_client)

    # === Template Response Tests ===

    def test_greeting(self, generator):
        """Test greeting generation."""
        response = generator.greeting()
        assert "Hello" in response
        assert "appointment" in response.lower()

    def test_greeting_with_clinic_name(self, generator):
        """Test greeting with clinic name."""
        response = generator.greeting("Main Street Clinic")
        assert "Main Street Clinic" in response

    def test_goodbye(self, generator):
        """Test goodbye generation."""
        response = generator.goodbye()
        assert "goodbye" in response.lower() or "take care" in response.lower()

    def test_goodbye_with_name(self, generator):
        """Test goodbye with patient name."""
        response = generator.goodbye("John")
        assert "John" in response

    def test_handoff(self, generator):
        """Test handoff generation."""
        response = generator.handoff()
        assert "staff" in response.lower() or "connect" in response.lower()

    def test_handoff_with_reason(self, generator):
        """Test handoff with reason."""
        response = generator.handoff("billing question")
        assert "billing question" in response

    def test_out_of_scope(self, generator):
        """Test out of scope response."""
        response = generator.out_of_scope()
        assert "scheduling" in response.lower() or "appointment" in response.lower()

    def test_clarification(self, generator):
        """Test clarification request."""
        response = generator.clarification("the date you mentioned")
        assert "the date you mentioned" in response

    # === Slot Formatting Tests ===

    def test_format_slots_empty(self, generator):
        """Test formatting empty slots."""
        response = generator.format_slots([])
        assert "no available" in response.lower() or "sorry" in response.lower()

    def test_format_slots(self, generator):
        """Test formatting slots."""
        slots = [
            TimeSlot(
                slot_id="1",
                provider_id="doc-1",
                provider_name="Dr. Smith",
                start_time="2024-01-15T09:00:00",
                end_time="2024-01-15T09:30:00",
            ),
            TimeSlot(
                slot_id="2",
                provider_id="doc-1",
                provider_name="Dr. Smith",
                start_time="2024-01-15T10:00:00",
                end_time="2024-01-15T10:30:00",
            ),
        ]

        response = generator.format_slots(slots)

        assert "Dr. Smith" in response
        assert "09:00" in response
        assert "10:00" in response
        assert "1." in response
        assert "2." in response

    def test_format_slots_with_intro(self, generator):
        """Test formatting slots with custom intro."""
        slots = [
            TimeSlot(
                slot_id="1",
                provider_id="doc-1",
                provider_name="Dr. Smith",
                start_time="09:00",
                end_time="09:30",
            ),
        ]

        response = generator.format_slots(slots, intro="Here's what's available:")

        assert "Here's what's available:" in response

    # === Booking Confirmation Tests ===

    def test_confirm_booking(self, generator):
        """Test booking confirmation request."""
        response = generator.confirm_booking(
            provider_name="Dr. Smith",
            date="January 15, 2024",
            time="10:00 AM",
            patient_name="John Doe",
            reason="Checkup",
        )

        assert "Dr. Smith" in response
        assert "January 15" in response
        assert "10:00" in response
        assert "John Doe" in response
        assert "Checkup" in response
        assert "book" in response.lower()

    def test_booking_confirmed(self, generator):
        """Test booking confirmed response."""
        response = generator.booking_confirmed(
            booking_id="BK-12345",
            provider_name="Dr. Smith",
            date="January 15, 2024",
            time="10:00 AM",
            patient_name="John",
        )

        assert "confirmed" in response.lower()
        assert "BK-12345" in response
        assert "Dr. Smith" in response
        assert "John" in response

    def test_booking_failed(self, generator):
        """Test booking failed response."""
        response = generator.booking_failed(
            reason="The slot is no longer available.",
            suggestions=["Try a different time", "Choose another doctor"],
        )

        assert "sorry" in response.lower()
        assert "Try a different time" in response

    def test_booking_failed_no_suggestions(self, generator):
        """Test booking failed without suggestions."""
        response = generator.booking_failed()

        assert "sorry" in response.lower()
        assert "different" in response.lower()

    # === Template Selection Tests ===

    @pytest.mark.asyncio
    async def test_uses_template_for_collect_provider(self, generator, mock_claude_client):
        """Test template is used for collect provider state."""
        context = ResponseContext(
            state=BookingState.COLLECT_PROVIDER,
            user_message="",
            collected_data={},
        )

        response = await generator.generate(context)

        # Should use template, not call LLM
        mock_claude_client.generate.assert_not_called()
        assert "doctor" in response.lower() or "which" in response.lower()

    @pytest.mark.asyncio
    async def test_uses_template_for_collect_date(self, generator, mock_claude_client):
        """Test template for collect date state."""
        context = ResponseContext(
            state=BookingState.COLLECT_DATE,
            user_message="",
            collected_data={"provider_name": "Dr. Smith"},
        )

        response = await generator.generate(context)

        mock_claude_client.generate.assert_not_called()
        assert "Dr. Smith" in response or "when" in response.lower()

    @pytest.mark.asyncio
    async def test_uses_template_for_collect_patient_info(self, generator, mock_claude_client):
        """Test template for collect patient info."""
        context = ResponseContext(
            state=BookingState.COLLECT_PATIENT_INFO,
            user_message="",
            collected_data={},
        )

        response = await generator.generate(context)

        mock_claude_client.generate.assert_not_called()
        assert "name" in response.lower()

    @pytest.mark.asyncio
    async def test_includes_patient_name_prefix(self, generator, mock_claude_client):
        """Test patient name is used as prefix."""
        context = ResponseContext(
            state=BookingState.COLLECT_PATIENT_INFO,
            user_message="",
            collected_data={"patient_name": "Sarah"},
        )

        response = await generator.generate(context)

        assert "Sarah" in response

    @pytest.mark.asyncio
    async def test_error_response(self, generator, mock_claude_client):
        """Test error context generates apology."""
        context = ResponseContext(
            state=BookingState.IDLE,
            user_message="test",
            collected_data={},
            error_message="something went wrong",
        )

        response = await generator.generate(context)

        mock_claude_client.generate.assert_not_called()
        assert "apologize" in response.lower() or "sorry" in response.lower()

    # === LLM Fallback Tests ===

    @pytest.mark.asyncio
    async def test_uses_llm_for_idle_state(self, generator, mock_claude_client):
        """Test LLM is used for idle state responses."""
        mock_claude_client.generate.return_value = MockClaudeResponse(
            content="How can I help you schedule an appointment today?"
        )

        context = ResponseContext(
            state=BookingState.IDLE,
            user_message="Hi there!",
            collected_data={},
        )

        response = await generator.generate(context)

        mock_claude_client.generate.assert_called_once()
        assert "appointment" in response.lower()

    @pytest.mark.asyncio
    async def test_fallback_on_llm_error(self, generator, mock_claude_client):
        """Test fallback when LLM fails."""
        mock_claude_client.generate.side_effect = Exception("API error")

        context = ResponseContext(
            state=BookingState.IDLE,
            user_message="Hi!",
            collected_data={},
        )

        response = await generator.generate(context)

        # Should use fallback response
        assert "Hello" in response or "help" in response.lower()


class TestResponseContext:
    """Test ResponseContext dataclass."""

    def test_create_context(self):
        """Test creating context."""
        context = ResponseContext(
            state=BookingState.COLLECT_DATE,
            user_message="Next Tuesday",
            collected_data={"provider_name": "Dr. Smith"},
            action="collect",
        )

        assert context.state == BookingState.COLLECT_DATE
        assert context.user_message == "Next Tuesday"
        assert context.collected_data["provider_name"] == "Dr. Smith"
        assert context.action == "collect"

    def test_context_with_slots(self):
        """Test context with available slots."""
        slots = [
            TimeSlot(
                slot_id="1",
                provider_id="doc-1",
                provider_name="Dr. Smith",
                start_time="09:00",
                end_time="09:30",
            ),
        ]

        context = ResponseContext(
            state=BookingState.SHOWING_SLOTS,
            user_message="",
            collected_data={},
            available_slots=slots,
        )

        assert context.available_slots is not None
        assert len(context.available_slots) == 1
