"""
Content Filter Module

Filters inappropriate content for a medical receptionist AI context.
Used for both input filtering (user messages) and output filtering
(AI responses) to ensure professional, appropriate interactions.
"""

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class ContentCategory(str, Enum):
    """Categories of filtered content."""

    CLEAN = "clean"
    PROFANITY = "profanity"
    SEXUAL = "sexual"
    VIOLENCE = "violence"
    SPAM = "spam"
    OFF_TOPIC = "off_topic"
    HATE_SPEECH = "hate_speech"
    HALLUCINATION = "hallucination"  # For AI output filtering
    MEDICAL_ADVICE = "medical_advice"  # AI giving specific medical advice


class FilterAction(str, Enum):
    """Actions to take on filtered content."""

    ALLOW = "allow"           # Content is fine
    WARN = "warn"             # Flag but allow
    REDIRECT = "redirect"     # Gently redirect conversation
    BLOCK = "block"           # Block and provide standard response


@dataclass
class ContentFilterResult:
    """Result of content filtering analysis."""

    is_appropriate: bool
    action: FilterAction
    categories_detected: list[ContentCategory] = field(default_factory=list)
    confidence: float = 0.0
    reason: str = ""
    suggested_response: str = ""

    def to_dict(self) -> dict:
        """Convert to dictionary for API responses."""
        return {
            "is_appropriate": self.is_appropriate,
            "action": self.action.value,
            "categories_detected": [c.value for c in self.categories_detected],
            "confidence": self.confidence,
            "reason": self.reason,
            "suggested_response": self.suggested_response,
        }


# ==================================
# Content Patterns Configuration
# ==================================

# Structure: (pattern, category, action, weight)

PROFANITY_PATTERNS: list[tuple[str, float]] = [
    # Severe profanity (block)
    (r"\bf+u+c+k+\w*\b", 0.9),
    (r"\bs+h+i+t+\w*\b", 0.7),
    (r"\ba+s+s+h+o+l+e+\b", 0.85),
    (r"\bb+i+t+c+h+\w*\b", 0.8),
    (r"\bd+a+m+n+\b", 0.3),  # Mild
    (r"\bh+e+l+l+\b", 0.2),  # Very mild, context-dependent
    (r"\bcrap\b", 0.2),
    (r"\bpiss(ed)?\b", 0.4),

    # Slurs and hate speech (always block)
    (r"\b(n+i+g+g+\w*|f+a+g+\w*|r+e+t+a+r+d+\w*)\b", 1.0),
]

SEXUAL_PATTERNS: list[tuple[str, float]] = [
    (r"\b(sex|sexual|sexy)\b", 0.5),
    (r"\b(porn|pornograph\w*)\b", 0.95),
    (r"\b(nude|naked|nud(ity|e))\b", 0.7),
    (r"\b(erotic|xxx)\b", 0.9),
    # Medical terms are excluded - handled separately
]

VIOLENCE_PATTERNS: list[tuple[str, float]] = [
    # Non-crisis violence (crisis detector handles actual threats)
    (r"\b(gore|gory|gruesome)\b", 0.7),
    (r"\b(torture|torturing)\b", 0.8),
    (r"\b(mutilat\w*)\b", 0.85),
    # Gaming/entertainment violence - lower weight
    (r"\b(kill(ed|ing)?|murder(ed|ing)?)\b(?!.*\b(myself|me|suicide)\b)", 0.3),
]

SPAM_PATTERNS: list[tuple[str, float]] = [
    (r"\b(buy\s+now|click\s+here|free\s+offer)\b", 0.8),
    (r"\b(make\s+money|earn\s+\$|work\s+from\s+home)\b", 0.7),
    (r"\b(viagra|cialis|pharmacy|pills?\s+online)\b", 0.9),
    (r"\b(casino|lottery|jackpot|winner)\b", 0.6),
    (r"(https?://\S+){3,}", 0.75),  # Multiple URLs
    (r"\b(subscribe|unsubscribe|newsletter)\b", 0.4),
    (r"[A-Z\s]{20,}", 0.5),  # Excessive caps
    (r"(.)\1{5,}", 0.6),  # Repeated characters
]

