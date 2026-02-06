"""
Safety Pipeline Orchestrator

Central orchestrator that processes all messages through the
complete safety and compliance pipeline.

This is the single entry point for all safety checks.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from uuid import uuid4

from app.safety.sanitizer import Sanitizer, SanitizationResult
from app.safety.pii_detector import PIIDetector, PIIDetectionResult
from app.safety.crisis_detector import (
    CrisisDetector,
    CrisisDetectionResult,
    CrisisLevel,
)
from app.safety.content_filter import (
    ContentFilter,
    ContentFilterResult,
    FilterAction,
)
from app.safety.consent_manager import (
    ConsentManager,
    ConsentCheckResult,
    ConsentType,
)
from app.safety.patient_verifier import (
    PatientVerifier,
    VerificationResult,
    VerificationStatus,
)
from app.safety.audit_logger import (
    AuditLogger,
    AuditEventType,
    AuditSeverity,
)

logger = logging.getLogger(__name__)


class PipelineAction(str, Enum):
    """Actions the pipeline can recommend."""

    PROCEED = "proceed"                    # Safe to continue
    PROCEED_WITH_REDACTION = "proceed_with_redaction"  # Continue with PII redacted
    REQUIRE_CONSENT = "require_consent"    # Need consent before proceeding
    REQUIRE_VERIFICATION = "require_verification"  # Need identity verification
    ESCALATE_CRISIS = "escalate_crisis"    # Immediate human intervention
    REDIRECT = "redirect"                  # Gently redirect conversation
    BLOCK = "block"                        # Block and provide safe response
    HUMAN_REVIEW = "human_review"          # Flag for human review


@dataclass
class PipelineContext:
    """Context for pipeline processing."""

    clinic_id: str
    patient_id: Optional[str] = None
    session_id: Optional[str] = None
    verification_session_id: Optional[str] = None
    request_id: Optional[str] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None

    # Processing flags
    skip_consent_check: bool = False
    skip_verification: bool = False
    high_security: bool = False

    def to_dict(self) -> dict:
        return {
            "clinic_id": self.clinic_id,
            "patient_id": self.patient_id,
            "session_id": self.session_id,
            "request_id": self.request_id,
        }


@dataclass
class InputProcessingResult:
    """Result of processing user input through safety pipeline."""

    # Overall result
    request_id: str
    timestamp: datetime
    action: PipelineAction
    can_proceed: bool

    # Processed text
    original_text: str
    processed_text: str  # After sanitization and PII redaction

    # Component results
    sanitization: Optional[SanitizationResult] = None
    pii_detection: Optional[PIIDetectionResult] = None
    crisis_detection: Optional[CrisisDetectionResult] = None
    content_filter: Optional[ContentFilterResult] = None
    consent_check: Optional[ConsentCheckResult] = None

    # Flags
    has_pii: bool = False
    has_crisis: bool = False
    has_inappropriate_content: bool = False
    has_prompt_injection: bool = False
    requires_consent: bool = False
    requires_verification: bool = False

    # Response guidance
    suggested_response: Optional[str] = None
    crisis_resources: list[str] = field(default_factory=list)

    # Metadata
    processing_time_ms: float = 0.0
    components_run: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "request_id": self.request_id,
            "timestamp": self.timestamp.isoformat(),
            "action": self.action.value,
            "can_proceed": self.can_proceed,
            "processed_text": self.processed_text,
            "has_pii": self.has_pii,
            "has_crisis": self.has_crisis,
            "has_inappropriate_content": self.has_inappropriate_content,
            "has_prompt_injection": self.has_prompt_injection,
            "requires_consent": self.requires_consent,
            "requires_verification": self.requires_verification,
            "suggested_response": self.suggested_response,
            "crisis_resources": self.crisis_resources,
            "processing_time_ms": self.processing_time_ms,
            "components_run": self.components_run,
        }


@dataclass
class OutputProcessingResult:
    """Result of processing AI output through safety pipeline."""

    request_id: str
    timestamp: datetime
    action: PipelineAction
    can_send: bool

    original_text: str
    processed_text: str

    # Component results
    pii_detection: Optional[PIIDetectionResult] = None
    content_filter: Optional[ContentFilterResult] = None

    # Flags
    has_pii_leak: bool = False
    has_hallucination: bool = False
    has_medical_advice: bool = False
    has_inappropriate_content: bool = False

    # If blocked, use this instead
    fallback_response: Optional[str] = None

    processing_time_ms: float = 0.0

    def to_dict(self) -> dict:
        return {
            "request_id": self.request_id,
            "timestamp": self.timestamp.isoformat(),
            "action": self.action.value,
            "can_send": self.can_send,
            "processed_text": self.processed_text,
            "has_pii_leak": self.has_pii_leak,
            "has_hallucination": self.has_hallucination,
            "has_medical_advice": self.has_medical_advice,
            "fallback_response": self.fallback_response,
            "processing_time_ms": self.processing_time_ms,
        }


# ==================================
# Fallback Responses
# ==================================

FALLBACK_RESPONSES = {
    PipelineAction.ESCALATE_CRISIS: (
        "I'm concerned about what you've shared. Your safety is the top priority. "
        "Please reach out to one of these resources:\n\n"
        "• National Crisis Hotline: 988\n"
        "• Crisis Text Line: Text HOME to 741741\n"
        "• Emergency Services: 911\n\n"
        "Would you like me to connect you with a staff member who can help?"
    ),
    PipelineAction.REQUIRE_CONSENT: (
        "Before I can assist you, I need your consent to proceed. "
        "This AI assistant will help with appointment scheduling and general inquiries. "
        "Your information will be handled according to HIPAA regulations. "
        "Do you consent to continue?"
    ),
    PipelineAction.REQUIRE_VERIFICATION: (
        "For your security, I need to verify your identity before we continue. "
        "This helps protect your personal health information."
    ),
    PipelineAction.BLOCK: (
        "I'm not able to help with that request. "
        "I'm here to assist with healthcare-related questions like "
        "scheduling appointments or answering questions about our clinic. "
        "How can I help you with your healthcare needs?"
    ),
    PipelineAction.REDIRECT: (
        "I'd be happy to help you with healthcare-related questions. "
        "Is there something about appointments, clinic services, or "
        "general health inquiries I can assist with?"
    ),
    "ai_blocked": (
        "I apologize, but I'm not able to provide that specific information. "
        "For medical advice, please consult with your healthcare provider directly. "
        "Is there something else I can help you with regarding appointments or clinic services?"
    ),
}


# ==================================
# Safety Pipeline Class
# ==================================

class SafetyPipeline:
    """
    Orchestrates all safety components into a unified pipeline.

    This is the single entry point for processing both user input
    and AI output through all safety checks.

    Usage:
        pipeline = SafetyPipeline(clinic_id="clinic_123")

        # Process user input
        context = PipelineContext(
            clinic_id="clinic_123",
            patient_id="patient_456",
            session_id="session_789"
        )
        result = pipeline.process_input("I need to schedule an appointment", context)

        if result.can_proceed:
            # Safe to send to AI
            ai_response = call_ai(result.processed_text)

            # Process AI output
            output_result = pipeline.process_output(ai_response, context)
            if output_result.can_send:
                return output_result.processed_text
            else:
                return output_result.fallback_response
        else:
            return result.suggested_response
    """

    def __init__(
        self,
        clinic_id: str,
        enable_pii_detection: bool = True,
        enable_crisis_detection: bool = True,
        enable_content_filter: bool = True,
        enable_consent_check: bool = True,
        enable_audit_logging: bool = True,
        strict_mode: bool = False,
    ):
        """
        Initialize Safety Pipeline.

        Args:
            clinic_id: Clinic identifier for multi-tenant isolation
            enable_pii_detection: Enable PII detection and redaction
            enable_crisis_detection: Enable crisis detection
            enable_content_filter: Enable content filtering
            enable_consent_check: Enable consent verification
            enable_audit_logging: Enable audit logging
            strict_mode: Enable strict filtering thresholds
        """
        self.clinic_id = clinic_id

        # Feature flags
        self._enable_pii = enable_pii_detection
        self._enable_crisis = enable_crisis_detection
        self._enable_content = enable_content_filter
        self._enable_consent = enable_consent_check
        self._enable_audit = enable_audit_logging

        # Initialize components
        self.sanitizer = Sanitizer()

        if self._enable_pii:
            self.pii_detector = PIIDetector()

        if self._enable_crisis:
            self.crisis_detector = CrisisDetector()

        if self._enable_content:
            self.content_filter = ContentFilter(
                strict_mode=strict_mode,
                filter_ai_output=True,
                healthcare_context=True,
            )

        if self._enable_consent:
            self.consent_manager = ConsentManager(clinic_id=clinic_id)

        self.patient_verifier = PatientVerifier(clinic_id=clinic_id)

        if self._enable_audit:
            self.audit_logger = AuditLogger(clinic_id=clinic_id)

        logger.info(
            f"SafetyPipeline initialized for clinic={clinic_id}, "
            f"pii={enable_pii_detection}, crisis={enable_crisis_detection}, "
            f"content={enable_content_filter}, consent={enable_consent_check}"
        )

    def process_input(
        self,
        text: str,
        context: PipelineContext,
    ) -> InputProcessingResult:
        """
        Process user input through the complete safety pipeline.

        Pipeline order:
        1. Sanitization (clean input, detect prompt injection)
        2. Consent check (if patient identified)
        3. PII detection and redaction
        4. Crisis detection
        5. Content filtering

        Args:
            text: User input text
            context: Processing context

        Returns:
            InputProcessingResult with all findings
        """
        import time
        start_time = time.time()

        request_id = context.request_id or str(uuid4())
        components_run = []

        # Initialize result
        result = InputProcessingResult(
            request_id=request_id,
            timestamp=datetime.now(timezone.utc),
            action=PipelineAction.PROCEED,
            can_proceed=True,
            original_text=text,
            processed_text=text,
        )

        try:
            # ==================================
            # Step 1: Sanitization
            # ==================================
            sanitization = self.sanitizer.sanitize(text)
            result.sanitization = sanitization
            result.processed_text = sanitization.sanitized_text
            components_run.append("sanitizer")

            # Check for prompt injection
            if sanitization.prompt_injection_detected:
                result.has_prompt_injection = True
                result.action = PipelineAction.BLOCK
                result.can_proceed = False
                result.suggested_response = FALLBACK_RESPONSES[PipelineAction.BLOCK]

                if self._enable_audit:
                    self.audit_logger.log_prompt_injection(
                        patient_id=context.patient_id,
                        patterns_detected=sanitization.changes_made,
                        ip_address=context.ip_address,
                        request_id=request_id,
                    )

                # Don't process further - potential attack
                result.processing_time_ms = (time.time() - start_time) * 1000
                result.components_run = components_run
                return result

            # ==================================
            # Step 2: Consent Check
            # ==================================
            if self._enable_consent and context.patient_id and not context.skip_consent_check:
                consent_result = self.consent_manager.check_consent(context.patient_id)
                result.consent_check = consent_result
                components_run.append("consent_manager")

                if not consent_result.has_consent:
                    result.requires_consent = True
                    result.action = PipelineAction.REQUIRE_CONSENT
                    result.can_proceed = False
                    result.suggested_response = FALLBACK_RESPONSES[PipelineAction.REQUIRE_CONSENT]

                    if self._enable_audit:
                        self.audit_logger.log(
                            event_type=AuditEventType.CONSENT_CHECK,
                            severity=AuditSeverity.WARNING,
                            action="Consent required but not granted",
                            patient_id=context.patient_id,
                            details={"missing": [c.value for c in consent_result.missing_consents]},
                            request_id=request_id,
                        )

                    result.processing_time_ms = (time.time() - start_time) * 1000
                    result.components_run = components_run
                    return result

            # ==================================
            # Step 3: PII Detection
            # ==================================
            if self._enable_pii:
                pii_result = self.pii_detector.detect(result.processed_text)
                result.pii_detection = pii_result
                components_run.append("pii_detector")

                if pii_result.pii_detected:
                    result.has_pii = True
                    result.processed_text = pii_result.redacted_text

                    # Update action but allow proceeding with redacted text
                    if result.action == PipelineAction.PROCEED:
                        result.action = PipelineAction.PROCEED_WITH_REDACTION

                    if self._enable_audit:
                        self.audit_logger.log_pii_detected(
                            patient_id=context.patient_id,
                            pii_types=[e.entity_type.value for e in pii_result.entities_found],
                            action_taken="redacted",
                            ip_address=context.ip_address,
                            request_id=request_id,
                        )

            # ==================================
            # Step 4: Crisis Detection
            # ==================================
            if self._enable_crisis:
                crisis_result = self.crisis_detector.detect(result.processed_text)
                result.crisis_detection = crisis_result
                components_run.append("crisis_detector")

                if crisis_result.is_crisis:
                    result.has_crisis = True
                    result.crisis_resources = crisis_result.resources

                    # Determine action based on severity
                    if crisis_result.level in [CrisisLevel.CRITICAL, CrisisLevel.HIGH]:
                        result.action = PipelineAction.ESCALATE_CRISIS
                        result.can_proceed = False
                        result.suggested_response = FALLBACK_RESPONSES[PipelineAction.ESCALATE_CRISIS]

                        if self._enable_audit:
                            self.audit_logger.log_crisis_detected(
                                patient_id=context.patient_id,
                                crisis_type=crisis_result.crisis_type.value,
                                level=crisis_result.level.value,
                                escalated=True,
                                ip_address=context.ip_address,
                                request_id=request_id,
                            )

                        result.processing_time_ms = (time.time() - start_time) * 1000
                        result.components_run = components_run
                        return result
                    else:
                        # Lower severity - log but continue
                        if self._enable_audit:
                            self.audit_logger.log_crisis_detected(
                                patient_id=context.patient_id,
                                crisis_type=crisis_result.crisis_type.value,
                                level=crisis_result.level.value,
                                escalated=False,
                                request_id=request_id,
                            )

            # ==================================
            # Step 5: Content Filtering
            # ==================================
            if self._enable_content:
                content_result = self.content_filter.filter_input(result.processed_text)
                result.content_filter = content_result
                components_run.append("content_filter")

                if not content_result.is_appropriate:
                    result.has_inappropriate_content = True

                    if content_result.action == FilterAction.BLOCK:
                        result.action = PipelineAction.BLOCK
                        result.can_proceed = False
                        result.suggested_response = content_result.suggested_response or FALLBACK_RESPONSES[PipelineAction.BLOCK]
                    elif content_result.action == FilterAction.REDIRECT:
                        result.action = PipelineAction.REDIRECT
                        result.can_proceed = False
                        result.suggested_response = content_result.suggested_response or FALLBACK_RESPONSES[PipelineAction.REDIRECT]
                    elif content_result.action == FilterAction.WARN:
                        # Allow but flag for review
                        if result.action == PipelineAction.PROCEED:
                            result.action = PipelineAction.HUMAN_REVIEW

                    if self._enable_audit:
                        self.audit_logger.log_content_filtered(
                            patient_id=context.patient_id,
                            categories=[c.value for c in content_result.categories_detected],
                            action_taken=content_result.action.value,
                            ip_address=context.ip_address,
                            request_id=request_id,
                        )

            # Log successful processing
            if self._enable_audit and result.can_proceed:
                self.audit_logger.log_ai_request(
                    patient_id=context.patient_id,
                    request_type="conversation",
                    input_length=len(result.processed_text),
                    request_id=request_id,
                )

        except Exception as e:
            logger.error(f"Safety pipeline error: {e}", exc_info=True)
            result.action = PipelineAction.HUMAN_REVIEW
            result.can_proceed = False
            result.suggested_response = (
                "I apologize, but I'm experiencing a technical issue. "
                "Please try again or contact the clinic directly."
            )

            if self._enable_audit:
                self.audit_logger.log_system_error(
                    error_type="pipeline_error",
                    error_message=str(e),
                    component="safety_pipeline",
                    patient_id=context.patient_id,
                    request_id=request_id,
                )

        result.processing_time_ms = (time.time() - start_time) * 1000
        result.components_run = components_run
        return result

    def process_output(
        self,
        text: str,
        context: PipelineContext,
    ) -> OutputProcessingResult:
        """
        Process AI output through safety filters.

        Checks for:
        1. PII leakage (AI accidentally revealing patient data)
        2. Hallucinations (made-up medical facts)
        3. Inappropriate medical advice
        4. Other inappropriate content

        Args:
            text: AI response text
            context: Processing context

        Returns:
            OutputProcessingResult
        """
        import time
        start_time = time.time()

        request_id = context.request_id or str(uuid4())

        result = OutputProcessingResult(
            request_id=request_id,
            timestamp=datetime.now(timezone.utc),
            action=PipelineAction.PROCEED,
            can_send=True,
            original_text=text,
            processed_text=text,
        )

        try:
            # ==================================
            # Step 1: Check for PII Leakage
            # ==================================
            if self._enable_pii:
                pii_result = self.pii_detector.detect(text)
                result.pii_detection = pii_result

                if pii_result.pii_detected:
                    result.has_pii_leak = True
                    result.processed_text = pii_result.redacted_text

                    if self._enable_audit:
                        self.audit_logger.log_pii_detected(
                            patient_id=context.patient_id,
                            pii_types=[e.entity_type.value for e in pii_result.entities_found],
                            action_taken="redacted_from_output",
                            source="ai_response",
                            request_id=request_id,
                        )

            # ==================================
            # Step 2: Content Filter (Output Mode)
            # ==================================
            if self._enable_content:
                content_result = self.content_filter.filter_output(text)
                result.content_filter = content_result

                if not content_result.is_appropriate:
                    from app.safety.content_filter import ContentCategory

                    if ContentCategory.HALLUCINATION in content_result.categories_detected:
                        result.has_hallucination = True

                    if ContentCategory.MEDICAL_ADVICE in content_result.categories_detected:
                        result.has_medical_advice = True

                    if content_result.action == FilterAction.BLOCK:
                        result.action = PipelineAction.BLOCK
                        result.can_send = False
                        result.fallback_response = FALLBACK_RESPONSES["ai_blocked"]

                        if self._enable_audit:
                            self.audit_logger.log_ai_response_filtered(
                                patient_id=context.patient_id,
                                reason="blocked",
                                category=content_result.categories_detected[0].value if content_result.categories_detected else "unknown",
                                request_id=request_id,
                            )

                    elif content_result.action == FilterAction.WARN:
                        result.action = PipelineAction.HUMAN_REVIEW
                        # Still send but flag for review

                        if self._enable_audit:
                            self.audit_logger.log_ai_response_filtered(
                                patient_id=context.patient_id,
                                reason="flagged",
                                category=content_result.categories_detected[0].value if content_result.categories_detected else "unknown",
                                request_id=request_id,
                            )

        except Exception as e:
            logger.error(f"Output processing error: {e}", exc_info=True)
            result.action = PipelineAction.BLOCK
            result.can_send = False
            result.fallback_response = FALLBACK_RESPONSES["ai_blocked"]

            if self._enable_audit:
                self.audit_logger.log_system_error(
                    error_type="output_processing_error",
                    error_message=str(e),
                    component="safety_pipeline",
                    request_id=request_id,
                )

        result.processing_time_ms = (time.time() - start_time) * 1000
        return result

    def grant_consent(
        self,
        patient_id: str,
        consent_types: Optional[list[ConsentType]] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> list:
        """
        Grant consent for a patient.

        Args:
            patient_id: Patient identifier
            consent_types: Types of consent to grant (defaults to required)
            ip_address: IP address for audit
            user_agent: User agent for audit

        Returns:
            List of granted ConsentRecords
        """
        if not self._enable_consent:
            return []

        types_to_grant = consent_types or [
            ConsentType.AI_INTERACTION,
            ConsentType.DATA_PROCESSING,
        ]

        records = []
        for consent_type in types_to_grant:
            record = self.consent_manager.grant_consent(
                patient_id=patient_id,
                consent_type=consent_type,
                ip_address=ip_address,
                user_agent=user_agent,
            )
            records.append(record)

            if self._enable_audit:
                self.audit_logger.log_consent_granted(
                    patient_id=patient_id,
                    consent_type=consent_type.value,
                    ip_address=ip_address,
                )

        return records

    def start_verification(
        self,
        patient_id: str,
        high_security: bool = False,
    ) -> VerificationResult:
        """
        Start patient verification.

        Args:
            patient_id: Patient identifier
            high_security: Require additional verification

        Returns:
            VerificationResult
        """
        result = self.patient_verifier.start_verification(
            patient_id=patient_id,
            high_security=high_security,
        )

        if self._enable_audit and result.session:
            self.audit_logger.log_verification_started(
                patient_id=patient_id,
                session_id=result.session.session_id,
                methods=[m.value for m in result.session.methods_required],
            )

        return result

    def get_audit_summary(self) -> dict:
        """Get audit summary for this clinic."""
        if self._enable_audit:
            summary = self.audit_logger.get_summary()
            return summary.to_dict()
        return {}


# ==================================
# Singleton & Convenience Functions
# ==================================

_pipeline_instances: dict[str, SafetyPipeline] = {}


def get_safety_pipeline(
    clinic_id: str,
    **kwargs
) -> SafetyPipeline:
    """
    Get or create SafetyPipeline for a clinic.

    Args:
        clinic_id: Clinic identifier
        **kwargs: Pipeline configuration options

    Returns:
        SafetyPipeline instance
    """
    if clinic_id not in _pipeline_instances:
        _pipeline_instances[clinic_id] = SafetyPipeline(clinic_id=clinic_id, **kwargs)
    return _pipeline_instances[clinic_id]


def process_user_input(
    clinic_id: str,
    text: str,
    patient_id: Optional[str] = None,
    session_id: Optional[str] = None,
    **kwargs
) -> InputProcessingResult:
    """
    Convenience function to process user input.

    Args:
        clinic_id: Clinic identifier
        text: User input text
        patient_id: Patient identifier
        session_id: Session identifier
        **kwargs: Additional context

    Returns:
        InputProcessingResult
    """
    pipeline = get_safety_pipeline(clinic_id)
    context = PipelineContext(
        clinic_id=clinic_id,
        patient_id=patient_id,
        session_id=session_id,
        **kwargs
    )
    return pipeline.process_input(text, context)


def process_ai_output(
    clinic_id: str,
    text: str,
    patient_id: Optional[str] = None,
    **kwargs
) -> OutputProcessingResult:
    """
    Convenience function to process AI output.

    Args:
        clinic_id: Clinic identifier
        text: AI response text
        patient_id: Patient identifier
        **kwargs: Additional context

    Returns:
        OutputProcessingResult
    """
    pipeline = get_safety_pipeline(clinic_id)
    context = PipelineContext(
        clinic_id=clinic_id,
        patient_id=patient_id,
        **kwargs
    )
    return pipeline.process_output(text, context)
