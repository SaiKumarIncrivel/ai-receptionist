"""Tests for Conversation Flow Manager."""

import pytest
from datetime import date, time

from app.core.scheduling.flow import (
    ConversationFlow,
    FlowAction,
)
from app.core.intelligence.intent.types import Intent, IntentResult, ConfirmationType
from app.core.intelligence.slots.types import ExtractedSlots
from app.core.intelligence.session.models import SessionData
from app.core.intelligence.session.state import BookingState


class TestConversationFlow:
    """Test ConversationFlow state machine."""

    @pytest.fixture
    def flow(self):
        """Create flow manager."""
        return ConversationFlow()

    @pytest.fixture
    def session(self):
        """Create test session."""
        return SessionData(
            session_id="test-session",
            clinic_id="clinic-123",
            state=BookingState.IDLE,
        )

    # === Intent Handling Tests ===

    def test_handoff_intent(self, flow, session):
        """Test handoff intent always transitions to HANDED_OFF."""
        intent = IntentResult(intent=Intent.HANDOFF, confidence=0.95)
        slots = ExtractedSlots()

        action = flow.process(session, intent, slots)

        assert action.next_state == BookingState.HANDED_OFF
        assert action.action_type == "handoff"

    def test_goodbye_intent(self, flow, session):
        """Test goodbye intent resets to IDLE."""
        session.state = BookingState.COLLECT_DATE
        intent = IntentResult(intent=Intent.GOODBYE, confidence=0.95)
        slots = ExtractedSlots()

        action = flow.process(session, intent, slots)

        assert action.next_state == BookingState.IDLE
        assert action.message == "goodbye"

    def test_out_of_scope_intent(self, flow, session):
        """Test out of scope stays in current state."""
        session.state = BookingState.COLLECT_DATE
        intent = IntentResult(intent=Intent.OUT_OF_SCOPE, confidence=0.95)
        slots = ExtractedSlots()

        action = flow.process(session, intent, slots)

        assert action.next_state == BookingState.COLLECT_DATE
        assert action.message == "out_of_scope"

    def test_greeting_in_idle(self, flow, session):
        """Test greeting in idle state."""
        intent = IntentResult(intent=Intent.GREETING, confidence=0.95)
        slots = ExtractedSlots()

        action = flow.process(session, intent, slots)

        assert action.next_state == BookingState.IDLE
        assert action.message == "greeting"

    # === Scheduling Flow Tests ===

    def test_scheduling_intent_starts_collection(self, flow, session):
        """Test scheduling intent starts collection flow."""
        intent = IntentResult(intent=Intent.SCHEDULING, confidence=0.95)
        slots = ExtractedSlots()

        action = flow.process(session, intent, slots)

        assert action.action_type == "collect"
        assert action.prompt_for == "provider_name"
        assert action.next_state == BookingState.COLLECT_PROVIDER

    def test_scheduling_with_provider_goes_to_date(self, flow, session):
        """Test with provider collected, asks for date."""
        intent = IntentResult(intent=Intent.SCHEDULING, confidence=0.95)
        slots = ExtractedSlots(provider_name="Smith")

        action = flow.process(session, intent, slots)

        assert action.prompt_for == "date"
        assert action.next_state == BookingState.COLLECT_DATE

    def test_scheduling_with_provider_and_date_shows_slots(self, flow, session):
        """Test with provider and date, shows available slots."""
        intent = IntentResult(intent=Intent.PROVIDE_INFO, confidence=0.95)
        slots = ExtractedSlots(
            provider_name="Smith",
            date=date(2024, 1, 15),
        )

        action = flow.process(session, intent, slots)

        assert action.next_state == BookingState.SHOWING_SLOTS
        assert action.should_search_slots is True

    def test_all_required_fields_triggers_confirmation(self, flow, session):
        """Test with all required fields, asks for confirmation."""
        session.collected_data = {
            "provider_name": "Dr. Smith",
            "date": "2024-01-15",
            "time": "10:00",
            "patient_name": "John Doe",
        }

        intent = IntentResult(intent=Intent.PROVIDE_INFO, confidence=0.95)
        slots = ExtractedSlots()

        action = flow.process(session, intent, slots)

        assert action.next_state == BookingState.CONFIRM_BOOKING
        assert action.action_type == "confirm"

    # === Confirmation Handling Tests ===

    def test_confirmation_yes_books(self, flow, session):
        """Test yes confirmation triggers booking."""
        session.state = BookingState.CONFIRM_BOOKING
        session.collected_data = {
            "provider_name": "Dr. Smith",
            "date": "2024-01-15",
            "time": "10:00",
            "patient_name": "John Doe",
        }

        intent = IntentResult(
            intent=Intent.CONFIRMATION,
            confidence=0.95,
            confirmation_type=ConfirmationType.YES,
        )
        slots = ExtractedSlots()

        action = flow.process(session, intent, slots)

        assert action.next_state == BookingState.BOOKED
        assert action.should_book is True

    def test_confirmation_no_restarts_collection(self, flow, session):
        """Test no confirmation allows correction."""
        session.state = BookingState.CONFIRM_BOOKING

        intent = IntentResult(
            intent=Intent.CONFIRMATION,
            confidence=0.95,
            confirmation_type=ConfirmationType.NO,
        )
        slots = ExtractedSlots()

        action = flow.process(session, intent, slots)

        assert action.next_state == BookingState.COLLECT_PROVIDER
        assert action.prompt_for == "correction"

    def test_unclear_confirmation_asks_again(self, flow, session):
        """Test unclear confirmation asks again."""
        session.state = BookingState.CONFIRM_BOOKING

        intent = IntentResult(
            intent=Intent.CONFIRMATION,
            confidence=0.5,
            confirmation_type=ConfirmationType.PARTIAL,
        )
        slots = ExtractedSlots()

        action = flow.process(session, intent, slots)

        assert action.next_state == BookingState.CONFIRM_BOOKING
        assert "yes or no" in action.message.lower()

    # === Cancellation Tests ===

    def test_cancellation_with_booking_id(self, flow, session):
        """Test cancellation with booking ID."""
        session.collected_data = {"booking_id": "booking-123"}

        intent = IntentResult(intent=Intent.CANCELLATION, confidence=0.95)
        slots = ExtractedSlots()

        action = flow.process(session, intent, slots)

        assert action.next_state == BookingState.CANCELLED
        assert action.should_cancel is True

    def test_cancellation_needs_patient_name(self, flow, session):
        """Test cancellation without patient name asks for it."""
        intent = IntentResult(intent=Intent.CANCELLATION, confidence=0.95)
        slots = ExtractedSlots()

        action = flow.process(session, intent, slots)

        assert action.next_state == BookingState.COLLECT_PATIENT_INFO
        assert "cancel" in action.message.lower()

    def test_cancellation_with_patient_name(self, flow, session):
        """Test cancellation with patient name triggers lookup."""
        session.collected_data = {"patient_name": "John Doe"}

        intent = IntentResult(intent=Intent.CANCELLATION, confidence=0.95)
        slots = ExtractedSlots()

        action = flow.process(session, intent, slots)

        assert action.next_state == BookingState.CANCELLED
        assert action.metadata.get("needs_lookup") is True

    # === Reschedule Tests ===

    def test_reschedule_clears_and_restarts(self, flow, session):
        """Test reschedule clears data and starts fresh."""
        session.collected_data = {
            "provider_name": "Dr. Smith",
            "date": "2024-01-15",
        }

        intent = IntentResult(intent=Intent.RESCHEDULE, confidence=0.95)
        slots = ExtractedSlots(provider_name="Dr. Jones")

        action = flow.process(session, intent, slots)

        # Should be in scheduling flow with new provider
        assert session.collected_data.get("provider_name") == "Dr. Jones"
        assert action.action_type == "collect"

    # === Slot Merging Tests ===

    def test_slots_merged_into_collected(self, flow, session):
        """Test extracted slots are merged into collected data."""
        session.collected_data = {"provider_name": "Dr. Smith"}

        intent = IntentResult(intent=Intent.PROVIDE_INFO, confidence=0.95)
        slots = ExtractedSlots(
            date=date(2024, 1, 15),
            time=time(10, 0),
        )

        flow.process(session, intent, slots)

        # Note: to_dict() serializes dates/times to strings
        assert session.collected_data["date"] == "2024-01-15"
        assert session.collected_data["time"] == "10:00:00"
        assert session.collected_data["provider_name"] == "Dr. Smith"

    # === Helper Method Tests ===

    def test_get_missing_fields(self, flow):
        """Test getting missing required fields."""
        collected = {"provider_name": "Dr. Smith"}

        missing = flow._get_missing_fields(collected)

        assert "date" in missing
        assert "time" in missing
        assert "patient_name" in missing
        assert "provider_name" not in missing

    def test_get_missing_fields_with_raw(self, flow):
        """Test raw values count as filled."""
        collected = {
            "provider_name": "Dr. Smith",
            "date_raw": "tomorrow",
            "time_raw": "afternoon",
            "patient_name": "John",
        }

        missing = flow._get_missing_fields(collected)

        assert len(missing) == 0

    def test_can_proceed_to_booking(self, flow):
        """Test checking if ready for booking."""
        incomplete = {"provider_name": "Dr. Smith"}
        complete = {
            "provider_name": "Dr. Smith",
            "date": "2024-01-15",
            "time": "10:00",
            "patient_name": "John",
        }

        assert flow.can_proceed_to_booking(incomplete) is False
        assert flow.can_proceed_to_booking(complete) is True

    def test_get_progress(self, flow):
        """Test progress calculation."""
        collected = {
            "provider_name": "Dr. Smith",
            "date": "2024-01-15",
        }

        progress = flow.get_progress(collected)

        assert progress["total_required"] == 4
        assert progress["completed"] == 2
        assert progress["percent"] == 50
        assert "time" in progress["missing"]
        assert "patient_name" in progress["missing"]

    def test_reset_flow(self, flow, session):
        """Test resetting flow."""
        session.state = BookingState.COLLECT_DATE
        session.collected_data = {"provider_name": "Dr. Smith"}

        action = flow.reset_flow(session)

        assert session.state == BookingState.IDLE
        assert session.collected_data == {}
        assert action.next_state == BookingState.IDLE
        assert action.message == "greeting"


class TestFlowAction:
    """Test FlowAction dataclass."""

    def test_create_action(self):
        """Test creating action."""
        action = FlowAction(
            next_state=BookingState.COLLECT_DATE,
            action_type="collect",
            prompt_for="date",
        )

        assert action.next_state == BookingState.COLLECT_DATE
        assert action.action_type == "collect"
        assert action.prompt_for == "date"
        assert action.should_book is False

    def test_action_with_flags(self):
        """Test action with flags."""
        action = FlowAction(
            next_state=BookingState.BOOKED,
            action_type="book",
            should_book=True,
            should_search_slots=True,
        )

        assert action.should_book is True
        assert action.should_search_slots is True