OFF_TOPIC_PATTERNS: list[tuple[str, float]] = [
    # Completely unrelated to healthcare
    (r"\b(stock\s+market|crypto|bitcoin|trading)\b", 0.7),
    (r"\b(recipe|cooking|baking)\b(?!.*(diet|nutrition|allergy))", 0.5),
    (r"\b(sports?\s+score|game\s+result|playoffs?)\b", 0.6),
    (r"\b(movie|film|tv\s+show|netflix)\b(?!.*(anxiety|stress|mental))", 0.4),
    (r"\b(dating|tinder|relationship\s+advice)\b(?!.*(health|std|mental))", 0.5),
    (r"\b(homework|essay|assignment)\b(?!.*(medical|health))", 0.6),
    (r"\b(code|programming|software|app\s+develop)\b(?!.*(medical|health))", 0.5),
]

# For AI output filtering - detect potential hallucinations
HALLUCINATION_PATTERNS: list[tuple[str, float]] = [
    # Made-up citations
    (r"\b(study\s+shows?|research\s+(indicates?|proves?))\b(?!.*\d{4})", 0.4),
    # Overly specific fake statistics
    (r"\b\d{2,3}(\.\d+)?%\s+of\s+(patients?|people|cases?)\b", 0.3),
    # Confident medical claims an AI shouldn't make
    (r"\byou\s+(definitely|certainly|absolutely)\s+have\b", 0.8),
    (r"\bthis\s+is\s+(definitely|certainly)\s+(not\s+)?cancer\b", 0.9),
    (r"\byou\s+don'?t\s+need\s+to\s+see\s+a\s+doctor\b", 0.85),
]

# Medical advice the AI should NOT give
MEDICAL_ADVICE_PATTERNS: list[tuple[str, float]] = [
    (r"\byou\s+should\s+(take|stop\s+taking)\s+\w+\s*(mg|medication|medicine|drug)\b", 0.9),
    (r"\b(increase|decrease|change)\s+your\s+(dosage|medication|prescription)\b", 0.95),
    (r"\bdiagnos(is|e|ing)\s+you\s+with\b", 0.9),
    (r"\byou\s+have\s+(cancer|diabetes|hiv|aids|heart\s+disease)\b", 0.95),
    (r"\bdon'?t\s+(worry|go)\s+.*(emergency|hospital|doctor)\b", 0.85),
]


# ==================================
# Suggested Responses
# ==================================

SUGGESTED_RESPONSES = {
    ContentCategory.PROFANITY: (
        "I'd be happy to help you, but let's keep our conversation professional. "
        "How can I assist you with your healthcare needs today?"
    ),
    ContentCategory.SEXUAL: (
        "I'm a medical receptionist assistant focused on appointment scheduling "
        "and general healthcare inquiries. How can I help you with your medical needs?"
    ),
    ContentCategory.VIOLENCE: (
        "I'm here to help with healthcare-related questions. "
        "Is there something medical I can assist you with?"
    ),
    ContentCategory.SPAM: (
        "I'm an AI medical receptionist. I can help you with appointment scheduling, "
        "clinic information, and general healthcare questions."
    ),
    ContentCategory.OFF_TOPIC: (
        "I'm specifically designed to help with healthcare-related questions "
        "like scheduling appointments, clinic hours, and medical inquiries. "
        "Is there something in that area I can help with?"
    ),
    ContentCategory.HATE_SPEECH: (
        "I'm unable to engage with that type of content. "
        "I'm here to help with your healthcare needs in a respectful manner."
    ),
    ContentCategory.HALLUCINATION: (
        "[INTERNAL: AI response contained potential hallucination - review required]"
    ),
    ContentCategory.MEDICAL_ADVICE: (
        "[INTERNAL: AI response contained specific medical advice - blocked for safety]"
    ),
}


# ==================================
# Healthcare Context Allowlist
# ==================================

# Terms that might trigger filters but are legitimate in healthcare
HEALTHCARE_ALLOWLIST = [
    # Anatomy
    r"\b(breast|vagina|penis|testicle|prostate|rectum|anus|genital)\b",
    r"\b(uterus|ovary|cervix|urethra)\b",

    # Medical procedures
    r"\b(pap\s+smear|mammogram|colonoscopy|prostate\s+exam)\b",
    r"\b(biopsy|surgery|operation|procedure)\b",

    # Conditions
    r"\b(std|sti|hiv|aids|herpes|chlamydia|gonorrhea)\b",
    r"\b(erectile\s+dysfunction|impotence)\b",
    r"\b(hemorrhoid|constipation|diarrhea)\b",

    # Symptoms
    r"\b(discharge|bleeding|pain|swelling)\b",
    r"\b(nausea|vomiting|fever)\b",
]


