"""
Database Models

SQLAlchemy ORM models for the AI Receptionist multi-tenant medical scheduling system.
"""

import uuid
from datetime import datetime
from enum import Enum
from typing import Optional, List

from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Index, Integer, String, Text,
    Enum as SQLEnum, text
)
from sqlalchemy.dialects.postgresql import UUID, JSON
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    """Base class for all database models."""
    pass


class TimestampMixin:
    """Mixin that adds created_at and updated_at timestamp columns."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False
    )


class SoftDeleteMixin:
    """Mixin that adds soft delete functionality."""

    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime,
        nullable=True
    )


class ClinicStatus(str, Enum):
    """Clinic status enumeration."""
    ACTIVE = "active"
    SUSPENDED = "suspended"
    INACTIVE = "inactive"


class ProviderStatus(str, Enum):
    """Provider status enumeration."""
    ACTIVE = "active"
    INACTIVE = "inactive"
    ON_LEAVE = "on_leave"


class AppointmentStatus(str, Enum):
    """Appointment status enumeration."""
    SCHEDULED = "scheduled"
    CONFIRMED = "confirmed"
    CHECKED_IN = "checked_in"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    NO_SHOW = "no_show"


class AuditAction(str, Enum):
    """Audit log action enumeration."""
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    LOGIN = "login"
    LOGOUT = "logout"
    SAFETY_TRIGGER = "safety_trigger"
    EMERGENCY = "emergency"
    PHI_DETECTED = "phi_detected"
    APPOINTMENT_BOOKED = "appointment_booked"
    APPOINTMENT_CANCELLED = "appointment_cancelled"


class Clinic(Base, TimestampMixin, SoftDeleteMixin):
    """
    Clinic model (Tenant).

    Each clinic is a separate tenant in the multi-tenant system.
    Clinics have their own providers, patients, and appointments.
    """

    __tablename__ = "clinics"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    timezone: Mapped[str] = mapped_column(String(50), default="America/New_York")
    api_key_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    ehr_provider: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    ehr_credentials: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    business_hours: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[ClinicStatus] = mapped_column(
        SQLEnum(ClinicStatus),
        default=ClinicStatus.ACTIVE
    )
    default_reminder_hours: Mapped[int] = mapped_column(Integer, default=24)
    rate_limit_tier: Mapped[str] = mapped_column(
        String(20),
        default="standard",
        doc="Rate limit tier: free, standard, professional, enterprise, unlimited"
    )
    rate_limit_rpm: Mapped[int] = mapped_column(
        Integer,
        default=60,
        doc="Requests per minute limit for this clinic"
    )

    # Relationships
    providers: Mapped[List["Provider"]] = relationship(
        "Provider",
        back_populates="clinic"
    )
    patients: Mapped[List["Patient"]] = relationship(
        "Patient",
        back_populates="clinic"
    )
    appointments: Mapped[List["Appointment"]] = relationship(
        "Appointment",
        back_populates="clinic"
    )
    sessions: Mapped[List["Session"]] = relationship(
        "Session",
        back_populates="clinic"
    )
    audit_logs: Mapped[List["AuditLog"]] = relationship(
        "AuditLog",
        back_populates="clinic"
    )

    def __repr__(self) -> str:
        return f"<Clinic(id={self.id}, name='{self.name}', status={self.status.value})>"


class Provider(Base, TimestampMixin, SoftDeleteMixin):
    """
    Provider model (Doctors, Nurses, etc.).

    Providers belong to a clinic and can have appointments scheduled with them.
    """

    __tablename__ = "providers"
    __table_args__ = (
        Index("idx_provider_clinic", "clinic_id"),
        Index("idx_provider_external", "clinic_id", "external_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )
    clinic_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("clinics.id", ondelete="CASCADE"),
        nullable=False
    )
    external_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    specialty: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    status: Mapped[ProviderStatus] = mapped_column(
        SQLEnum(ProviderStatus),
        default=ProviderStatus.ACTIVE
    )
    schedule: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    default_appointment_duration: Mapped[int] = mapped_column(Integer, default=30)
    accepting_new_patients: Mapped[bool] = mapped_column(Boolean, default=True)
    npi: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    bio: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    languages: Mapped[list] = mapped_column(JSON, default=list)

    # Relationships
    clinic: Mapped["Clinic"] = relationship("Clinic", back_populates="providers")
    appointments: Mapped[List["Appointment"]] = relationship(
        "Appointment",
        back_populates="provider"
    )

    @property
    def full_name(self) -> str:
        """Return full name with title if exists."""
        if self.title:
            return f"{self.title} {self.first_name} {self.last_name}"
        return f"{self.first_name} {self.last_name}"

    def __repr__(self) -> str:
        return f"<Provider(id={self.id}, name='{self.full_name}', specialty='{self.specialty}')>"


class Patient(Base, TimestampMixin, SoftDeleteMixin):
    """
    Patient model.

    Patients belong to a clinic and can have appointments scheduled.
    """

    __tablename__ = "patients"
    __table_args__ = (
        Index("idx_patient_clinic", "clinic_id"),
        Index("idx_patient_phone", "clinic_id", "phone"),
        Index("idx_patient_email", "clinic_id", "email"),
        Index("idx_patient_external", "clinic_id", "external_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )
    clinic_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("clinics.id", ondelete="CASCADE"),
        nullable=False
    )
    external_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    date_of_birth: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    gender: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    street_address: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    city: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    state: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    zip_code: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    phone_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    preferred_language: Mapped[str] = mapped_column(String(10), default="en")
    sms_opt_in: Mapped[bool] = mapped_column(Boolean, default=True)
    email_opt_in: Mapped[bool] = mapped_column(Boolean, default=True)

    # Relationships
    clinic: Mapped["Clinic"] = relationship("Clinic", back_populates="patients")
    appointments: Mapped[List["Appointment"]] = relationship(
        "Appointment",
        back_populates="patient"
    )

    @property
    def full_name(self) -> str:
        """Return full name."""
        return f"{self.first_name} {self.last_name}"

    def __repr__(self) -> str:
        return f"<Patient(id={self.id}, name='{self.full_name}', phone='{self.phone}')>"


class Appointment(Base, TimestampMixin, SoftDeleteMixin):
    """
    Appointment model.

    Represents scheduled appointments between patients and providers.
    """

    __tablename__ = "appointments"
    __table_args__ = (
        Index("idx_appointment_clinic", "clinic_id"),
        Index("idx_appointment_provider_date", "provider_id", "scheduled_start"),
        Index("idx_appointment_patient", "patient_id"),
        Index("idx_appointment_status", "clinic_id", "status"),
        Index("idx_appointment_external", "clinic_id", "external_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )
    clinic_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("clinics.id", ondelete="CASCADE"),
        nullable=False
    )
    provider_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("providers.id", ondelete="CASCADE"),
        nullable=False
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("patients.id", ondelete="CASCADE"),
        nullable=False
    )
    external_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    scheduled_start: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False
    )
    scheduled_end: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False
    )
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    visit_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[AppointmentStatus] = mapped_column(
        SQLEnum(AppointmentStatus),
        default=AppointmentStatus.SCHEDULED
    )
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime,
        nullable=True
    )
    reminder_sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime,
        nullable=True
    )
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime,
        nullable=True
    )
    cancellation_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    cancelled_by: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    checked_in_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime,
        nullable=True
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime,
        nullable=True
    )
    is_new_patient_visit: Mapped[bool] = mapped_column(Boolean, default=False)
    special_instructions: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    rescheduled_from_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("appointments.id", ondelete="SET NULL"),
        nullable=True
    )
    booked_via: Mapped[str] = mapped_column(String(50), default="ai_receptionist")
    reminder_count: Mapped[int] = mapped_column(Integer, default=0)

    # Relationships
    clinic: Mapped["Clinic"] = relationship("Clinic", back_populates="appointments")
    provider: Mapped["Provider"] = relationship("Provider", back_populates="appointments")
    patient: Mapped["Patient"] = relationship("Patient", back_populates="appointments")
    rescheduled_from: Mapped[Optional["Appointment"]] = relationship(
        "Appointment",
        remote_side=[id],
        uselist=False
    )

    def __repr__(self) -> str:
        return (
            f"<Appointment(id={self.id}, patient_id={self.patient_id}, "
            f"provider_id={self.provider_id}, start={self.scheduled_start}, "
            f"status={self.status.value})>"
        )


class Session(Base, TimestampMixin):
    """
    Session model.

    Tracks conversation state for chat sessions.
    Stored in Redis for fast access, with PostgreSQL as backup.
    """

    __tablename__ = "sessions"
    __table_args__ = (
        Index("idx_session_clinic", "clinic_id"),
        Index("idx_session_expires", "expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )
    clinic_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("clinics.id", ondelete="CASCADE"),
        nullable=False
    )
    channel: Mapped[str] = mapped_column(String(50), default="web")
    channel_user_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    patient_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("patients.id", ondelete="SET NULL"),
        nullable=True
    )
    state: Mapped[dict] = mapped_column(JSON, default=dict)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False
    )
    message_count: Mapped[int] = mapped_column(Integer, default=0)

    # Relationships
    clinic: Mapped["Clinic"] = relationship("Clinic", back_populates="sessions")

    def __repr__(self) -> str:
        return (
            f"<Session(id={self.id}, clinic_id={self.clinic_id}, "
            f"channel='{self.channel}', expires_at={self.expires_at})>"
        )


class AuditLog(Base):
    """
    Audit Log model.

    Immutable audit trail for HIPAA compliance and security monitoring.
    Records all critical actions in the system.
    """

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("idx_audit_clinic_time", "clinic_id", "timestamp"),
        Index("idx_audit_action", "action"),
        Index("idx_audit_resource", "resource_type", "resource_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )
    clinic_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("clinics.id", ondelete="CASCADE"),
        nullable=False
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False
    )
    action: Mapped[AuditAction] = mapped_column(
        SQLEnum(AuditAction),
        nullable=False
    )
    resource_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    resource_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    details: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    session_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        nullable=True
    )
    ip_address: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    severity: Mapped[str] = mapped_column(String(20), default="info")

    # Relationships
    clinic: Mapped["Clinic"] = relationship("Clinic", back_populates="audit_logs")

    def __repr__(self) -> str:
        return (
            f"<AuditLog(id={self.id}, action={self.action.value}, "
            f"timestamp={self.timestamp}, severity='{self.severity}')>"
        )
