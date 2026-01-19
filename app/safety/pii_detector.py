"""
PII Detection Module

Uses Microsoft Presidio with spaCy NER for detecting and redacting
personally identifiable information from text.

Layers:
1. Built-in Presidio recognizers (SSN, credit card, email, phone, etc.)
2. spaCy NER (person names, locations, organizations)
3. Custom healthcare recognizers (MRN, Insurance ID)
"""

import logging
import time
from typing import Optional

from presidio_analyzer import AnalyzerEngine, RecognizerResult, Pattern, PatternRecognizer
from presidio_analyzer.nlp_engine import NlpEngineProvider
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig

from app.safety.models import PIIType, PIIEntity, PIIDetectionResult

logger = logging.getLogger(__name__)


# ==================================
# Mapping: Presidio entity types → Our PIIType enum
# ==================================

PRESIDIO_TO_PII_TYPE: dict[str, PIIType] = {
    # Built-in Presidio types
    "US_SSN": PIIType.SSN,
    "CREDIT_CARD": PIIType.CREDIT_CARD,
    "EMAIL_ADDRESS": PIIType.EMAIL,
    "PHONE_NUMBER": PIIType.PHONE,
    "PERSON": PIIType.PERSON,
    "DATE_TIME": PIIType.DATE_OF_BIRTH,  # Context determines if it's DOB
    "LOCATION": PIIType.ADDRESS,
    "IP_ADDRESS": PIIType.IP_ADDRESS,

    # Custom healthcare types (we'll add these)
    "MEDICAL_RECORD_NUMBER": PIIType.MEDICAL_RECORD,
    "INSURANCE_ID": PIIType.INSURANCE_ID,
    "DATE_OF_BIRTH": PIIType.DATE_OF_BIRTH,
}


def get_pii_type(presidio_type: str) -> PIIType:
    """Convert Presidio entity type to our PIIType enum."""
    return PRESIDIO_TO_PII_TYPE.get(presidio_type, PIIType.UNKNOWN)


# ==================================
# Custom Healthcare Recognizers
# ==================================

class MedicalRecordNumberRecognizer(PatternRecognizer):
    """
    Recognizer for Medical Record Numbers (MRN).

    Common patterns:
    - MRN-123456
    - MRN: 123456
    - MRN#123456
    - Medical Record: 123456
    """

    def __init__(self):
        patterns = [
            Pattern(
                name="mrn_pattern_1",
                regex=r"\bMRN[-:#\s]?\s*(\d{5,10})\b",
                score=0.9,
            ),
            Pattern(
                name="mrn_pattern_2",
                regex=r"\bMedical\s+Record\s*(?:Number|#|:)?\s*(\d{5,10})\b",
                score=0.85,
            ),
            Pattern(
                name="mrn_pattern_3",
                regex=r"\bPatient\s*(?:ID|#|Number)?\s*[:=#]?\s*(\d{5,10})\b",
                score=0.7,
            ),
        ]

        super().__init__(
            supported_entity="MEDICAL_RECORD_NUMBER",
            patterns=patterns,
            context=["medical", "record", "mrn", "patient", "chart"],
            supported_language="en",
        )


class InsuranceIDRecognizer(PatternRecognizer):
    """
    Recognizer for Insurance/Member IDs.

    Common patterns:
    - Insurance ID: ABC123456789
    - Member ID: 123456789
    - Policy#: XYZ-123-456
    """

    def __init__(self):
        patterns = [
            Pattern(
                name="insurance_id_pattern_1",
                regex=r"\b(?:Insurance|Member|Policy|Subscriber)\s*(?:ID|#|Number)?\s*[:=#]?\s*([A-Z]{0,3}\d{6,12})\b",
                score=0.85,
            ),
            Pattern(
                name="insurance_id_pattern_2",
                regex=r"\b(?:Insurance|Member|Policy)\s*[:=#]?\s*([A-Z]{2,3}[-\s]?\d{3}[-\s]?\d{3,6})\b",
                score=0.8,
            ),
        ]

        super().__init__(
            supported_entity="INSURANCE_ID",
            patterns=patterns,
            context=["insurance", "member", "policy", "subscriber", "coverage", "plan"],
            supported_language="en",
        )


