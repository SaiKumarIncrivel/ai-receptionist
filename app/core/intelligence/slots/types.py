"""Slot types for entity extraction."""

from dataclasses import dataclass
from datetime import date, time
from enum import Enum
from typing import Optional


class AppointmentType(str, Enum):
    """Types of appointments."""

    CHECKUP = "checkup"
    CONSULTATION = "consultation"
    FOLLOW_UP = "follow_up"
    URGENT = "urgent"
    NEW_PATIENT = "new_patient"
    SPECIALIST = "specialist"
    SICK_VISIT = "sick_visit"
    PHYSICAL = "physical"
    OTHER = "other"


@dataclass
class ExtractedSlots:
    """Slots extracted from a message by LLM."""

    # Provider
    provider_name: Optional[str] = None

    # Date/time
    date: Optional[date] = None          # Parsed date
    time: Optional[time] = None          # Parsed time
    date_raw: Optional[str] = None       # "next Tuesday", "January 15"
    time_raw: Optional[str] = None       # "2pm", "morning"
    is_flexible: bool = False            # "around 2pm", "morning works"

    # Appointment
    appointment_type: Optional[AppointmentType] = None
    reason: Optional[str] = None         # "back pain", "annual physical"

    # Patient (if mentioned)
    patient_name: Optional[str] = None
    patient_phone: Optional[str] = None
    patient_dob: Optional[date] = None

    # Metadata
    raw_response: str = ""
    processing_time_ms: float = 0.0

    def has_any(self) -> bool:
        """Check if any slots were extracted."""
        return any([
            self.provider_name,
            self.date,
            self.time,
            self.date_raw,
            self.time_raw,
            self.appointment_type,
            self.reason,
            self.patient_name,
            self.patient_phone,
        ])

    @property
    def has_datetime(self) -> bool:
        """Check if date or time was extracted."""
        return self.date is not None or self.time is not None or self.date_raw is not None

    @property
    def has_patient_info(self) -> bool:
        """Check if patient information was extracted."""
        return self.patient_name is not None or self.patient_phone is not None

    def merge(self, other: "ExtractedSlots") -> "ExtractedSlots":
        """Merge with another ExtractedSlots, preferring non-None values from other."""
        return ExtractedSlots(
            provider_name=other.provider_name or self.provider_name,
            date=other.date or self.date,
            time=other.time or self.time,
            date_raw=other.date_raw or self.date_raw,
            time_raw=other.time_raw or self.time_raw,
            is_flexible=other.is_flexible or self.is_flexible,
            appointment_type=other.appointment_type or self.appointment_type,
            reason=other.reason or self.reason,
            patient_name=other.patient_name or self.patient_name,
            patient_phone=other.patient_phone or self.patient_phone,
            patient_dob=other.patient_dob or self.patient_dob,
        )

    def to_dict(self) -> dict:
        """Convert to dict, excluding None values."""
        result = {}
        if self.provider_name:
            result["provider_name"] = self.provider_name
        if self.date:
            result["date"] = self.date.isoformat()
        if self.time:
            result["time"] = self.time.isoformat()
        if self.date_raw:
            result["date_raw"] = self.date_raw
        if self.time_raw:
            result["time_raw"] = self.time_raw
        if self.is_flexible:
            result["is_flexible"] = self.is_flexible
        if self.appointment_type:
            result["appointment_type"] = self.appointment_type.value
        if self.reason:
            result["reason"] = self.reason
        if self.patient_name:
            result["patient_name"] = self.patient_name
        if self.patient_phone:
            result["patient_phone"] = self.patient_phone
        if self.patient_dob:
            result["patient_dob"] = self.patient_dob.isoformat()
        return result
