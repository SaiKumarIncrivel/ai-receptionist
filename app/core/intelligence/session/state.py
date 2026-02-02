"""Booking state machine."""

from enum import Enum
from typing import Set


class BookingState(str, Enum):
    """States in the appointment booking flow."""

    # Initial
    IDLE = "idle"

    # Information gathering
    COLLECT_PROVIDER = "collect_provider"
    COLLECT_DATE = "collect_date"
    COLLECT_TIME = "collect_time"
    COLLECT_PATIENT_INFO = "collect_patient_info"
    COLLECT_REASON = "collect_reason"

    # Availability
    SEARCHING = "searching"
    SHOWING_SLOTS = "showing_slots"

    # Confirmation
    CONFIRM_BOOKING = "confirm_booking"

    # Terminal states
    BOOKED = "booked"
    CANCELLED = "cancelled"
    HANDED_OFF = "handed_off"
    COMPLETED = "completed"
    ERROR = "error"


# Valid state transitions
VALID_TRANSITIONS: dict[BookingState, Set[BookingState]] = {
    BookingState.IDLE: {
        BookingState.COLLECT_PROVIDER,
        BookingState.COLLECT_DATE,
        BookingState.COLLECT_REASON,
        BookingState.SEARCHING,
        BookingState.HANDED_OFF,
    },
    BookingState.COLLECT_PROVIDER: {
        BookingState.COLLECT_DATE,
        BookingState.COLLECT_TIME,
        BookingState.COLLECT_REASON,
        BookingState.SEARCHING,
        BookingState.IDLE,
        BookingState.HANDED_OFF,
    },
    BookingState.COLLECT_DATE: {
        BookingState.COLLECT_TIME,
        BookingState.COLLECT_PROVIDER,
        BookingState.COLLECT_REASON,
        BookingState.SEARCHING,
        BookingState.IDLE,
        BookingState.HANDED_OFF,
    },
    BookingState.COLLECT_TIME: {
        BookingState.SEARCHING,
        BookingState.COLLECT_DATE,
        BookingState.COLLECT_PROVIDER,
        BookingState.IDLE,
        BookingState.HANDED_OFF,
    },
    BookingState.COLLECT_PATIENT_INFO: {
        BookingState.SEARCHING,
        BookingState.SHOWING_SLOTS,
        BookingState.CONFIRM_BOOKING,
        BookingState.IDLE,
        BookingState.HANDED_OFF,
    },
    BookingState.COLLECT_REASON: {
        BookingState.COLLECT_DATE,
        BookingState.COLLECT_PROVIDER,
        BookingState.SEARCHING,
        BookingState.IDLE,
        BookingState.HANDED_OFF,
    },
    BookingState.SEARCHING: {
        BookingState.SHOWING_SLOTS,
        BookingState.COLLECT_DATE,
        BookingState.COLLECT_PROVIDER,
        BookingState.ERROR,
        BookingState.HANDED_OFF,
    },
    BookingState.SHOWING_SLOTS: {
        BookingState.CONFIRM_BOOKING,
        BookingState.SEARCHING,
        BookingState.COLLECT_DATE,
        BookingState.IDLE,
        BookingState.HANDED_OFF,
    },
    BookingState.CONFIRM_BOOKING: {
        BookingState.BOOKED,
        BookingState.SHOWING_SLOTS,
        BookingState.COLLECT_DATE,
        BookingState.IDLE,
        BookingState.HANDED_OFF,
        BookingState.CANCELLED,
    },
    BookingState.BOOKED: {
        BookingState.COMPLETED,
        BookingState.IDLE,  # User wants to book another
    },
    BookingState.CANCELLED: {
        BookingState.COMPLETED,
        BookingState.IDLE,  # User starts over
    },
    BookingState.HANDED_OFF: {
        BookingState.COMPLETED,
    },
    BookingState.COMPLETED: set(),  # Terminal state
    BookingState.ERROR: {
        BookingState.IDLE,
        BookingState.HANDED_OFF,
    },
}


def can_transition(from_state: BookingState, to_state: BookingState) -> bool:
    """Check if a state transition is valid."""
    return to_state in VALID_TRANSITIONS.get(from_state, set())


def get_valid_transitions(state: BookingState) -> Set[BookingState]:
    """Get all valid transitions from a state."""
    return VALID_TRANSITIONS.get(state, set())


def is_terminal_state(state: BookingState) -> bool:
    """Check if state is terminal (no further transitions)."""
    return state in {
        BookingState.COMPLETED,
    }


def is_collecting_state(state: BookingState) -> bool:
    """Check if state is a data collection state."""
    return state in {
        BookingState.COLLECT_PROVIDER,
        BookingState.COLLECT_DATE,
        BookingState.COLLECT_TIME,
        BookingState.COLLECT_PATIENT_INFO,
        BookingState.COLLECT_REASON,
    }
