"""
Safety module data models.

Pydantic models for PII detection, crisis detection,
content filtering, and safety pipeline results.
"""

from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field
from uuid import UUID


# ==================================
# Enums
# ==================================

class PIIType(str, Enum):
    """Types of PII that can be detected."""
    SSN = "SSN"
    CREDIT_CARD = "CREDIT_CARD"
    EMAIL = "EMAIL"
    PHONE = "PHONE"
    PERSON = "PERSON"
    DATE_OF_BIRTH = "DATE_OF_BIRTH"
    ADDRESS = "ADDRESS"
    MEDICAL_RECORD = "MEDICAL_RECORD"
    INSURANCE_ID = "INSURANCE_ID"
    IP_ADDRESS = "IP_ADDRESS"
    UNKNOWN = "UNKNOWN"


class CrisisType(str, Enum):
    """Types of crisis situations."""
    SUICIDAL_IDEATION = "suicidal_ideation"
    SELF_HARM = "self_harm"
    MEDICAL_EMERGENCY = "medical_emergency"
    DOMESTIC_VIOLENCE = "domestic_violence"
    CHILD_SAFETY = "child_safety"
    THREAT_TO_OTHERS = "threat_to_others"


class CrisisLevel(str, Enum):
    """Severity level of detected crisis."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ContentCategory(str, Enum):
    """Categories for content filtering."""
    ON_TOPIC = "on_topic"
    OFF_TOPIC = "off_topic"
    PROFANITY = "profanity"
    SPAM = "spam"
    THREAT = "threat"
    INAPPROPRIATE = "inappropriate"


class FilterAction(str, Enum):
    """Actions to take on filtered content."""
    ALLOW = "allow"
    WARN = "warn"
    REDIRECT = "redirect"
    BLOCK = "block"


class VerificationMethod(str, Enum):
    """Methods for patient verification."""
    DATE_OF_BIRTH = "dob"
    PHONE_LAST_FOUR = "phone_last_four"
    SECURITY_QUESTION = "security_question"
    EMAIL_CODE = "email_code"
    SMS_CODE = "sms_code"


class VerificationStatus(str, Enum):
    """Status of patient verification."""
    NOT_STARTED = "not_started"
    PENDING = "pending"
    VERIFIED = "verified"
    FAILED = "failed"
    EXPIRED = "expired"


class ConsentType(str, Enum):
    """Types of consent."""
    AI_COMMUNICATION = "ai_communication"
    DATA_PROCESSING = "data_processing"
    APPOINTMENT_REMINDERS = "appointment_reminders"


class AuditEventType(str, Enum):
    """Types of audit events."""
    PII_DETECTED = "pii_detected"
    PII_REDACTED = "pii_redacted"
    CRISIS_DETECTED = "crisis_detected"
    CONTENT_BLOCKED = "content_blocked"
    CONSENT_GIVEN = "consent_given"
    CONSENT_REVOKED = "consent_revoked"
    VERIFICATION_ATTEMPTED = "verification_attempted"
    VERIFICATION_SUCCESS = "verification_success"
    VERIFICATION_FAILED = "verification_failed"
    SAFETY_CHECK_FAILED = "safety_check_failed"


# ==================================
# PII Detection Models
# ==================================

class PIIEntity(BaseModel):
    """A detected PII entity."""
    entity_type: PIIType
    text: str = Field(description="The actual PII text (for internal use only)")
    start: int = Field(description="Start position in text")
    end: int = Field(description="End position in text")
    confidence: float = Field(ge=0.0, le=1.0)

    class Config:
        frozen = True


class PIIDetectionResult(BaseModel):
    """Result of PII detection on text."""
    original_text: str
    redacted_text: str
    entities_found: list[PIIEntity] = Field(default_factory=list)
    pii_detected: bool = False
    detection_time_ms: float = 0.0

    @property
    def entity_types(self) -> list[PIIType]:
        """Get list of PII types found."""
        return [e.entity_type for e in self.entities_found]


# ==================================
# Crisis Detection Models
# ==================================

class CrisisIndicator(BaseModel):
    """A detected crisis indicator."""
    crisis_type: CrisisType
    matched_text: str
    confidence: float = Field(ge=0.0, le=1.0)
    context: str = Field(description="Surrounding text for context")


class CrisisDetectionResult(BaseModel):
    """Result of crisis detection."""
    is_crisis: bool = False
    crisis_level: Optional[CrisisLevel] = None
    indicators: list[CrisisIndicator] = Field(default_factory=list)
    recommended_action: str = ""
    resources: list[str] = Field(default_factory=list)

    @property
    def crisis_types(self) -> list[CrisisType]:
        """Get list of crisis types detected."""
        return [i.crisis_type for i in self.indicators]


# ==================================
# Content Filter Models
# ==================================

class ContentFilterResult(BaseModel):
    """Result of content filtering."""
    category: ContentCategory
    action: FilterAction
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = ""
    suggested_response: Optional[str] = None


# ==================================
# Sanitization Models
# ==================================

class SanitizationResult(BaseModel):
    """Result of input sanitization."""
    original_text: str
    sanitized_text: str
    changes_made: list[str] = Field(default_factory=list)
    prompt_injection_detected: bool = False
    is_safe: bool = True


# ==================================
# Consent Models
# ==================================

class ConsentStatus(BaseModel):
    """Current consent status for a session."""
    has_consented: bool = False
    consent_types: list[ConsentType] = Field(default_factory=list)
    consented_at: Optional[datetime] = None
    consent_version: str = "1.0"
    needs_consent_prompt: bool = True


class ConsentRequest(BaseModel):
    """Request to record consent."""
    session_id: UUID
    clinic_id: UUID
    patient_id: Optional[UUID] = None
    consent_types: list[ConsentType]
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None


# ==================================
# Patient Verification Models
# ==================================

class VerificationRequest(BaseModel):
    """Request to verify patient identity."""
    session_id: UUID
    clinic_id: UUID
    method: VerificationMethod
    provided_value: str = Field(description="Value provided by patient (e.g., DOB)")


class VerificationResult(BaseModel):
    """Result of patient verification."""
    status: VerificationStatus
    patient_id: Optional[UUID] = None
    method: VerificationMethod
    attempts: int = 1
    max_attempts: int = 3
    expires_at: Optional[datetime] = None
    message: str = ""

    @property
    def can_retry(self) -> bool:
        """Check if more verification attempts are allowed."""
        return self.status == VerificationStatus.FAILED and self.attempts < self.max_attempts


# ==================================
# Audit Models
# ==================================

class AuditEntry(BaseModel):
    """An audit log entry."""
    event_type: AuditEventType
    clinic_id: UUID
    session_id: Optional[UUID] = None
    patient_id: Optional[UUID] = None

    details: dict = Field(default_factory=dict)

    ip_address: Optional[str] = None
    user_agent: Optional[str] = None

    timestamp: datetime = Field(default_factory=lambda: datetime.now())

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat(),
            UUID: lambda v: str(v)
        }


# ==================================
# Pipeline Models
# ==================================

class SafetyCheckInput(BaseModel):
    """Input to the safety pipeline."""
    text: str
    session_id: UUID
    clinic_id: UUID
    patient_id: Optional[UUID] = None

    # Context
    is_first_message: bool = False
    conversation_history: list[str] = Field(default_factory=list)

    # Request metadata
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None


class SafetyCheckResult(BaseModel):
    """Complete result from safety pipeline."""

    # Core result
    is_allowed: bool = True
    safe_text: str = ""

    # Component results
    sanitization: Optional[SanitizationResult] = None
    pii_detection: Optional[PIIDetectionResult] = None
    crisis_detection: Optional[CrisisDetectionResult] = None
    content_filter: Optional[ContentFilterResult] = None

    # Consent & Verification
    consent_status: Optional[ConsentStatus] = None
    verification_status: Optional[VerificationResult] = None

    # Flags
    is_crisis: bool = False
    needs_consent: bool = False
    needs_verification: bool = False

    # If blocked
    block_reason: Optional[str] = None
    suggested_response: Optional[str] = None

    # Metadata
    processing_time_ms: float = 0.0
    audit_id: Optional[UUID] = None

    @property
    def pii_types_found(self) -> list[PIIType]:
        """Get list of PII types detected."""
        if self.pii_detection:
            return self.pii_detection.entity_types
        return []


class OutputFilterResult(BaseModel):
    """Result of filtering AI output."""

    original_response: str
    filtered_response: str

    is_safe: bool = True
    pii_leaked: bool = False
    pii_removed: list[PIIType] = Field(default_factory=list)

    content_issues: list[str] = Field(default_factory=list)
    was_modified: bool = False

    processing_time_ms: float = 0.0
