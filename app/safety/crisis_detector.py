"""
Crisis Detection Module

Detects mental health crises and safety-critical situations
that require immediate human intervention.

IMPORTANT: This is a supplementary safety layer, not a replacement
for professional crisis intervention services.
"""

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class CrisisLevel(str, Enum):
    """Severity levels for detected crises."""

    NONE = "none"
    LOW = "low"           # Mention of distress, monitor situation
    MEDIUM = "medium"     # Clear distress signals, offer resources
    HIGH = "high"         # Explicit crisis indicators, escalate to human
    CRITICAL = "critical" # Imminent danger, immediate escalation required


class CrisisType(str, Enum):
    """Types of crises that can be detected."""

    NONE = "none"
    SELF_HARM = "self_harm"
    SUICIDE = "suicide"
    HARM_TO_OTHERS = "harm_to_others"
    MEDICAL_EMERGENCY = "medical_emergency"
    DOMESTIC_ABUSE = "domestic_abuse"
    CHILD_SAFETY = "child_safety"
    SUBSTANCE_OVERDOSE = "substance_overdose"
    MENTAL_HEALTH_CRISIS = "mental_health_crisis"


@dataclass
class CrisisDetectionResult:
    """Result of crisis detection analysis."""

    is_crisis: bool
    level: CrisisLevel
    crisis_type: CrisisType
    matched_patterns: list[str] = field(default_factory=list)
    confidence: float = 0.0
    recommended_action: str = ""
    resources: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to dictionary for API responses."""
        return {
            "is_crisis": self.is_crisis,
            "level": self.level.value,
            "crisis_type": self.crisis_type.value,
            "matched_patterns": self.matched_patterns,
            "confidence": self.confidence,
            "recommended_action": self.recommended_action,
            "resources": self.resources,
        }


# ==================================
# Crisis Patterns Configuration
# ==================================

# Pattern structure: (regex_pattern, crisis_type, base_level, weight)
# Weight affects confidence calculation

CRISIS_PATTERNS: list[tuple[str, CrisisType, CrisisLevel, float]] = [
    # ==========================================
    # SUICIDE - Highest Priority
    # ==========================================

    # Explicit suicidal intent
    (r"\b(want|going|plan(ning)?|think(ing)?( about)?)\s+(to\s+)?(kill\s+myself|end\s+(my\s+)?life|die)\b",
     CrisisType.SUICIDE, CrisisLevel.CRITICAL, 1.0),
    (r"\b(i('m| am)\s+going\s+to\s+)?(commit|attempting?)\s+suicide\b",
     CrisisType.SUICIDE, CrisisLevel.CRITICAL, 1.0),
    (r"\bsuicid(e|al)\s+(ideation|thoughts?|plan)\b",
     CrisisType.SUICIDE, CrisisLevel.CRITICAL, 1.0),
    (r"\b(no\s+)?reason\s+to\s+(live|go\s+on|continue)\b",
     CrisisType.SUICIDE, CrisisLevel.HIGH, 0.8),
    (r"\bwish\s+i\s+(was|were)\s+(dead|never\s+born)\b",
     CrisisType.SUICIDE, CrisisLevel.HIGH, 0.85),
    (r"\beveryone\s+would\s+be\s+better\s+off\s+without\s+me\b",
     CrisisType.SUICIDE, CrisisLevel.HIGH, 0.8),
    (r"\bdon'?t\s+want\s+to\s+(be\s+here|exist|wake\s+up)\b",
     CrisisType.SUICIDE, CrisisLevel.HIGH, 0.75),

    # Methods mentioned
    (r"\b(pills?|overdose|hanging|jump(ing)?|gun|shoot|slit|cut)\b.{0,30}\b(myself|suicide|end\s+it)\b",
     CrisisType.SUICIDE, CrisisLevel.CRITICAL, 1.0),

    # ==========================================
    # SELF-HARM
    # ==========================================

    (r"\b(cutting|cut(ting)?)\s+(myself|my\s+(wrist|arm|leg|body))\b",
     CrisisType.SELF_HARM, CrisisLevel.HIGH, 0.9),
    (r"\bself[- ]?harm(ing)?\b",
     CrisisType.SELF_HARM, CrisisLevel.HIGH, 0.85),
    (r"\bhurt(ing)?\s+myself\b",
     CrisisType.SELF_HARM, CrisisLevel.MEDIUM, 0.7),
    (r"\bburn(ing)?\s+myself\b",
     CrisisType.SELF_HARM, CrisisLevel.HIGH, 0.85),
    (r"\bpunish(ing)?\s+my(self|\s+body)\b",
     CrisisType.SELF_HARM, CrisisLevel.MEDIUM, 0.6),

    # ==========================================
    # HARM TO OTHERS
    # ==========================================

    (r"\b(want|going|plan(ning)?)\s+to\s+(kill|hurt|harm|attack)\s+(someone|him|her|them|my)\b",
     CrisisType.HARM_TO_OTHERS, CrisisLevel.CRITICAL, 1.0),
    (r"\b(going\s+to|will)\s+(murder|shoot|stab|strangle)\b",
     CrisisType.HARM_TO_OTHERS, CrisisLevel.CRITICAL, 1.0),
    (r"\bthoughts?\s+of\s+(killing|harming|hurting)\s+(people|others|someone)\b",
     CrisisType.HARM_TO_OTHERS, CrisisLevel.HIGH, 0.85),

    # ==========================================
    # MEDICAL EMERGENCY
    # ==========================================

    (r"\b(having|think(ing)?)\s+(a\s+)?(heart\s+attack|stroke)\b",
     CrisisType.MEDICAL_EMERGENCY, CrisisLevel.CRITICAL, 0.95),
    (r"\bcan'?t\s+breathe?\b",
     CrisisType.MEDICAL_EMERGENCY, CrisisLevel.HIGH, 0.8),
    (r"\bchest\s+pain.{0,20}(severe|crushing|radiating)\b",
     CrisisType.MEDICAL_EMERGENCY, CrisisLevel.HIGH, 0.85),
    (r"\bsevere\s+(bleeding|blood\s+loss)\b",
     CrisisType.MEDICAL_EMERGENCY, CrisisLevel.CRITICAL, 0.9),
    (r"\bunconscious|passed\s+out|collapsed\b",
     CrisisType.MEDICAL_EMERGENCY, CrisisLevel.HIGH, 0.85),
    (r"\bseizure|convuls(ing|ion)\b",
     CrisisType.MEDICAL_EMERGENCY, CrisisLevel.HIGH, 0.85),
    (r"\ballergic\s+reaction.{0,20}(throat|swelling|breathe?)\b",
     CrisisType.MEDICAL_EMERGENCY, CrisisLevel.CRITICAL, 0.9),

    # ==========================================
    # SUBSTANCE OVERDOSE
    # ==========================================

    (r"\b(took|swallowed|overdos(ed?|ing))\s+(too\s+many\s+)?(pills?|medication|drugs?)\b",
     CrisisType.SUBSTANCE_OVERDOSE, CrisisLevel.CRITICAL, 0.95),
    (r"\boverdos(e|ed|ing)\b",
     CrisisType.SUBSTANCE_OVERDOSE, CrisisLevel.CRITICAL, 0.9),
    (r"\baccidentally\s+took\s+(too\s+much|double|extra)\s+(dose|medication|medicine)\b",
     CrisisType.SUBSTANCE_OVERDOSE, CrisisLevel.HIGH, 0.8),

    # ==========================================
    # DOMESTIC ABUSE
    # ==========================================

    (r"\b(partner|husband|wife|boyfriend|girlfriend|spouse)\s+(hit|hits|hitting|beat|beats|beating|hurt|hurts|hurting)\s+me\b",
     CrisisType.DOMESTIC_ABUSE, CrisisLevel.HIGH, 0.85),
    (r"\bdomestic\s+(violence|abuse)\b",
     CrisisType.DOMESTIC_ABUSE, CrisisLevel.HIGH, 0.8),
    (r"\bafraid\s+(of\s+)?(my\s+)?(partner|husband|wife|boyfriend|girlfriend)\b",
     CrisisType.DOMESTIC_ABUSE, CrisisLevel.MEDIUM, 0.7),
    (r"\b(he|she)\s+(threatens?|threatened)\s+to\s+(kill|hurt)\s+me\b",
     CrisisType.DOMESTIC_ABUSE, CrisisLevel.CRITICAL, 0.95),

    # ==========================================
    # CHILD SAFETY
    # ==========================================

    (r"\b(child|kid|minor|baby|infant)\s+(is\s+)?(being\s+)?(abuse[d]?|hurt|neglect(ed)?)\b",
     CrisisType.CHILD_SAFETY, CrisisLevel.CRITICAL, 1.0),
    (r"\b(abuse|hurt|neglect)(ing)?\s+(a\s+)?(child|kid|minor|baby)\b",
     CrisisType.CHILD_SAFETY, CrisisLevel.CRITICAL, 1.0),
    (r"\bchild\s+(abuse|endangerment|neglect)\b",
     CrisisType.CHILD_SAFETY, CrisisLevel.CRITICAL, 0.95),

    # ==========================================
    # MENTAL HEALTH CRISIS (General)
    # ==========================================

    (r"\b(having|in)\s+(a\s+)?(mental|nervous)\s+(breakdown|crisis)\b",
     CrisisType.MENTAL_HEALTH_CRISIS, CrisisLevel.HIGH, 0.8),
    (r"\bcan'?t\s+(cope|handle|take\s+it)\s+(anymore|any\s+more)\b",
     CrisisType.MENTAL_HEALTH_CRISIS, CrisisLevel.MEDIUM, 0.65),
    (r"\b(severe|extreme)\s+(anxiety|panic|depression)\b",
     CrisisType.MENTAL_HEALTH_CRISIS, CrisisLevel.MEDIUM, 0.6),
    (r"\bpanic\s+attack\b",
     CrisisType.MENTAL_HEALTH_CRISIS, CrisisLevel.MEDIUM, 0.5),
    (r"\bhallucinating|hearing\s+voices?\b",
     CrisisType.MENTAL_HEALTH_CRISIS, CrisisLevel.HIGH, 0.75),
    (r"\bpsychotic\s+(episode|break)\b",
     CrisisType.MENTAL_HEALTH_CRISIS, CrisisLevel.HIGH, 0.85),
]


# ==================================
# Crisis Resources
# ==================================

CRISIS_RESOURCES = {
    CrisisType.SUICIDE: [
        "National Suicide Prevention Lifeline: 988",
        "Crisis Text Line: Text HOME to 741741",
        "International Association for Suicide Prevention: https://www.iasp.info/resources/Crisis_Centres/",
    ],
    CrisisType.SELF_HARM: [
        "National Suicide Prevention Lifeline: 988",
        "Crisis Text Line: Text HOME to 741741",
        "SAMHSA National Helpline: 1-800-662-4357",
    ],
    CrisisType.HARM_TO_OTHERS: [
        "National Crisis Hotline: 988",
        "Emergency Services: 911",
    ],
    CrisisType.MEDICAL_EMERGENCY: [
        "Emergency Services: 911",
        "Poison Control: 1-800-222-1222",
    ],
    CrisisType.SUBSTANCE_OVERDOSE: [
        "Emergency Services: 911",
        "Poison Control: 1-800-222-1222",
        "SAMHSA National Helpline: 1-800-662-4357",
    ],
    CrisisType.DOMESTIC_ABUSE: [
        "National Domestic Violence Hotline: 1-800-799-7233",
        "Text START to 88788",
        "Emergency Services: 911",
    ],
    CrisisType.CHILD_SAFETY: [
        "Childhelp National Child Abuse Hotline: 1-800-422-4453",
        "Emergency Services: 911",
    ],
    CrisisType.MENTAL_HEALTH_CRISIS: [
        "National Crisis Hotline: 988",
        "Crisis Text Line: Text HOME to 741741",
        "NAMI Helpline: 1-800-950-6264",
    ],
}


# ==================================
# Recommended Actions
# ==================================

RECOMMENDED_ACTIONS = {
    CrisisLevel.NONE: "Continue normal conversation flow.",
    CrisisLevel.LOW: "Monitor conversation. Offer supportive responses.",
    CrisisLevel.MEDIUM: "Acknowledge distress. Provide relevant resources. Consider human review.",
    CrisisLevel.HIGH: "Prioritize safety. Provide crisis resources. Flag for human review.",
    CrisisLevel.CRITICAL: "IMMEDIATE ESCALATION. Connect to human immediately. Provide emergency resources.",
}


# ==================================
# Crisis Detector Class
# ==================================

class CrisisDetector:
    """
    Detects mental health crises and safety-critical situations.

    This detector uses pattern matching to identify concerning content
    and should be used as part of a comprehensive safety pipeline.

    Usage:
        detector = CrisisDetector()
        result = detector.detect("I want to hurt myself")
        if result.is_crisis:
            # Handle crisis appropriately
            print(f"Crisis detected: {result.crisis_type}")
            print(f"Level: {result.level}")
    """

    def __init__(
        self,
        sensitivity: float = 1.0,
        include_resources: bool = True,
    ):
        """
        Initialize Crisis Detector.

        Args:
            sensitivity: Multiplier for confidence threshold (0.5-2.0)
                        Lower = more sensitive (more detections)
                        Higher = less sensitive (fewer false positives)
            include_resources: Whether to include crisis resources in results
        """
        self.sensitivity = max(0.5, min(2.0, sensitivity))
        self.include_resources = include_resources

        # Compile patterns for efficiency
        self._compiled_patterns = [
            (re.compile(pattern, re.IGNORECASE), crisis_type, level, weight)
            for pattern, crisis_type, level, weight in CRISIS_PATTERNS
        ]

        logger.info(
            f"CrisisDetector initialized with sensitivity={self.sensitivity}, "
            f"patterns={len(self._compiled_patterns)}"
        )

    def detect(self, text: str) -> CrisisDetectionResult:
        """
        Analyze text for crisis indicators.

        Args:
            text: User message to analyze

        Returns:
            CrisisDetectionResult with detection details
        """
        if not text or not text.strip():
            return CrisisDetectionResult(
                is_crisis=False,
                level=CrisisLevel.NONE,
                crisis_type=CrisisType.NONE,
            )

        # Track all matches
        matches: list[tuple[str, CrisisType, CrisisLevel, float]] = []

        # Check each pattern
        for pattern, crisis_type, level, weight in self._compiled_patterns:
            if pattern.search(text):
                match_text = pattern.pattern[:50] + "..." if len(pattern.pattern) > 50 else pattern.pattern
                matches.append((match_text, crisis_type, level, weight))
                logger.debug(f"Crisis pattern matched: {crisis_type.value} at level {level.value}")

        # No matches
        if not matches:
            return CrisisDetectionResult(
                is_crisis=False,
                level=CrisisLevel.NONE,
                crisis_type=CrisisType.NONE,
                recommended_action=RECOMMENDED_ACTIONS[CrisisLevel.NONE],
            )

        # Determine highest severity
        level_priority = {
            CrisisLevel.NONE: 0,
            CrisisLevel.LOW: 1,
            CrisisLevel.MEDIUM: 2,
            CrisisLevel.HIGH: 3,
            CrisisLevel.CRITICAL: 4,
        }

        highest_level = CrisisLevel.NONE
        primary_type = CrisisType.NONE
        total_weight = 0.0
        matched_patterns = []

        for match_text, crisis_type, level, weight in matches:
            matched_patterns.append(f"{crisis_type.value}:{level.value}")
            total_weight += weight

            if level_priority[level] > level_priority[highest_level]:
                highest_level = level
                primary_type = crisis_type

        # Calculate confidence (capped at 1.0)
        confidence = min(1.0, total_weight / self.sensitivity)

        # Adjust level based on sensitivity
        adjusted_level = self._adjust_level_for_sensitivity(highest_level, confidence)

        # Get resources for primary crisis type
        resources = []
        if self.include_resources and primary_type != CrisisType.NONE:
            resources = CRISIS_RESOURCES.get(primary_type, [])

        return CrisisDetectionResult(
            is_crisis=True,
            level=adjusted_level,
            crisis_type=primary_type,
            matched_patterns=matched_patterns,
            confidence=round(confidence, 3),
            recommended_action=RECOMMENDED_ACTIONS[adjusted_level],
            resources=resources,
        )

    def _adjust_level_for_sensitivity(
        self,
        level: CrisisLevel,
        confidence: float
    ) -> CrisisLevel:
        """
        Adjust crisis level based on sensitivity setting.

        High sensitivity (< 1.0): May elevate levels
        Low sensitivity (> 1.0): May reduce levels for low confidence
        """
        # Never reduce CRITICAL
        if level == CrisisLevel.CRITICAL:
            return level

        level_order = [
            CrisisLevel.NONE,
            CrisisLevel.LOW,
            CrisisLevel.MEDIUM,
            CrisisLevel.HIGH,
            CrisisLevel.CRITICAL,
        ]

        current_idx = level_order.index(level)

        # Low confidence + low sensitivity = might reduce level
        if self.sensitivity > 1.3 and confidence < 0.5 and current_idx > 0:
            return level_order[current_idx - 1]

        return level

    def is_crisis(self, text: str) -> bool:
        """
        Quick check if text contains crisis indicators.

        Args:
            text: User message to check

        Returns:
            True if any crisis detected, False otherwise
        """
        return self.detect(text).is_crisis

    def get_crisis_level(self, text: str) -> CrisisLevel:
        """
        Get the crisis level for text.

        Args:
            text: User message to check

        Returns:
            CrisisLevel enum value
        """
        return self.detect(text).level


# ==================================
# Singleton & Convenience Functions
# ==================================

_detector_instance: Optional[CrisisDetector] = None


def get_detector(
    sensitivity: float = 1.0,
    include_resources: bool = True,
) -> CrisisDetector:
    """
    Get or create singleton CrisisDetector instance.

    Args:
        sensitivity: Detection sensitivity (0.5-2.0)
        include_resources: Whether to include crisis resources

    Returns:
        CrisisDetector instance
    """
    global _detector_instance
    if _detector_instance is None:
        _detector_instance = CrisisDetector(
            sensitivity=sensitivity,
            include_resources=include_resources,
        )
    return _detector_instance


def detect_crisis(text: str) -> CrisisDetectionResult:
    """
    Convenience function to detect crisis in text.

    Args:
        text: User message to analyze

    Returns:
        CrisisDetectionResult
    """
    return get_detector().detect(text)


def is_crisis(text: str) -> bool:
    """
    Convenience function to check if text contains crisis.

    Args:
        text: User message to check

    Returns:
        True if crisis detected
    """
    return get_detector().is_crisis(text)


def get_crisis_level(text: str) -> CrisisLevel:
    """
    Convenience function to get crisis level.

    Args:
        text: User message to check

    Returns:
        CrisisLevel enum value
    """
    return get_detector().get_crisis_level(text)