# ==================================
# Content Filter Class
# ==================================

class ContentFilter:
    """
    Filters inappropriate content for medical receptionist context.

    Handles both user input filtering and AI output filtering
    with healthcare-specific allowlists.

    Usage:
        filter = ContentFilter()
        result = filter.filter_input("user message here")
        if not result.is_appropriate:
            print(f"Blocked: {result.reason}")
    """

    def __init__(
        self,
        strict_mode: bool = False,
        filter_ai_output: bool = True,
        profanity_threshold: float = 0.6,
        healthcare_context: bool = True,
    ):
        """
        Initialize Content Filter.

        Args:
            strict_mode: If True, lower thresholds for all categories
            filter_ai_output: Enable hallucination/medical advice detection
            profanity_threshold: Minimum weight to flag profanity (0.0-1.0)
            healthcare_context: Apply healthcare allowlist
        """
        self.strict_mode = strict_mode
        self.filter_ai_output = filter_ai_output
        self.profanity_threshold = profanity_threshold if not strict_mode else 0.3
        self.healthcare_context = healthcare_context

        # Compile patterns
        self._profanity = [(re.compile(p, re.IGNORECASE), w) for p, w in PROFANITY_PATTERNS]
        self._sexual = [(re.compile(p, re.IGNORECASE), w) for p, w in SEXUAL_PATTERNS]
        self._violence = [(re.compile(p, re.IGNORECASE), w) for p, w in VIOLENCE_PATTERNS]
        self._spam = [(re.compile(p, re.IGNORECASE), w) for p, w in SPAM_PATTERNS]
        self._off_topic = [(re.compile(p, re.IGNORECASE), w) for p, w in OFF_TOPIC_PATTERNS]
        self._hallucination = [(re.compile(p, re.IGNORECASE), w) for p, w in HALLUCINATION_PATTERNS]
        self._medical_advice = [(re.compile(p, re.IGNORECASE), w) for p, w in MEDICAL_ADVICE_PATTERNS]
        self._healthcare_allowlist = [re.compile(p, re.IGNORECASE) for p in HEALTHCARE_ALLOWLIST]

        logger.info(
            f"ContentFilter initialized: strict_mode={strict_mode}, "
            f"healthcare_context={healthcare_context}"
        )

    def filter_input(self, text: str) -> ContentFilterResult:
        """
        Filter user input for inappropriate content.

        Args:
            text: User message to filter

        Returns:
            ContentFilterResult with filtering decision
        """
        return self._filter(text, is_ai_output=False)

    def filter_output(self, text: str) -> ContentFilterResult:
        """
        Filter AI output for hallucinations and inappropriate medical advice.

        Args:
            text: AI response to filter

        Returns:
            ContentFilterResult with filtering decision
        """
        if not self.filter_ai_output:
            return ContentFilterResult(
                is_appropriate=True,
                action=FilterAction.ALLOW,
            )
        return self._filter(text, is_ai_output=True)

    def _filter(self, text: str, is_ai_output: bool = False) -> ContentFilterResult:
        """
        Internal filtering logic.

        Args:
            text: Text to filter
            is_ai_output: Whether this is AI-generated content

        Returns:
            ContentFilterResult
        """
        if not text or not text.strip():
            return ContentFilterResult(
                is_appropriate=True,
                action=FilterAction.ALLOW,
            )

        # Check healthcare allowlist first
        is_healthcare_context = False
        if self.healthcare_context:
            for pattern in self._healthcare_allowlist:
                if pattern.search(text):
                    is_healthcare_context = True
                    break

        categories: list[ContentCategory] = []
        max_weight = 0.0
        primary_category = ContentCategory.CLEAN

        # Check each category
        checks = [
            (self._profanity, ContentCategory.PROFANITY, 0.6),
            (self._sexual, ContentCategory.SEXUAL, 0.7 if is_healthcare_context else 0.5),
            (self._violence, ContentCategory.VIOLENCE, 0.6),
            (self._spam, ContentCategory.SPAM, 0.7),
            (self._off_topic, ContentCategory.OFF_TOPIC, 0.6),
        ]

        # Add AI-specific checks
        if is_ai_output:
            checks.extend([
                (self._hallucination, ContentCategory.HALLUCINATION, 0.5),
                (self._medical_advice, ContentCategory.MEDICAL_ADVICE, 0.7),
            ])

        for patterns, category, threshold in checks:
            weight = self._check_patterns(text, patterns)

            # Apply healthcare context adjustment for sexual content
            if category == ContentCategory.SEXUAL and is_healthcare_context:
                weight *= 0.3  # Significantly reduce weight in healthcare context

            # Apply strict mode
            actual_threshold = threshold * (0.7 if self.strict_mode else 1.0)

            if weight >= actual_threshold:
                categories.append(category)
                if weight > max_weight:
                    max_weight = weight
                    primary_category = category

        # Hate speech check (special handling - always block)
        for pattern, weight in self._profanity:
            if weight >= 1.0 and pattern.search(text):
                categories.append(ContentCategory.HATE_SPEECH)
                primary_category = ContentCategory.HATE_SPEECH
                max_weight = 1.0
                break

        # Determine action
        if not categories:
            return ContentFilterResult(
                is_appropriate=True,
                action=FilterAction.ALLOW,
            )

        action = self._determine_action(primary_category, max_weight, is_ai_output)

        return ContentFilterResult(
            is_appropriate=(action == FilterAction.ALLOW),
            action=action,
            categories_detected=categories,
            confidence=round(max_weight, 3),
            reason=f"Content flagged as {primary_category.value}",
            suggested_response=SUGGESTED_RESPONSES.get(primary_category, ""),
        )

    def _check_patterns(
        self,
        text: str,
        patterns: list[tuple[re.Pattern, float]]
    ) -> float:
        """Check patterns and return maximum weight found."""
        max_weight = 0.0
        for pattern, weight in patterns:
            if pattern.search(text):
                max_weight = max(max_weight, weight)
        return max_weight

    def _determine_action(
        self,
        category: ContentCategory,
        weight: float,
        is_ai_output: bool
    ) -> FilterAction:
        """Determine appropriate action based on category and severity."""

        # Always block hate speech and high-confidence issues
        if category == ContentCategory.HATE_SPEECH:
            return FilterAction.BLOCK

        if category in [ContentCategory.HALLUCINATION, ContentCategory.MEDICAL_ADVICE]:
            return FilterAction.BLOCK if weight >= 0.7 else FilterAction.WARN

        # Threshold-based decisions
        if weight >= 0.9:
            return FilterAction.BLOCK
        elif weight >= 0.7:
            return FilterAction.REDIRECT
        elif weight >= 0.5:
            return FilterAction.WARN
        else:
            return FilterAction.ALLOW

    def is_appropriate(self, text: str) -> bool:
        """
        Quick check if content is appropriate.

        Args:
            text: Text to check

        Returns:
            True if appropriate, False otherwise
        """
        return self.filter_input(text).is_appropriate

    def get_action(self, text: str) -> FilterAction:
        """
        Get recommended action for content.

        Args:
            text: Text to check

        Returns:
            FilterAction enum value
        """
        return self.filter_input(text).action


