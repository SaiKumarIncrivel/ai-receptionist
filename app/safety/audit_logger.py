"""
Audit Logging Module

HIPAA-compliant audit logging for all safety and compliance events.
Provides tamper-evident, searchable audit trail for regulatory compliance.
"""

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


class AuditEventType(str, Enum):
    """Types of audit events."""

    # PII Events
    PII_DETECTED = "pii_detected"
    PII_REDACTED = "pii_redacted"
    PII_ACCESS_ATTEMPT = "pii_access_attempt"

    # Crisis Events
    CRISIS_DETECTED = "crisis_detected"
    CRISIS_ESCALATED = "crisis_escalated"
    CRISIS_RESOLVED = "crisis_resolved"

    # Consent Events
    CONSENT_GRANTED = "consent_granted"
    CONSENT_WITHDRAWN = "consent_withdrawn"
    CONSENT_EXPIRED = "consent_expired"
    CONSENT_CHECK = "consent_check"

    # Verification Events
    VERIFICATION_STARTED = "verification_started"
    VERIFICATION_SUCCESS = "verification_success"
    VERIFICATION_FAILED = "verification_failed"
    VERIFICATION_LOCKED = "verification_locked"

    # Content Events
    CONTENT_FILTERED = "content_filtered"
    CONTENT_BLOCKED = "content_blocked"
    PROMPT_INJECTION_DETECTED = "prompt_injection_detected"

    # Access Events
    PHI_ACCESSED = "phi_accessed"
    APPOINTMENT_VIEWED = "appointment_viewed"
    APPOINTMENT_CREATED = "appointment_created"
    APPOINTMENT_MODIFIED = "appointment_modified"
    APPOINTMENT_CANCELLED = "appointment_cancelled"

    # AI Events
    AI_REQUEST = "ai_request"
    AI_RESPONSE = "ai_response"
    AI_RESPONSE_FILTERED = "ai_response_filtered"
    AI_HALLUCINATION_DETECTED = "ai_hallucination_detected"

    # System Events
    SYSTEM_ERROR = "system_error"
    RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"
    AUTHENTICATION_SUCCESS = "authentication_success"
    AUTHENTICATION_FAILED = "authentication_failed"

    # Human Escalation
    HUMAN_ESCALATION_REQUESTED = "human_escalation_requested"
    HUMAN_ESCALATION_COMPLETED = "human_escalation_completed"


class AuditSeverity(str, Enum):
    """Severity levels for audit events."""

    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class AuditEvent:
    """Individual audit event record."""

    id: UUID
    timestamp: datetime
    event_type: AuditEventType
    severity: AuditSeverity
    clinic_id: str

    # Actor information
    patient_id: Optional[str] = None
    user_id: Optional[str] = None
    session_id: Optional[str] = None

    # Event details
    action: str = ""
    resource: str = ""
    details: dict = field(default_factory=dict)

    # Request context
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    request_id: Optional[str] = None

    # Outcome
    outcome: str = "success"  # success, failure, partial
    error_message: Optional[str] = None

    # Integrity
    previous_hash: Optional[str] = None
    event_hash: Optional[str] = None

    def compute_hash(self, previous_hash: str = "") -> str:
        """Compute hash for tamper detection."""
        data = {
            "id": str(self.id),
            "timestamp": self.timestamp.isoformat(),
            "event_type": self.event_type.value,
            "clinic_id": self.clinic_id,
            "patient_id": self.patient_id,
            "action": self.action,
            "outcome": self.outcome,
            "previous_hash": previous_hash,
        }
        content = json.dumps(data, sort_keys=True)
        return hashlib.sha256(content.encode()).hexdigest()

    def to_dict(self) -> dict:
        """Convert to dictionary for storage/transmission."""
        return {
            "id": str(self.id),
            "timestamp": self.timestamp.isoformat(),
            "event_type": self.event_type.value,
            "severity": self.severity.value,
            "clinic_id": self.clinic_id,
            "patient_id": self.patient_id,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "action": self.action,
            "resource": self.resource,
            "details": self.details,
            "ip_address": self.ip_address,
            "user_agent": self.user_agent,
            "request_id": self.request_id,
            "outcome": self.outcome,
            "error_message": self.error_message,
            "event_hash": self.event_hash,
        }

    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict())


