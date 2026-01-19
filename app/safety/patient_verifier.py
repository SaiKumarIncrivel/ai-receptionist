"""
Patient Identity Verification Module

Verifies patient identity before allowing access to PHI.
Required for HIPAA compliance to prevent unauthorized access.
"""

import hashlib
import logging
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class VerificationMethod(str, Enum):
    """Methods available for patient verification."""

    DATE_OF_BIRTH = "date_of_birth"
    PHONE_LAST_FOUR = "phone_last_four"
    SSN_LAST_FOUR = "ssn_last_four"
    VERIFICATION_CODE = "verification_code"
    SECURITY_QUESTION = "security_question"
    NAME_CONFIRMATION = "name_confirmation"


class VerificationStatus(str, Enum):
    """Status of verification attempt."""

    PENDING = "pending"
    VERIFIED = "verified"
    FAILED = "failed"
    LOCKED = "locked"        # Too many failed attempts
    EXPIRED = "expired"      # Verification session expired


@dataclass
class VerificationChallenge:
    """A verification challenge for the patient."""

    method: VerificationMethod
    prompt: str
    hint: Optional[str] = None
    attempts_remaining: int = 3

    def to_dict(self) -> dict:
        return {
            "method": self.method.value,
            "prompt": self.prompt,
            "hint": self.hint,
            "attempts_remaining": self.attempts_remaining,
        }


@dataclass
class VerificationSession:
    """Tracks a patient verification session."""

    session_id: str
    patient_id: str
    clinic_id: str
    status: VerificationStatus
    methods_required: list[VerificationMethod]
    methods_completed: list[VerificationMethod] = field(default_factory=list)
    failed_attempts: int = 0
    max_attempts: int = 5
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc) + timedelta(minutes=15))
    verified_at: Optional[datetime] = None
    verification_code: Optional[str] = None
    code_expires_at: Optional[datetime] = None

    def is_expired(self) -> bool:
        """Check if session has expired."""
        return datetime.now(timezone.utc) > self.expires_at

    def is_locked(self) -> bool:
        """Check if too many failed attempts."""
        return self.failed_attempts >= self.max_attempts

    def is_verified(self) -> bool:
        """Check if fully verified."""
        return self.status == VerificationStatus.VERIFIED

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "patient_id": self.patient_id,
            "status": self.status.value,
            "methods_required": [m.value for m in self.methods_required],
            "methods_completed": [m.value for m in self.methods_completed],
            "failed_attempts": self.failed_attempts,
            "is_verified": self.is_verified(),
            "is_locked": self.is_locked(),
            "expires_at": self.expires_at.isoformat(),
        }


@dataclass
class VerificationResult:
    """Result of a verification attempt."""

    success: bool
    status: VerificationStatus
    message: str
    next_challenge: Optional[VerificationChallenge] = None
    session: Optional[VerificationSession] = None
    requires_human: bool = False

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "status": self.status.value,
            "message": self.message,
            "next_challenge": self.next_challenge.to_dict() if self.next_challenge else None,
            "requires_human": self.requires_human,
        }


# ==================================
# Mock Patient Data (Development)
# ==================================

# In production, this comes from the database
MOCK_PATIENTS = {
    "patient_001": {
        "name": "John Smith",
        "date_of_birth": "1985-03-15",
        "phone": "555-123-4567",
        "ssn_last_four": "1234",
        "security_question": "What is your mother's maiden name?",
        "security_answer_hash": hashlib.sha256("johnson".lower().encode()).hexdigest(),
    },
    "patient_002": {
        "name": "Jane Doe",
        "date_of_birth": "1990-07-22",
        "phone": "555-987-6543",
        "ssn_last_four": "5678",
        "security_question": "What city were you born in?",
        "security_answer_hash": hashlib.sha256("chicago".lower().encode()).hexdigest(),
    },
}


# ==================================
# Configuration
# ==================================