# ==================================
# Singleton & Convenience Functions
# ==================================

_filter_instance: Optional[ContentFilter] = None


def get_filter(
    strict_mode: bool = False,
    filter_ai_output: bool = True,
    healthcare_context: bool = True,
) -> ContentFilter:
    """
    Get or create singleton ContentFilter instance.

    Args:
        strict_mode: Enable strict filtering
        filter_ai_output: Enable AI output filtering
        healthcare_context: Apply healthcare allowlist

    Returns:
        ContentFilter instance
    """
    global _filter_instance
    if _filter_instance is None:
        _filter_instance = ContentFilter(
            strict_mode=strict_mode,
            filter_ai_output=filter_ai_output,
            healthcare_context=healthcare_context,
        )
    return _filter_instance


def filter_content(text: str) -> ContentFilterResult:
    """
    Convenience function to filter user content.

    Args:
        text: User message to filter

    Returns:
        ContentFilterResult
    """
    return get_filter().filter_input(text)


def filter_ai_response(text: str) -> ContentFilterResult:
    """
    Convenience function to filter AI response.

    Args:
        text: AI response to filter

    Returns:
        ContentFilterResult
    """
    return get_filter().filter_output(text)


def is_appropriate(text: str) -> bool:
    """
    Convenience function to check if content is appropriate.

    Args:
        text: Text to check

    Returns:
        True if appropriate
    """
    return get_filter().is_appropriate(text)