@dataclass
class AuditQuery:
    """Query parameters for searching audit logs."""

    clinic_id: str
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    event_types: Optional[list[AuditEventType]] = None
    severity: Optional[AuditSeverity] = None
    patient_id: Optional[str] = None
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    outcome: Optional[str] = None
    limit: int = 100
    offset: int = 0


@dataclass
class AuditSummary:
    """Summary of audit events for reporting."""

    total_events: int
    events_by_type: dict[str, int]
    events_by_severity: dict[str, int]
    events_by_outcome: dict[str, int]
    time_range_start: Optional[datetime] = None
    time_range_end: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            "total_events": self.total_events,
            "events_by_type": self.events_by_type,
            "events_by_severity": self.events_by_severity,
            "events_by_outcome": self.events_by_outcome,
            "time_range_start": self.time_range_start.isoformat() if self.time_range_start else None,
            "time_range_end": self.time_range_end.isoformat() if self.time_range_end else None,
        }


# ==================================
# Audit Logger Class
# ==================================

class AuditLogger:
    """
    HIPAA-compliant audit logger.

    Provides tamper-evident logging with hash chaining,
    structured event storage, and searchable audit trail.

    In production, events should be stored in:
    - Append-only database table
    - Immutable log storage (e.g., AWS CloudWatch, Azure Monitor)
    - SIEM system for security monitoring

    Usage:
        audit = AuditLogger(clinic_id="clinic_123")

        # Log PII detection
        audit.log_pii_detected(
            patient_id="patient_456",
            pii_types=["SSN", "PHONE"],
            action_taken="redacted"
        )

        # Log crisis event
        audit.log_crisis_detected(
            patient_id="patient_456",
            crisis_type="suicide",
            level="critical",
            escalated=True
        )
    """

    def __init__(
        self,
        clinic_id: str,
        enable_hash_chain: bool = True,
        log_to_stdout: bool = True,
    ):
        """
        Initialize Audit Logger.

        Args:
            clinic_id: Clinic identifier for multi-tenant isolation
            enable_hash_chain: Enable tamper-evident hash chaining
            log_to_stdout: Also log to standard output
        """
        self.clinic_id = clinic_id
        self.enable_hash_chain = enable_hash_chain
        self.log_to_stdout = log_to_stdout

        # In-memory storage (replace with database in production)
        self._events: list[AuditEvent] = []
        self._last_hash: str = "genesis"

        logger.info(f"AuditLogger initialized for clinic={clinic_id}")

    def log(
        self,
        event_type: AuditEventType,
        severity: AuditSeverity,
        action: str,
        resource: str = "",
        patient_id: Optional[str] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        details: Optional[dict] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        request_id: Optional[str] = None,
        outcome: str = "success",
        error_message: Optional[str] = None,
    ) -> AuditEvent:
        """
        Log an audit event.

        Args:
            event_type: Type of event
            severity: Severity level
            action: Description of action taken
            resource: Resource affected
            patient_id: Patient identifier if applicable
            user_id: User/staff identifier if applicable
            session_id: Session identifier
            details: Additional event details
            ip_address: Client IP address
            user_agent: Client user agent
            request_id: Request correlation ID
            outcome: Result of action
            error_message: Error details if failed

        Returns:
            Created AuditEvent
        """
        event = AuditEvent(
            id=uuid4(),
            timestamp=datetime.now(timezone.utc),
            event_type=event_type,
            severity=severity,
            clinic_id=self.clinic_id,
            patient_id=patient_id,
            user_id=user_id,
            session_id=session_id,
            action=action,
            resource=resource,
            details=details or {},
            ip_address=ip_address,
            user_agent=user_agent,
            request_id=request_id,
            outcome=outcome,
            error_message=error_message,
        )

        # Compute hash chain
        if self.enable_hash_chain:
            event.previous_hash = self._last_hash
            event.event_hash = event.compute_hash(self._last_hash)
            self._last_hash = event.event_hash

        # Store event
        self._events.append(event)

        # Log to stdout
        if self.log_to_stdout:
            log_level = getattr(logging, severity.value.upper(), logging.INFO)
            logger.log(
                log_level,
                f"AUDIT: {event_type.value} | {action} | "
                f"patient={patient_id} | outcome={outcome}"
            )

        return event

    # ==================================
    # Convenience Methods - PII Events
    # ==================================

    def log_pii_detected(
        self,
        patient_id: Optional[str] = None,
        pii_types: Optional[list[str]] = None,
        action_taken: str = "redacted",
        source: str = "user_input",
        details: Optional[dict] = None,
        **kwargs
    ) -> AuditEvent:
        """
        Log PII detection event.

        Args:
            patient_id: Patient identifier
            pii_types: List of PII types detected (type names only, NOT values)
            action_taken: Action taken on the PII (e.g., "sensitive_redacted", "detected_only")
            source: Source of the PII (e.g., "user_input", "ai_response")
            details: Additional details to merge (e.g., operational vs sensitive breakdown)
        """
        # Build base details
        event_details = {
            "pii_types": pii_types or [],
            "action_taken": action_taken,
            "source": source,
        }
        # Merge any additional details
        if details:
            event_details.update(details)

        return self.log(
            event_type=AuditEventType.PII_DETECTED,
            severity=AuditSeverity.INFO,
            action=f"PII detected and {action_taken}",
            resource=source,
            patient_id=patient_id,
            details=event_details,
            **kwargs
        )

    # ==================================
    # Convenience Methods - Crisis Events
    # ==================================

    def log_crisis_detected(
        self,
        patient_id: Optional[str] = None,
        crisis_type: str = "",
        level: str = "",
        escalated: bool = False,
        **kwargs
    ) -> AuditEvent:
        """Log crisis detection event."""
        severity = AuditSeverity.CRITICAL if level in ["critical", "high"] else AuditSeverity.WARNING
        return self.log(
            event_type=AuditEventType.CRISIS_DETECTED,
            severity=severity,
            action=f"Crisis detected: {crisis_type} ({level})",
            resource="conversation",
            patient_id=patient_id,
            details={
                "crisis_type": crisis_type,
                "level": level,
                "escalated": escalated,
            },
            **kwargs
        )

    def log_crisis_escalated(
        self,
        patient_id: Optional[str] = None,
        crisis_type: str = "",
        escalation_target: str = "human_agent",
        **kwargs
    ) -> AuditEvent:
        """Log crisis escalation event."""
        return self.log(
            event_type=AuditEventType.CRISIS_ESCALATED,
            severity=AuditSeverity.CRITICAL,
            action=f"Crisis escalated to {escalation_target}",
            resource="conversation",
            patient_id=patient_id,
            details={
                "crisis_type": crisis_type,
                "escalation_target": escalation_target,
            },
            **kwargs
        )

    # ==================================
    # Convenience Methods - Consent Events
    # ==================================

    def log_consent_granted(
        self,
        patient_id: str,
        consent_type: str,
        version: str = "1.0",
        **kwargs
    ) -> AuditEvent:
        """Log consent grant event."""
        return self.log(
            event_type=AuditEventType.CONSENT_GRANTED,
            severity=AuditSeverity.INFO,
            action=f"Consent granted: {consent_type}",
            resource="consent",
            patient_id=patient_id,
            details={
                "consent_type": consent_type,
                "version": version,
            },
            **kwargs
        )

    def log_consent_withdrawn(
        self,
        patient_id: str,
        consent_type: str,
        **kwargs
    ) -> AuditEvent:
        """Log consent withdrawal event."""
        return self.log(
            event_type=AuditEventType.CONSENT_WITHDRAWN,
            severity=AuditSeverity.WARNING,
            action=f"Consent withdrawn: {consent_type}",
            resource="consent",
            patient_id=patient_id,
            details={"consent_type": consent_type},
            **kwargs
        )

    # ==================================
    # Convenience Methods - Verification Events
    # ==================================

    def log_verification_started(
        self,
        patient_id: str,
        session_id: str,
        methods: list[str],
        **kwargs
    ) -> AuditEvent:
        """Log verification start event."""
        return self.log(
            event_type=AuditEventType.VERIFICATION_STARTED,
            severity=AuditSeverity.INFO,
            action="Patient verification started",
            resource="verification",
            patient_id=patient_id,
            session_id=session_id,
            details={"methods_required": methods},
            **kwargs
        )

    def log_verification_success(
        self,
        patient_id: str,
        session_id: str,
        methods_completed: list[str],
        **kwargs
    ) -> AuditEvent:
        """Log successful verification event."""
        return self.log(
            event_type=AuditEventType.VERIFICATION_SUCCESS,
            severity=AuditSeverity.INFO,
            action="Patient verification successful",
            resource="verification",
            patient_id=patient_id,
            session_id=session_id,
            details={"methods_completed": methods_completed},
            outcome="success",
            **kwargs
        )

    def log_verification_failed(
        self,
        patient_id: str,
        session_id: str,
        method: str,
        attempts: int,
        **kwargs
    ) -> AuditEvent:
        """Log failed verification attempt."""
        return self.log(
            event_type=AuditEventType.VERIFICATION_FAILED,
            severity=AuditSeverity.WARNING,
            action=f"Verification failed: {method}",
            resource="verification",
            patient_id=patient_id,
            session_id=session_id,
            details={
                "method": method,
                "attempts": attempts,
            },
            outcome="failure",
            **kwargs
        )

    def log_verification_locked(
        self,
        patient_id: str,
        session_id: str,
        lockout_duration_minutes: int = 30,
        **kwargs
    ) -> AuditEvent:
        """Log account lockout due to failed verifications."""
        return self.log(
            event_type=AuditEventType.VERIFICATION_LOCKED,
            severity=AuditSeverity.ERROR,
            action=f"Account locked for {lockout_duration_minutes} minutes",
            resource="verification",
            patient_id=patient_id,
            session_id=session_id,
            details={"lockout_duration_minutes": lockout_duration_minutes},
            outcome="failure",
            **kwargs
        )

    # ==================================
    # Convenience Methods - Content Events
    # ==================================

    def log_content_filtered(
        self,
        patient_id: Optional[str] = None,
        categories: Optional[list[str]] = None,
        action_taken: str = "warn",
        source: str = "user_input",
        **kwargs
    ) -> AuditEvent:
        """Log content filtering event."""
        return self.log(
            event_type=AuditEventType.CONTENT_FILTERED,
            severity=AuditSeverity.WARNING,
            action=f"Content filtered: {action_taken}",
            resource=source,
            patient_id=patient_id,
            details={
                "categories": categories or [],
                "action_taken": action_taken,
            },
            **kwargs
        )

    def log_prompt_injection(
        self,
        patient_id: Optional[str] = None,
        patterns_detected: Optional[list[str]] = None,
        **kwargs
    ) -> AuditEvent:
        """Log prompt injection attempt."""
        return self.log(
            event_type=AuditEventType.PROMPT_INJECTION_DETECTED,
            severity=AuditSeverity.ERROR,
            action="Prompt injection attempt detected",
            resource="user_input",
            patient_id=patient_id,
            details={"patterns_detected": patterns_detected or []},
            outcome="blocked",
            **kwargs
        )

    # ==================================
    # Convenience Methods - AI Events
    # ==================================

    def log_ai_request(
        self,
        patient_id: Optional[str] = None,
        request_type: str = "conversation",
        input_length: int = 0,
        **kwargs
    ) -> AuditEvent:
        """Log AI request event."""
        return self.log(
            event_type=AuditEventType.AI_REQUEST,
            severity=AuditSeverity.DEBUG,
            action=f"AI request: {request_type}",
            resource="ai_service",
            patient_id=patient_id,
            details={
                "request_type": request_type,
                "input_length": input_length,
            },
            **kwargs
        )

    def log_ai_response_filtered(
        self,
        patient_id: Optional[str] = None,
        reason: str = "",
        category: str = "",
        **kwargs
    ) -> AuditEvent:
        """Log AI response filtering event."""
        return self.log(
            event_type=AuditEventType.AI_RESPONSE_FILTERED,
            severity=AuditSeverity.WARNING,
            action=f"AI response filtered: {reason}",
            resource="ai_service",
            patient_id=patient_id,
            details={
                "reason": reason,
                "category": category,
            },
            **kwargs
        )

    # ==================================
    # Convenience Methods - Access Events
    # ==================================

    def log_phi_accessed(
        self,
        patient_id: str,
        user_id: Optional[str] = None,
        data_type: str = "",
        purpose: str = "",
        **kwargs
    ) -> AuditEvent:
        """Log PHI access event."""
        return self.log(
            event_type=AuditEventType.PHI_ACCESSED,
            severity=AuditSeverity.INFO,
            action=f"PHI accessed: {data_type}",
            resource="phi",
            patient_id=patient_id,
            user_id=user_id,
            details={
                "data_type": data_type,
                "purpose": purpose,
            },
            **kwargs
        )

    def log_appointment_event(
        self,
        event_type: AuditEventType,
        patient_id: str,
        appointment_id: str,
        **kwargs
    ) -> AuditEvent:
        """Log appointment-related event."""
        action_map = {
            AuditEventType.APPOINTMENT_VIEWED: "Appointment viewed",
            AuditEventType.APPOINTMENT_CREATED: "Appointment created",
            AuditEventType.APPOINTMENT_MODIFIED: "Appointment modified",
            AuditEventType.APPOINTMENT_CANCELLED: "Appointment cancelled",
        }
        return self.log(
            event_type=event_type,
            severity=AuditSeverity.INFO,
            action=action_map.get(event_type, "Appointment event"),
            resource="appointment",
            patient_id=patient_id,
            details={"appointment_id": appointment_id},
            **kwargs
        )

    # ==================================
    # Convenience Methods - System Events
    # ==================================

    def log_system_error(
        self,
        error_type: str,
        error_message: str,
        component: str = "",
        **kwargs
    ) -> AuditEvent:
        """Log system error event."""
        return self.log(
            event_type=AuditEventType.SYSTEM_ERROR,
            severity=AuditSeverity.ERROR,
            action=f"System error: {error_type}",
            resource=component,
            details={"error_type": error_type},
            outcome="failure",
            error_message=error_message,
            **kwargs
        )

    def log_rate_limit_exceeded(
        self,
        patient_id: Optional[str] = None,
        limit_type: str = "",
        current_count: int = 0,
        limit: int = 0,
        **kwargs
    ) -> AuditEvent:
        """Log rate limit exceeded event."""
        return self.log(
            event_type=AuditEventType.RATE_LIMIT_EXCEEDED,
            severity=AuditSeverity.WARNING,
            action=f"Rate limit exceeded: {limit_type}",
            resource="rate_limiter",
            patient_id=patient_id,
            details={
                "limit_type": limit_type,
                "current_count": current_count,
                "limit": limit,
            },
            outcome="blocked",
            **kwargs
        )

    # ==================================
    # Query Methods
    # ==================================

    def query(self, query: AuditQuery) -> list[AuditEvent]:
        """
        Query audit events.

        Args:
            query: Query parameters

        Returns:
            List of matching AuditEvents
        """
        results = []

        for event in self._events:
            # Filter by clinic
            if event.clinic_id != query.clinic_id:
                continue

            # Filter by time range
            if query.start_time and event.timestamp < query.start_time:
                continue
            if query.end_time and event.timestamp > query.end_time:
                continue

            # Filter by event type
            if query.event_types and event.event_type not in query.event_types:
                continue

            # Filter by severity
            if query.severity and event.severity != query.severity:
                continue

            # Filter by patient
            if query.patient_id and event.patient_id != query.patient_id:
                continue

            # Filter by user
            if query.user_id and event.user_id != query.user_id:
                continue

            # Filter by session
            if query.session_id and event.session_id != query.session_id:
                continue

            # Filter by outcome
            if query.outcome and event.outcome != query.outcome:
                continue

            results.append(event)

        # Apply pagination
        return results[query.offset:query.offset + query.limit]

    def get_summary(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> AuditSummary:
        """
        Get summary of audit events.

        Args:
            start_time: Start of time range
            end_time: End of time range

        Returns:
            AuditSummary
        """
        events = [e for e in self._events if e.clinic_id == self.clinic_id]

        if start_time:
            events = [e for e in events if e.timestamp >= start_time]
        if end_time:
            events = [e for e in events if e.timestamp <= end_time]

        events_by_type: dict[str, int] = {}
        events_by_severity: dict[str, int] = {}
        events_by_outcome: dict[str, int] = {}

        for event in events:
            events_by_type[event.event_type.value] = events_by_type.get(event.event_type.value, 0) + 1
            events_by_severity[event.severity.value] = events_by_severity.get(event.severity.value, 0) + 1
            events_by_outcome[event.outcome] = events_by_outcome.get(event.outcome, 0) + 1

        return AuditSummary(
            total_events=len(events),
            events_by_type=events_by_type,
            events_by_severity=events_by_severity,
            events_by_outcome=events_by_outcome,
            time_range_start=start_time,
            time_range_end=end_time,
        )

    def verify_chain_integrity(self) -> tuple[bool, Optional[str]]:
        """
        Verify the integrity of the hash chain.

        Returns:
            Tuple of (is_valid, error_message)
        """
        if not self.enable_hash_chain:
            return True, None

        previous_hash = "genesis"

        for i, event in enumerate(self._events):
            if event.clinic_id != self.clinic_id:
                continue

            expected_hash = event.compute_hash(previous_hash)

            if event.event_hash != expected_hash:
                return False, f"Hash mismatch at event {i} (id={event.id})"

            if event.previous_hash != previous_hash:
                return False, f"Chain broken at event {i} (id={event.id})"

            previous_hash = event.event_hash

        return True, None

    def get_patient_audit_trail(
        self,
        patient_id: str,
        limit: int = 100,
    ) -> list[AuditEvent]:
        """
        Get complete audit trail for a patient.

        Args:
            patient_id: Patient identifier
            limit: Maximum events to return

        Returns:
            List of AuditEvents for patient
        """
        query = AuditQuery(
            clinic_id=self.clinic_id,
            patient_id=patient_id,
            limit=limit,
        )
        return self.query(query)


# ==================================
# Singleton & Convenience Functions
# ==================================

_logger_instances: dict[str, AuditLogger] = {}


def get_audit_logger(clinic_id: str) -> AuditLogger:
    """
    Get or create AuditLogger for a clinic.

    Args:
        clinic_id: Clinic identifier

    Returns:
        AuditLogger instance
    """
    if clinic_id not in _logger_instances:
        _logger_instances[clinic_id] = AuditLogger(clinic_id=clinic_id)
    return _logger_instances[clinic_id]


def audit_log(
    clinic_id: str,
    event_type: AuditEventType,
    severity: AuditSeverity,
    action: str,
    **kwargs
) -> AuditEvent:
    """
    Convenience function to log audit event.

    Args:
        clinic_id: Clinic identifier
        event_type: Type of event
        severity: Severity level
        action: Action description
        **kwargs: Additional event parameters

    Returns:
        AuditEvent
    """
    return get_audit_logger(clinic_id).log(
        event_type=event_type,
        severity=severity,
        action=action,
        **kwargs
    )


# Shorthand functions for common events
def audit_pii_detected(clinic_id: str, **kwargs) -> AuditEvent:
    """Log PII detection."""
    return get_audit_logger(clinic_id).log_pii_detected(**kwargs)


def audit_crisis_detected(clinic_id: str, **kwargs) -> AuditEvent:
    """Log crisis detection."""
    return get_audit_logger(clinic_id).log_crisis_detected(**kwargs)


def audit_consent_granted(clinic_id: str, **kwargs) -> AuditEvent:
    """Log consent grant."""
    return get_audit_logger(clinic_id).log_consent_granted(**kwargs)


def audit_verification_failed(clinic_id: str, **kwargs) -> AuditEvent:
    """Log verification failure."""
    return get_audit_logger(clinic_id).log_verification_failed(**kwargs)


def audit_phi_accessed(clinic_id: str, **kwargs) -> AuditEvent:
    """Log PHI access."""
    return get_audit_logger(clinic_id).log_phi_accessed(**kwargs)
