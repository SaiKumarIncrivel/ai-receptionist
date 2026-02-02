"""
Consent Management Module

Tracks and verifies patient consent for HIPAA compliance.
Ensures explicit consent exists before processing patient data
through AI systems.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


class ConsentType(str, Enum):
    """Types of consent that can be granted."""

    AI_INTERACTION = "ai_interaction"      # Consent to interact with AI
    DATA_PROCESSING = "data_processing"    # Consent to process health data
    SMS_COMMUNICATION = "sms_communication"
    EMAIL_COMMUNICATION = "email_communication"
    VOICE_COMMUNICATION = "voice_communication"
    APPOINTMENT_REMINDERS = "appointment_reminders"
    MARKETING = "marketing"                # Optional marketing communications
    DATA_SHARING = "data_sharing"          # Share with third parties


class ConsentStatus(str, Enum):
    """Status of a consent record."""

    GRANTED = "granted"
    DENIED = "denied"
    WITHDRAWN = "withdrawn"
    EXPIRED = "expired"
    PENDING = "pending"


@dataclass
class ConsentRecord:
    """Individual consent record."""

    id: UUID
    patient_id: str
    clinic_id: str
    consent_type: ConsentType
    status: ConsentStatus
    granted_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    withdrawn_at: Optional[datetime] = None
    version: str = "1.0"
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    consent_text_hash: Optional[str] = None  # Hash of consent text shown

    def is_valid(self) -> bool:
        """Check if consent is currently valid."""
        if self.status != ConsentStatus.GRANTED:
            return False
        if self.expires_at and datetime.now(timezone.utc) > self.expires_at:
            return False
        return True

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "id": str(self.id),
            "patient_id": self.patient_id,
            "clinic_id": self.clinic_id,
            "consent_type": self.consent_type.value,
            "status": self.status.value,
            "granted_at": self.granted_at.isoformat() if self.granted_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "withdrawn_at": self.withdrawn_at.isoformat() if self.withdrawn_at else None,
            "version": self.version,
            "is_valid": self.is_valid(),
        }


@dataclass
class ConsentCheckResult:
    """Result of consent verification."""

    has_consent: bool
    missing_consents: list[ConsentType] = field(default_factory=list)
    expired_consents: list[ConsentType] = field(default_factory=list)
    message: str = ""
    requires_action: bool = False

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "has_consent": self.has_consent,
            "missing_consents": [c.value for c in self.missing_consents],
            "expired_consents": [c.value for c in self.expired_consents],
            "message": self.message,
            "requires_action": self.requires_action,
        }


# ==================================
# Consent Configuration
# ==================================

# Required consents for AI interaction
REQUIRED_CONSENTS = [
    ConsentType.AI_INTERACTION,
    ConsentType.DATA_PROCESSING,
]

# Default consent expiration (1 year)
DEFAULT_CONSENT_DURATION_DAYS = 365

# Consent text versions (for audit trail)
CONSENT_VERSIONS = {
    ConsentType.AI_INTERACTION: {
        "version": "1.0",
        "text": (
            "I consent to interact with an AI-powered medical receptionist. "
            "I understand that this AI will help with appointment scheduling "
            "and general inquiries, but will not provide medical advice. "
            "A human representative is available upon request."
        ),
    },
    ConsentType.DATA_PROCESSING: {
        "version": "1.0",
        "text": (
            "I consent to the processing of my personal and health information "
            "for the purpose of appointment scheduling and healthcare coordination. "
            "My data will be handled in accordance with HIPAA regulations."
        ),
    },
    ConsentType.SMS_COMMUNICATION: {
        "version": "1.0",
        "text": (
            "I consent to receive SMS text messages regarding my appointments "
            "and healthcare communications. Message and data rates may apply."
        ),
    },
    ConsentType.EMAIL_COMMUNICATION: {
        "version": "1.0",
        "text": (
            "I consent to receive email communications regarding my appointments "
            "and healthcare information."
        ),
    },
    ConsentType.APPOINTMENT_REMINDERS: {
        "version": "1.0",
        "text": (
            "I consent to receive automated appointment reminders via my "
            "preferred communication method."
        ),
    },
}


# ==================================
# Consent Manager Class
# ==================================

class ConsentManager:
    """
    Manages patient consent for HIPAA compliance.

    In production, this would integrate with a database.
    Current implementation uses in-memory storage for development.

    Usage:
        manager = ConsentManager(clinic_id="clinic_123")

        # Check consent before processing
        result = manager.check_consent(patient_id="patient_456")
        if not result.has_consent:
            # Request consent from patient
            return consent_request_flow(result.missing_consents)

        # Grant consent
        manager.grant_consent(
            patient_id="patient_456",
            consent_type=ConsentType.AI_INTERACTION
        )
    """

    def __init__(
        self,
        clinic_id: str,
        required_consents: Optional[list[ConsentType]] = None,
        consent_duration_days: int = DEFAULT_CONSENT_DURATION_DAYS,
    ):
        """
        Initialize Consent Manager.

        Args:
            clinic_id: Clinic identifier for multi-tenant isolation
            required_consents: List of required consent types
            consent_duration_days: Days until consent expires
        """
        self.clinic_id = clinic_id
        self.required_consents = required_consents or REQUIRED_CONSENTS
        self.consent_duration_days = consent_duration_days

        # In-memory storage (replace with database in production)
        self._consents: dict[str, dict[ConsentType, ConsentRecord]] = {}

        logger.info(
            f"ConsentManager initialized for clinic={clinic_id}, "
            f"required_consents={[c.value for c in self.required_consents]}"
        )

    def check_consent(
        self,
        patient_id: str,
        required: Optional[list[ConsentType]] = None,
    ) -> ConsentCheckResult:
        """
        Check if patient has all required consents.

        Args:
            patient_id: Patient identifier
            required: Specific consents to check (defaults to REQUIRED_CONSENTS)

        Returns:
            ConsentCheckResult with consent status
        """
        required_types = required or self.required_consents
        patient_consents = self._consents.get(patient_id, {})

        missing = []
        expired = []

        for consent_type in required_types:
            record = patient_consents.get(consent_type)

            if not record:
                missing.append(consent_type)
            elif not record.is_valid():
                if record.status == ConsentStatus.GRANTED and record.expires_at:
                    expired.append(consent_type)
                else:
                    missing.append(consent_type)

        has_consent = len(missing) == 0 and len(expired) == 0

        if has_consent:
            message = "All required consents are valid."
        elif missing and expired:
            message = (
                f"Missing consents: {[c.value for c in missing]}. "
                f"Expired consents: {[c.value for c in expired]}."
            )
        elif missing:
            message = f"Missing required consents: {[c.value for c in missing]}."
        else:
            message = f"Expired consents requiring renewal: {[c.value for c in expired]}."

        return ConsentCheckResult(
            has_consent=has_consent,
            missing_consents=missing,
            expired_consents=expired,
            message=message,
            requires_action=not has_consent,
        )

    def grant_consent(
        self,
        patient_id: str,
        consent_type: ConsentType,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        duration_days: Optional[int] = None,
    ) -> ConsentRecord:
        """
        Record patient consent.

        Args:
            patient_id: Patient identifier
            consent_type: Type of consent being granted
            ip_address: IP address for audit trail
            user_agent: User agent for audit trail
            duration_days: Custom duration (defaults to consent_duration_days)

        Returns:
            Created ConsentRecord
        """
        now = datetime.now(timezone.utc)
        duration = duration_days or self.consent_duration_days

        # Get consent version info
        version_info = CONSENT_VERSIONS.get(consent_type, {"version": "1.0"})

        record = ConsentRecord(
            id=uuid4(),
            patient_id=patient_id,
            clinic_id=self.clinic_id,
            consent_type=consent_type,
            status=ConsentStatus.GRANTED,
            granted_at=now,
            expires_at=now + timedelta(days=duration),
            version=version_info["version"],
            ip_address=ip_address,
            user_agent=user_agent,
        )

        # Store consent
        if patient_id not in self._consents:
            self._consents[patient_id] = {}
        self._consents[patient_id][consent_type] = record

        logger.info(
            f"Consent granted: patient={patient_id}, type={consent_type.value}, "
            f"expires={record.expires_at}"
        )

        return record

    def withdraw_consent(
        self,
        patient_id: str,
        consent_type: ConsentType,
    ) -> Optional[ConsentRecord]:
        """
        Withdraw previously granted consent.

        Args:
            patient_id: Patient identifier
            consent_type: Type of consent to withdraw

        Returns:
            Updated ConsentRecord or None if not found
        """
        patient_consents = self._consents.get(patient_id, {})
        record = patient_consents.get(consent_type)

        if not record:
            logger.warning(
                f"Consent withdrawal failed - not found: "
                f"patient={patient_id}, type={consent_type.value}"
            )
            return None

        record.status = ConsentStatus.WITHDRAWN
        record.withdrawn_at = datetime.now(timezone.utc)

        logger.info(
            f"Consent withdrawn: patient={patient_id}, type={consent_type.value}"
        )

        return record

    def get_consent_status(
        self,
        patient_id: str,
        consent_type: ConsentType,
    ) -> Optional[ConsentRecord]:
        """
        Get current consent status for a specific type.

        Args:
            patient_id: Patient identifier
            consent_type: Type of consent to check

        Returns:
            ConsentRecord or None if not found
        """
        return self._consents.get(patient_id, {}).get(consent_type)

    def get_all_consents(
        self,
        patient_id: str,
    ) -> list[ConsentRecord]:
        """
        Get all consent records for a patient.

        Args:
            patient_id: Patient identifier

        Returns:
            List of ConsentRecords
        """
        return list(self._consents.get(patient_id, {}).values())

    def get_consent_text(
        self,
        consent_type: ConsentType,
    ) -> dict:
        """
        Get consent text for display to patient.

        Args:
            consent_type: Type of consent

        Returns:
            Dict with version and text
        """
        return CONSENT_VERSIONS.get(consent_type, {
            "version": "1.0",
            "text": f"Consent for {consent_type.value}",
        })

    def has_valid_consent(
        self,
        patient_id: str,
        consent_type: ConsentType,
    ) -> bool:
        """
        Quick check if specific consent is valid.

        Args:
            patient_id: Patient identifier
            consent_type: Type of consent to check

        Returns:
            True if valid consent exists
        """
        record = self.get_consent_status(patient_id, consent_type)
        return record.is_valid() if record else False

    def can_process_with_ai(self, patient_id: str) -> bool:
        """
        Quick check if patient can interact with AI.

        Args:
            patient_id: Patient identifier

        Returns:
            True if all required consents are valid
        """
        return self.check_consent(patient_id).has_consent


# ==================================
# Singleton & Convenience Functions
# ==================================

_manager_instances: dict[str, ConsentManager] = {}


def get_consent_manager(clinic_id: str) -> ConsentManager:
    """
    Get or create ConsentManager for a clinic.

    Args:
        clinic_id: Clinic identifier

    Returns:
        ConsentManager instance
    """
    if clinic_id not in _manager_instances:
        _manager_instances[clinic_id] = ConsentManager(clinic_id=clinic_id)
    return _manager_instances[clinic_id]


def check_consent(
    clinic_id: str,
    patient_id: str,
    required: Optional[list[ConsentType]] = None,
) -> ConsentCheckResult:
    """
    Convenience function to check consent.

    Args:
        clinic_id: Clinic identifier
        patient_id: Patient identifier
        required: Specific consents to check

    Returns:
        ConsentCheckResult
    """
    return get_consent_manager(clinic_id).check_consent(patient_id, required)


def can_process_with_ai(clinic_id: str, patient_id: str) -> bool:
    """
    Convenience function to check AI processing consent.

    Args:
        clinic_id: Clinic identifier
        patient_id: Patient identifier

    Returns:
        True if can process with AI
    """
    return get_consent_manager(clinic_id).can_process_with_ai(patient_id)


def grant_consent(
    clinic_id: str,
    patient_id: str,
    consent_type: ConsentType,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> ConsentRecord:
    """
    Convenience function to grant consent.

    Args:
        clinic_id: Clinic identifier
        patient_id: Patient identifier
        consent_type: Type of consent
        ip_address: IP for audit
        user_agent: User agent for audit

    Returns:
        ConsentRecord
    """
    return get_consent_manager(clinic_id).grant_consent(
        patient_id=patient_id,
        consent_type=consent_type,
        ip_address=ip_address,
        user_agent=user_agent,
    )