class DateOfBirthRecognizer(PatternRecognizer):
    """
    Recognizer specifically for Date of Birth (not just any date).

    Uses context words to identify DOB vs regular dates.
    """

    def __init__(self):
        patterns = [
            # DOB: 01/15/1990, DOB: 1990-01-15
            Pattern(
                name="dob_pattern_1",
                regex=r"\b(?:DOB|Date\s+of\s+Birth|Birth\s*date|Born)\s*[:=]?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b",
                score=0.95,
            ),
            # DOB: January 15, 1990
            Pattern(
                name="dob_pattern_2",
                regex=r"\b(?:DOB|Date\s+of\s+Birth|Birth\s*date|Born)\s*[:=]?\s*([A-Za-z]+\s+\d{1,2},?\s+\d{4})\b",
                score=0.95,
            ),
        ]

        super().__init__(
            supported_entity="DATE_OF_BIRTH",
            patterns=patterns,
            context=["dob", "birth", "born", "birthday", "age"],
            supported_language="en",
        )


# ==================================
# PII Detector Class
# ==================================

class PIIDetector:
    """
    PII Detection service using Microsoft Presidio.

    Features:
    - Built-in recognizers for common PII (SSN, credit card, email, etc.)
    - spaCy NER for names and locations
    - Custom healthcare recognizers (MRN, Insurance ID, DOB)
    - Configurable confidence thresholds
    - Graceful degradation if Presidio fails

    Usage:
        detector = PIIDetector()
        result = detector.detect("My SSN is 123-45-6789")
        print(result.redacted_text)  # "My SSN is [REDACTED_SSN]"
    """

    def __init__(
        self,
        confidence_threshold: float = 0.5,
        use_spacy: bool = True,
        spacy_model: str = "en_core_web_lg",
    ):
        """
        Initialize PII Detector.

        Args:
            confidence_threshold: Minimum confidence to consider a detection valid
            use_spacy: Whether to use spaCy NER (slower but catches names)
            spacy_model: spaCy model to use
        """
        self.confidence_threshold = confidence_threshold
        self.use_spacy = use_spacy
        self.spacy_model = spacy_model

        self._analyzer: Optional[AnalyzerEngine] = None
        self._anonymizer: Optional[AnonymizerEngine] = None
        self._initialized = False

        # Initialize on first use (lazy loading)

    def _initialize(self) -> bool:
        """
        Initialize Presidio engines.

        Returns:
            True if initialization successful, False otherwise
        """
        if self._initialized:
            return True

        try:
            logger.info("Initializing PII Detector with Presidio...")

            # Configure NLP engine with spaCy
            if self.use_spacy:
                nlp_config = {
                    "nlp_engine_name": "spacy",
                    "models": [{"lang_code": "en", "model_name": self.spacy_model}],
                }
                nlp_engine = NlpEngineProvider(nlp_configuration=nlp_config).create_engine()
                self._analyzer = AnalyzerEngine(nlp_engine=nlp_engine)
            else:
                self._analyzer = AnalyzerEngine()

            # Add custom healthcare recognizers
            self._analyzer.registry.add_recognizer(MedicalRecordNumberRecognizer())
            self._analyzer.registry.add_recognizer(InsuranceIDRecognizer())
            self._analyzer.registry.add_recognizer(DateOfBirthRecognizer())

            # Initialize anonymizer
            self._anonymizer = AnonymizerEngine()

            self._initialized = True
            logger.info("PII Detector initialized successfully")
            return True

        except Exception as e:
            logger.error(f"Failed to initialize PII Detector: {e}")
            return False

    def detect(self, text: str) -> PIIDetectionResult:
        """
        Detect PII in text.

        Args:
            text: Text to analyze

        Returns:
            PIIDetectionResult with detected entities and redacted text
        """
        start_time = time.time()

        # Handle empty text
        if not text or not text.strip():
            return PIIDetectionResult(
                original_text=text,
                redacted_text=text,
                pii_detected=False,
                detection_time_ms=0.0,
            )

        # Try to initialize if not already
        if not self._initialized and not self._initialize():
            # Fallback: return original text if Presidio fails
            logger.warning("PII Detector not initialized, returning original text")
            return PIIDetectionResult(
                original_text=text,
                redacted_text=text,
                pii_detected=False,
                detection_time_ms=(time.time() - start_time) * 1000,
            )

        try:
            # Analyze text for PII
            analyzer_results = self._analyzer.analyze(
                text=text,
                language="en",
                score_threshold=self.confidence_threshold,
            )

            # Convert to our PIIEntity format
            entities = self._convert_results(text, analyzer_results)

            # Redact if PII found
            if entities:
                redacted_text = self._redact(text, analyzer_results)
            else:
                redacted_text = text

            detection_time = (time.time() - start_time) * 1000

            return PIIDetectionResult(
                original_text=text,
                redacted_text=redacted_text,
                entities_found=entities,
                pii_detected=len(entities) > 0,
                detection_time_ms=detection_time,
            )

        except Exception as e:
            logger.error(f"Error during PII detection: {e}")
            # Graceful degradation: return original text
            return PIIDetectionResult(
                original_text=text,
                redacted_text=text,
                pii_detected=False,
                detection_time_ms=(time.time() - start_time) * 1000,
            )

    def _convert_results(
        self,
        text: str,
        results: list[RecognizerResult]
    ) -> list[PIIEntity]:
        """Convert Presidio results to our PIIEntity format."""
        entities = []

        for result in results:
            pii_type = get_pii_type(result.entity_type)

            entity = PIIEntity(
                entity_type=pii_type,
                text=text[result.start:result.end],
                start=result.start,
                end=result.end,
                confidence=result.score,
            )
            entities.append(entity)

        return entities

    def _redact(self, text: str, analyzer_results: list[RecognizerResult]) -> str:
        """
        Redact PII from text.

        Replaces each PII entity with a placeholder like [REDACTED_SSN].
        """
        # Create operator configs for each entity type
        operators = {}

        for result in analyzer_results:
            pii_type = get_pii_type(result.entity_type)
            placeholder = f"[REDACTED_{pii_type.value}]"

            operators[result.entity_type] = OperatorConfig(
                "replace",
                {"new_value": placeholder}
            )

        # Apply redaction
        anonymized = self._anonymizer.anonymize(
            text=text,
            analyzer_results=analyzer_results,
            operators=operators,
        )

        return anonymized.text

    def detect_and_extract(self, text: str) -> tuple[PIIDetectionResult, dict[PIIType, str]]:
        """
        Detect PII and also extract values (for verification purposes).

        IMPORTANT: Extracted values should only be used for verification,
        then discarded. Never store raw PII.

        Args:
            text: Text to analyze

        Returns:
            Tuple of (PIIDetectionResult, dict mapping PIIType to extracted value)
        """
        result = self.detect(text)

        extracted = {}
        for entity in result.entities_found:
            # Only keep first occurrence of each type
            if entity.entity_type not in extracted:
                extracted[entity.entity_type] = entity.text

        return result, extracted

    def get_supported_entities(self) -> list[str]:
        """Get list of all supported entity types."""
        if not self._initialized and not self._initialize():
            return []

        return self._analyzer.get_supported_entities()


# ==================================
# Module-level singleton instance
# ==================================

_detector: Optional[PIIDetector] = None


def get_pii_detector() -> PIIDetector:
    """
    Get the singleton PII Detector instance.

    Returns:
        PIIDetector instance
    """
    global _detector
    if _detector is None:
        _detector = PIIDetector()
    return _detector


def detect_pii(text: str) -> PIIDetectionResult:
    """
    Convenience function to detect PII in text.

    Args:
        text: Text to analyze

    Returns:
        PIIDetectionResult
    """
    return get_pii_detector().detect(text)


def redact_pii(text: str) -> str:
    """
    Convenience function to redact PII from text.

    Args:
        text: Text to redact

    Returns:
        Redacted text
    """
    result = detect_pii(text)
    return result.redacted_text