# Default verification requirements (can be configured per clinic)
DEFAULT_VERIFICATION_METHODS = [
    VerificationMethod.DATE_OF_BIRTH,
]

# High-security actions require additional verification
HIGH_SECURITY_METHODS = [
    VerificationMethod.DATE_OF_BIRTH,
    VerificationMethod.PHONE_LAST_FOUR,
]

# Verification code settings
VERIFICATION_CODE_LENGTH = 6
VERIFICATION_CODE_EXPIRY_MINUTES = 10

# Session settings
SESSION_EXPIRY_MINUTES = 15
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_DURATION_MINUTES = 30


# ==================================
# Patient Verifier Class
# ==================================

class PatientVerifier:
    """
    Handles patient identity verification for HIPAA compliance.

    Supports multiple verification methods and tracks verification
    sessions to prevent brute force attacks.

    Usage:
        verifier = PatientVerifier(clinic_id="clinic_123")

        # Start verification
        result = verifier.start_verification(patient_id="patient_001")

        # Patient provides DOB
        result = verifier.verify(
            session_id=result.session.session_id,
            method=VerificationMethod.DATE_OF_BIRTH,
            value="1985-03-15"
        )

        if result.success:
            # Allow access to PHI
            pass
    """

    def __init__(
        self,
        clinic_id: str,
        default_methods: Optional[list[VerificationMethod]] = None,
        session_expiry_minutes: int = SESSION_EXPIRY_MINUTES,
        max_attempts: int = MAX_FAILED_ATTEMPTS,
    ):
        """
        Initialize Patient Verifier.

        Args:
            clinic_id: Clinic identifier for multi-tenant isolation
            default_methods: Default verification methods required
            session_expiry_minutes: Session timeout
            max_attempts: Max failed attempts before lockout
        """
        self.clinic_id = clinic_id
        self.default_methods = default_methods or DEFAULT_VERIFICATION_METHODS
        self.session_expiry_minutes = session_expiry_minutes
        self.max_attempts = max_attempts

        # In-memory session storage (replace with Redis in production)
        self._sessions: dict[str, VerificationSession] = {}

        # Lockout tracking
        self._lockouts: dict[str, datetime] = {}

        logger.info(
            f"PatientVerifier initialized for clinic={clinic_id}, "
            f"methods={[m.value for m in self.default_methods]}"
        )

    def start_verification(
        self,
        patient_id: str,
        methods: Optional[list[VerificationMethod]] = None,
        high_security: bool = False,
    ) -> VerificationResult:
        """
        Start a verification session for a patient.

        Args:
            patient_id: Patient identifier
            methods: Specific methods to require
            high_security: Use high-security verification

        Returns:
            VerificationResult with first challenge
        """
        # Check lockout
        if self._is_locked_out(patient_id):
            lockout_end = self._lockouts.get(patient_id)
            remaining = (lockout_end - datetime.now(timezone.utc)).seconds // 60 if lockout_end else 0
            return VerificationResult(
                success=False,
                status=VerificationStatus.LOCKED,
                message=f"Account temporarily locked. Please try again in {remaining} minutes or contact the clinic.",
                requires_human=True,
            )

        # Get patient data (in production, from database)
        patient_data = self._get_patient_data(patient_id)
        if not patient_data:
            # Don't reveal if patient exists
            logger.warning(f"Verification attempted for unknown patient: {patient_id}")
            return VerificationResult(
                success=False,
                status=VerificationStatus.FAILED,
                message="Unable to verify identity. Please contact the clinic directly.",
                requires_human=True,
            )

        # Determine methods
        if methods:
            required_methods = methods
        elif high_security:
            required_methods = HIGH_SECURITY_METHODS
        else:
            required_methods = self.default_methods

        # Create session
        session_id = secrets.token_urlsafe(32)
        session = VerificationSession(
            session_id=session_id,
            patient_id=patient_id,
            clinic_id=self.clinic_id,
            status=VerificationStatus.PENDING,
            methods_required=required_methods,
            max_attempts=self.max_attempts,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=self.session_expiry_minutes),
        )

        self._sessions[session_id] = session

        # Generate first challenge
        challenge = self._generate_challenge(patient_id, required_methods[0], patient_data)

        logger.info(f"Verification session started: patient={patient_id}, session={session_id}")

        return VerificationResult(
            success=True,
            status=VerificationStatus.PENDING,
            message="Verification required. Please answer the security question.",
            next_challenge=challenge,
            session=session,
        )

    def verify(
        self,
        session_id: str,
        method: VerificationMethod,
        value: str,
    ) -> VerificationResult:
        """
        Attempt to verify patient identity.

        Args:
            session_id: Verification session ID
            method: Verification method being used
            value: Patient's response

        Returns:
            VerificationResult with status
        """
        # Get session
        session = self._sessions.get(session_id)
        if not session:
            return VerificationResult(
                success=False,
                status=VerificationStatus.FAILED,
                message="Invalid or expired session. Please start over.",
            )

        # Check session status
        if session.is_expired():
            session.status = VerificationStatus.EXPIRED
            return VerificationResult(
                success=False,
                status=VerificationStatus.EXPIRED,
                message="Verification session expired. Please start over.",
            )

        if session.is_locked():
            self._lockouts[session.patient_id] = datetime.now(timezone.utc) + timedelta(minutes=LOCKOUT_DURATION_MINUTES)
            return VerificationResult(
                success=False,
                status=VerificationStatus.LOCKED,
                message="Too many failed attempts. Account temporarily locked.",
                requires_human=True,
            )

        # Get patient data
        patient_data = self._get_patient_data(session.patient_id)
        if not patient_data:
            return VerificationResult(
                success=False,
                status=VerificationStatus.FAILED,
                message="Verification failed. Please contact the clinic.",
                requires_human=True,
            )

        # Perform verification
        is_valid = self._verify_response(method, value, patient_data)

        if is_valid:
            session.methods_completed.append(method)

            # Check if all methods completed
            remaining = [m for m in session.methods_required if m not in session.methods_completed]

            if not remaining:
                # Fully verified
                session.status = VerificationStatus.VERIFIED
                session.verified_at = datetime.now(timezone.utc)

                logger.info(f"Patient verified: patient={session.patient_id}, session={session_id}")

                return VerificationResult(
                    success=True,
                    status=VerificationStatus.VERIFIED,
                    message="Identity verified successfully.",
                    session=session,
                )
            else:
                # More verification needed
                next_challenge = self._generate_challenge(
                    session.patient_id,
                    remaining[0],
                    patient_data
                )

                return VerificationResult(
                    success=True,
                    status=VerificationStatus.PENDING,
                    message="Verification step completed. Please continue.",
                    next_challenge=next_challenge,
                    session=session,
                )
        else:
            # Failed attempt
            session.failed_attempts += 1
            attempts_left = session.max_attempts - session.failed_attempts

            logger.warning(
                f"Verification failed: patient={session.patient_id}, "
                f"method={method.value}, attempts_left={attempts_left}"
            )

            if session.is_locked():
                self._lockouts[session.patient_id] = datetime.now(timezone.utc) + timedelta(minutes=LOCKOUT_DURATION_MINUTES)
                session.status = VerificationStatus.LOCKED
                return VerificationResult(
                    success=False,
                    status=VerificationStatus.LOCKED,
                    message="Too many failed attempts. Please contact the clinic for assistance.",
                    requires_human=True,
                )

            # Regenerate same challenge
            challenge = self._generate_challenge(session.patient_id, method, patient_data)
            challenge.attempts_remaining = attempts_left

            return VerificationResult(
                success=False,
                status=VerificationStatus.PENDING,
                message=f"Verification failed. {attempts_left} attempts remaining.",
                next_challenge=challenge,
                session=session,
            )

    def generate_verification_code(
        self,
        session_id: str,
        delivery_method: str = "sms",
    ) -> tuple[bool, str]:
        """
        Generate and send a verification code.

        Args:
            session_id: Verification session ID
            delivery_method: "sms" or "email"

        Returns:
            Tuple of (success, message)
        """
        session = self._sessions.get(session_id)
        if not session:
            return False, "Invalid session"

        # Generate code
        code = ''.join(secrets.choice('0123456789') for _ in range(VERIFICATION_CODE_LENGTH))
        session.verification_code = hashlib.sha256(code.encode()).hexdigest()
        session.code_expires_at = datetime.now(timezone.utc) + timedelta(minutes=VERIFICATION_CODE_EXPIRY_MINUTES)

        # In production: Send via SMS/email service
        # For development, we log it
        logger.info(f"Verification code generated for session={session_id}: {code}")

        return True, f"Verification code sent via {delivery_method}"

    def verify_code(
        self,
        session_id: str,
        code: str,
    ) -> VerificationResult:
        """
        Verify a verification code.

        Args:
            session_id: Verification session ID
            code: Code entered by patient

        Returns:
            VerificationResult
        """
        session = self._sessions.get(session_id)
        if not session or not session.verification_code:
            return VerificationResult(
                success=False,
                status=VerificationStatus.FAILED,
                message="Invalid session or no code requested.",
            )

        if session.code_expires_at and datetime.now(timezone.utc) > session.code_expires_at:
            return VerificationResult(
                success=False,
                status=VerificationStatus.EXPIRED,
                message="Verification code expired. Please request a new code.",
            )

        # Constant-time comparison
        code_hash = hashlib.sha256(code.encode()).hexdigest()
        if secrets.compare_digest(code_hash, session.verification_code):
            return self.verify(session_id, VerificationMethod.VERIFICATION_CODE, code)
        else:
            session.failed_attempts += 1
            return VerificationResult(
                success=False,
                status=VerificationStatus.PENDING,
                message="Invalid code. Please try again.",
            )

    def is_verified(self, session_id: str) -> bool:
        """
        Check if a session is verified.

        Args:
            session_id: Verification session ID

        Returns:
            True if verified
        """
        session = self._sessions.get(session_id)
        return session.is_verified() if session else False

    def get_session(self, session_id: str) -> Optional[VerificationSession]:
        """
        Get verification session.

        Args:
            session_id: Session ID

        Returns:
            VerificationSession or None
        """
        return self._sessions.get(session_id)

    def _get_patient_data(self, patient_id: str) -> Optional[dict]:
        """Get patient data for verification (mock for development)."""
        # In production, query from database
        return MOCK_PATIENTS.get(patient_id)

    def _is_locked_out(self, patient_id: str) -> bool:
        """Check if patient is locked out."""
        lockout_until = self._lockouts.get(patient_id)
        if lockout_until and datetime.now(timezone.utc) < lockout_until:
            return True
        elif lockout_until:
            # Lockout expired, remove it
            del self._lockouts[patient_id]
        return False

    def _generate_challenge(
        self,
        patient_id: str,
        method: VerificationMethod,
        patient_data: dict,
    ) -> VerificationChallenge:
        """Generate a verification challenge."""

        if method == VerificationMethod.DATE_OF_BIRTH:
            return VerificationChallenge(
                method=method,
                prompt="Please enter your date of birth (YYYY-MM-DD):",
                hint="Format: YYYY-MM-DD",
            )

        elif method == VerificationMethod.PHONE_LAST_FOUR:
            phone = patient_data.get("phone", "")
            hint = f"Phone ending in ...{phone[-4:]}" if len(phone) >= 4 else None
            return VerificationChallenge(
                method=method,
                prompt="Please enter the last 4 digits of the phone number on file:",
                hint=hint,
            )

        elif method == VerificationMethod.SSN_LAST_FOUR:
            return VerificationChallenge(
                method=method,
                prompt="Please enter the last 4 digits of your SSN:",
                hint="This is optional. You may skip and request a verification code instead.",
            )

        elif method == VerificationMethod.SECURITY_QUESTION:
            question = patient_data.get("security_question", "What is your security answer?")
            return VerificationChallenge(
                method=method,
                prompt=question,
            )

        elif method == VerificationMethod.NAME_CONFIRMATION:
            name = patient_data.get("name", "")
            first_name = name.split()[0] if name else ""
            return VerificationChallenge(
                method=method,
                prompt=f"Please confirm your full name (first name starts with '{first_name[0]}'):",
                hint=f"First initial: {first_name[0]}" if first_name else None,
            )

        else:
            return VerificationChallenge(
                method=method,
                prompt="Please complete verification:",
            )

    def _verify_response(
        self,
        method: VerificationMethod,
        value: str,
        patient_data: dict,
    ) -> bool:
        """Verify a patient's response using constant-time comparison."""

        value = value.strip().lower()

        if method == VerificationMethod.DATE_OF_BIRTH:
            expected = patient_data.get("date_of_birth", "").lower()
            # Handle common date formats
            value_normalized = value.replace("/", "-").replace(".", "-")
            return secrets.compare_digest(value_normalized, expected)

        elif method == VerificationMethod.PHONE_LAST_FOUR:
            expected = patient_data.get("phone", "")[-4:]
            return secrets.compare_digest(value[-4:] if len(value) >= 4 else value, expected)

        elif method == VerificationMethod.SSN_LAST_FOUR:
            expected = patient_data.get("ssn_last_four", "")
            return secrets.compare_digest(value[-4:] if len(value) >= 4 else value, expected)

        elif method == VerificationMethod.SECURITY_QUESTION:
            expected_hash = patient_data.get("security_answer_hash", "")
            value_hash = hashlib.sha256(value.encode()).hexdigest()
            return secrets.compare_digest(value_hash, expected_hash)

        elif method == VerificationMethod.NAME_CONFIRMATION:
            expected = patient_data.get("name", "").lower()
            return secrets.compare_digest(value, expected)

        return False


