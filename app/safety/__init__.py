"""
Safety & Compliance Module (Phase 2)

Provides PII detection, crisis detection, content filtering,
consent management, patient verification, and audit logging.
"""

from app.safety.models import (
    # Enums
    PIIType,
    CrisisType,
    CrisisLevel,
    ContentCategory,
    FilterAction,
    VerificationMethod,
    VerificationStatus,
    ConsentType,
    AuditEventType,

    # Models
    PIIEntity,
    PIIDetectionResult,
    CrisisIndicator,
    CrisisDetectionResult,
    ContentFilterResult,
    SanitizationResult,
    ConsentStatus,
    ConsentRequest,
    VerificationRequest,
    VerificationResult,
    AuditEntry,
    SafetyCheckInput,
    SafetyCheckResult,
    OutputFilterResult,
)

from app.safety.pii_detector import (
    PIIDetector,
    get_pii_detector,
    detect_pii,
    redact_pii,
)

from app.safety.sanitizer import (
    Sanitizer,
    get_sanitizer,
    sanitize_input,
    is_input_safe,
    clean_input,
)

from app.safety.crisis_detector import (
    CrisisDetector,
    get_detector as get_crisis_detector,
    detect_crisis,
    is_crisis,
    get_crisis_level,
)

from app.safety.content_filter import (
    ContentFilter,
    get_filter as get_content_filter,
    filter_content,
    filter_ai_response,
    is_appropriate,
)

from app.safety.consent_manager import (
    ConsentManager,
    ConsentRecord,
    ConsentCheckResult,
    get_consent_manager,
    check_consent,
    can_process_with_ai,
    grant_consent,
)

from app.safety.patient_verifier import (
    PatientVerifier,
    VerificationChallenge,
    VerificationSession,
    get_patient_verifier,
    start_verification,
    verify_patient,
    is_patient_verified,
)

from app.safety.audit_logger import (
    AuditSeverity,
    AuditEvent,
    AuditQuery,
    AuditSummary,
    AuditLogger,
    get_audit_logger,
    audit_log,
    audit_pii_detected,
    audit_crisis_detected,
    audit_consent_granted,
    audit_verification_failed,
    audit_phi_accessed,
)

from app.safety.pipeline import (
    PipelineAction,
    PipelineContext,
    InputProcessingResult,
    OutputProcessingResult,
    SafetyPipeline,
    get_safety_pipeline,
    process_user_input,
    process_ai_output,
)

from app.safety.middleware import (
    SafetyRequestContext,
    SafetyMiddleware,
    get_safety_context,
    get_request_id,
    get_clinic_id,
    setup_safety_middleware,
    create_safe_response,
)

__all__ = [
    # Enums
    "PIIType",
    "CrisisType",
    "CrisisLevel",
    "ContentCategory",
    "FilterAction",
    "VerificationMethod",
    "VerificationStatus",
    "ConsentType",
    "AuditEventType",
    "AuditSeverity",
    "PipelineAction",

    # Models
    "PIIEntity",
    "PIIDetectionResult",
    "CrisisIndicator",
    "CrisisDetectionResult",
    "ContentFilterResult",
    "SanitizationResult",
    "ConsentStatus",
    "ConsentRequest",
    "VerificationRequest",
    "VerificationResult",
    "AuditEntry",
    "SafetyCheckInput",
    "SafetyCheckResult",
    "OutputFilterResult",

    # PII Detector
    "PIIDetector",
    "get_pii_detector",
    "detect_pii",
    "redact_pii",

    # Sanitizer
    "Sanitizer",
    "get_sanitizer",
    "sanitize_input",
    "is_input_safe",
    "clean_input",

    # Crisis Detector
    "CrisisDetector",
    "get_crisis_detector",
    "detect_crisis",
    "is_crisis",
    "get_crisis_level",

    # Content Filter
    "ContentFilter",
    "get_content_filter",
    "filter_content",
    "filter_ai_response",
    "is_appropriate",

    # Consent Manager
    "ConsentManager",
    "ConsentRecord",
    "ConsentCheckResult",
    "get_consent_manager",
    "check_consent",
    "can_process_with_ai",
    "grant_consent",

    # Patient Verifier
    "PatientVerifier",
    "VerificationChallenge",
    "VerificationSession",
    "get_patient_verifier",
    "start_verification",
    "verify_patient",
    "is_patient_verified",

    # Audit Logger
    "AuditEvent",
    "AuditQuery",
    "AuditSummary",
    "AuditLogger",
    "get_audit_logger",
    "audit_log",
    "audit_pii_detected",
    "audit_crisis_detected",
    "audit_consent_granted",
    "audit_verification_failed",
    "audit_phi_accessed",

    # Safety Pipeline
    "PipelineContext",
    "InputProcessingResult",
    "OutputProcessingResult",
    "SafetyPipeline",
    "get_safety_pipeline",
    "process_user_input",
    "process_ai_output",

    # Safety Middleware
    "SafetyRequestContext",
    "SafetyMiddleware",
    "get_safety_context",
    "get_request_id",
    "get_clinic_id",
    "setup_safety_middleware",
    "create_safe_response",
]
