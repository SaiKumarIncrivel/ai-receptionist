"""Slot extraction module."""

from .types import ExtractedSlots, AppointmentType
from .extractor import (
    SlotExtractor,
    get_slot_extractor,
    extract_slots,
)

__all__ = [
    # Types
    "ExtractedSlots",
    "AppointmentType",
    # Extractor
    "SlotExtractor",
    "get_slot_extractor",
    "extract_slots",
]