# ==================================
# Singleton & Convenience Functions
# ==================================

_verifier_instances: dict[str, PatientVerifier] = {}


def get_patient_verifier(clinic_id: str) -> PatientVerifier:
    """
    Get or create PatientVerifier for a clinic.

    Args:
        clinic_id: Clinic identifier

    Returns:
        PatientVerifier instance
    """
    if clinic_id not in _verifier_instances:
        _verifier_instances[clinic_id] = PatientVerifier(clinic_id=clinic_id)
    return _verifier_instances[clinic_id]


def start_verification(
    clinic_id: str,
    patient_id: str,
    high_security: bool = False,
) -> VerificationResult:
    """
    Convenience function to start verification.

    Args:
        clinic_id: Clinic identifier
        patient_id: Patient identifier
        high_security: Require additional verification

    Returns:
        VerificationResult
    """
    return get_patient_verifier(clinic_id).start_verification(
        patient_id=patient_id,
        high_security=high_security,
    )


def verify_patient(
    clinic_id: str,
    session_id: str,
    method: VerificationMethod,
    value: str,
) -> VerificationResult:
    """
    Convenience function to verify patient.

    Args:
        clinic_id: Clinic identifier
        session_id: Session ID
        method: Verification method
        value: Patient's response

    Returns:
        VerificationResult
    """
    return get_patient_verifier(clinic_id).verify(
        session_id=session_id,
        method=method,
        value=value,
    )


def is_patient_verified(clinic_id: str, session_id: str) -> bool:
    """
    Convenience function to check verification status.

    Args:
        clinic_id: Clinic identifier
        session_id: Session ID

    Returns:
        True if verified
    """
    return get_patient_verifier(clinic_id).is_verified(session_id)
