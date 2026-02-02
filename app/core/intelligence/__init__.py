"""
Intelligence Layer Module

Provides intent classification, slot extraction, session management,
and context building for the AI receptionist.

Usage:
    from app.core.intelligence import (
        classify_intent,
        extract_slots,
        get_session_manager,
        build_context,
    )

    # Classify intent
    result = await classify_intent("I need to schedule an appointment")
    print(result.intent)  # Intent.SCHEDULING

    # Extract slots
    slots = await extract_slots("Tuesday at 2pm with Dr. Smith")
    print(slots.provider_name)  # "Smith"
    print(slots.date_raw)  # "Tuesday"

    # Session management
    manager = await get_session_manager()
    session = await manager.create(clinic_id="123")
"""

# Intent Classification
from app.core.intelligence.intent.types import Intent, IntentResult, ConfirmationType
from app.core.intelligence.intent.classifier import (
    IntentClassifier,
    get_intent_classifier,
    classify_intent,
)

# Slot Extraction
from app.core.intelligence.slots.types import ExtractedSlots, AppointmentType
from app.core.intelligence.slots.extractor import (
    SlotExtractor,
    get_slot_extractor,
    extract_slots,
)

# Session Management
from app.core.intelligence.session.state import (
    BookingState,
    can_transition,
    get_valid_transitions,
    is_terminal_state,
    is_collecting_state,
)
from app.core.intelligence.session.models import SessionData, ConversationTurn
from app.core.intelligence.session.manager import SessionManager, get_session_manager

# Context Building
from app.core.intelligence.context.builder import (
    ContextBuilder,
    get_context_builder,
    build_context,
    build_system_prompt,
)

__all__ = [
    # Intent
    "Intent",
    "IntentResult",
    "ConfirmationType",
    "IntentClassifier",
    "get_intent_classifier",
    "classify_intent",
    # Slots
    "ExtractedSlots",
    "AppointmentType",
    "SlotExtractor",
    "get_slot_extractor",
    "extract_slots",
    # Session State
    "BookingState",
    "can_transition",
    "get_valid_transitions",
    "is_terminal_state",
    "is_collecting_state",
    # Session Data
    "SessionData",
    "ConversationTurn",
    "SessionManager",
    "get_session_manager",
    # Context
    "ContextBuilder",
    "get_context_builder",
    "build_context",
    "build_system_prompt",
]
