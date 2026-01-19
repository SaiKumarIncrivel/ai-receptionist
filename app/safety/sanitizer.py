"""
Input Sanitization Module

Cleans and validates user input to prevent:
- XSS attacks (HTML/script injection)
- Prompt injection attacks
- Buffer overflow (excessive length)
- Control character injection
"""

import html
import logging
import re
from typing import Optional

from app.safety.models import SanitizationResult

logger = logging.getLogger(__name__)


# ==================================
# Configuration
# ==================================

# Maximum allowed input length (characters)
MAX_INPUT_LENGTH = 10000

# Minimum length to process (skip empty/trivial input)
MIN_INPUT_LENGTH = 1

# Prompt injection patterns to detect
PROMPT_INJECTION_PATTERNS = [
    # Direct instruction override
    r"ignore\s+(all\s+)?(previous|prior|above)\s+(instructions?|prompts?|rules?)",
    r"disregard\s+(all\s+)?(previous|prior|above)\s+(instructions?|prompts?|rules?)",
    r"forget\s+(all\s+)?(previous|prior|above)\s+(instructions?|prompts?|rules?)",

    # Role manipulation
    r"you\s+are\s+now\s+(a|an)\s+",
    r"pretend\s+(you're|you\s+are|to\s+be)\s+",
    r"act\s+as\s+(a|an|if)\s+",
    r"roleplay\s+as\s+",
    r"switch\s+to\s+.+\s+mode",

    # System prompt extraction
    r"(show|reveal|display|print|output)\s+(me\s+)?(your|the)\s+(system\s+)?(prompt|instructions?)",
    r"what\s+(are|is)\s+your\s+(system\s+)?(prompt|instructions?)",
    r"repeat\s+(your|the)\s+(system\s+)?(prompt|instructions?)",

    # Jailbreak attempts
    r"jailbreak",
    r"DAN\s+mode",
    r"developer\s+mode",
    r"bypass\s+(your\s+)?(restrictions?|filters?|rules?)",

    # Code execution attempts
    r"execute\s+(this\s+)?(code|command|script)",
    r"run\s+(this\s+)?(code|command|script)",
    r"eval\s*\(",
    r"exec\s*\(",

    # Data exfiltration
    r"(send|transmit|post|upload)\s+(to|data\s+to)\s+",
    r"webhook",
    r"curl\s+",
    r"fetch\s*\(",
]

# HTML/Script tags to remove
HTML_TAG_PATTERN = re.compile(r"<[^>]+>", re.IGNORECASE)
SCRIPT_PATTERN = re.compile(r"<script[^>]*>.*?</script>", re.IGNORECASE | re.DOTALL)
STYLE_PATTERN = re.compile(r"<style[^>]*>.*?</style>", re.IGNORECASE | re.DOTALL)

# Control characters (except newline, tab, carriage return)
CONTROL_CHAR_PATTERN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# Multiple whitespace normalization
MULTIPLE_SPACES_PATTERN = re.compile(r" {2,}")
MULTIPLE_NEWLINES_PATTERN = re.compile(r"\n{3,}")


# ==================================
# Sanitizer Class
# ==================================

class Sanitizer:
    """
    Input sanitization service.

    Cleans user input and detects potential security threats
    like prompt injection attacks.

    Usage:
        sanitizer = Sanitizer()
        result = sanitizer.sanitize("Hello <script>alert('xss')</script>")
        print(result.sanitized_text)  # "Hello"
        print(result.is_safe)  # True
    """

    def __init__(
        self,
        max_length: int = MAX_INPUT_LENGTH,
        strip_html: bool = True,
        detect_injection: bool = True,
        normalize_whitespace: bool = True,
    ):
        """
        Initialize Sanitizer.

        Args:
            max_length: Maximum allowed input length
            strip_html: Whether to remove HTML tags
            detect_injection: Whether to check for prompt injection
            normalize_whitespace: Whether to normalize whitespace
        """
        self.max_length = max_length
        self.strip_html = strip_html
        self.detect_injection = detect_injection
        self.normalize_whitespace = normalize_whitespace

        # Compile injection patterns for efficiency
        self._injection_patterns = [
            re.compile(pattern, re.IGNORECASE)
            for pattern in PROMPT_INJECTION_PATTERNS
        ]

    def sanitize(self, text: str) -> SanitizationResult:
        """
        Sanitize input text.

        Args:
            text: Raw input text

        Returns:
            SanitizationResult with sanitized text and metadata
        """
        if text is None:
            text = ""

        original_text = text
        changes_made = []
        prompt_injection_detected = False

        # Step 1: Check length and truncate if needed
        if len(text) > self.max_length:
            text = text[:self.max_length]
            changes_made.append(f"truncated_from_{len(original_text)}_to_{self.max_length}")
            logger.warning(f"Input truncated from {len(original_text)} to {self.max_length} chars")

        # Step 2: Remove control characters
        text, control_removed = self._remove_control_chars(text)
        if control_removed:
            changes_made.append("removed_control_characters")

        # Step 3: Strip HTML/script tags
        if self.strip_html:
            text, html_removed = self._strip_html(text)
            if html_removed:
                changes_made.append("stripped_html_tags")

        # Step 4: Decode HTML entities
        decoded_text = html.unescape(text)
        if decoded_text != text:
            text = decoded_text
            changes_made.append("decoded_html_entities")

        # Step 5: Normalize whitespace
        if self.normalize_whitespace:
            text, ws_normalized = self._normalize_whitespace(text)
            if ws_normalized:
                changes_made.append("normalized_whitespace")

        # Step 6: Strip leading/trailing whitespace
        stripped_text = text.strip()
        if stripped_text != text:
            text = stripped_text
            changes_made.append("stripped_outer_whitespace")

        # Step 7: Detect prompt injection (after cleaning)
        if self.detect_injection:
            injection_found, injection_patterns = self._detect_prompt_injection(text)
            if injection_found:
                prompt_injection_detected = True
                changes_made.append(f"prompt_injection_detected: {injection_patterns}")
                logger.warning(f"Prompt injection detected: {injection_patterns}")

        return SanitizationResult(
            original_text=original_text,
            sanitized_text=text,
            changes_made=changes_made,
            prompt_injection_detected=prompt_injection_detected,
            is_safe=not prompt_injection_detected,
        )

    def _remove_control_chars(self, text: str) -> tuple[str, bool]:
        """Remove control characters except newline, tab, CR."""
        cleaned = CONTROL_CHAR_PATTERN.sub("", text)
        return cleaned, cleaned != text

    def _strip_html(self, text: str) -> tuple[str, bool]:
        """Remove HTML and script tags."""
        original = text

        # Remove script tags and content
        text = SCRIPT_PATTERN.sub("", text)

        # Remove style tags and content
        text = STYLE_PATTERN.sub("", text)

        # Remove remaining HTML tags
        text = HTML_TAG_PATTERN.sub("", text)

        return text, text != original

    def _normalize_whitespace(self, text: str) -> tuple[str, bool]:
        """Normalize multiple spaces and newlines."""
        original = text

        # Replace multiple spaces with single space
        text = MULTIPLE_SPACES_PATTERN.sub(" ", text)

        # Replace 3+ newlines with 2 newlines
        text = MULTIPLE_NEWLINES_PATTERN.sub("\n\n", text)

        return text, text != original

    def _detect_prompt_injection(self, text: str) -> tuple[bool, list[str]]:
        """
        Detect potential prompt injection attacks.

        Returns:
            Tuple of (detected: bool, matched_patterns: list[str])
        """
        matched_patterns = []

        for pattern in self._injection_patterns:
            if pattern.search(text):
                # Get the pattern string for logging (first 50 chars)
                pattern_str = pattern.pattern[:50]
                matched_patterns.append(pattern_str)

        return len(matched_patterns) > 0, matched_patterns

    def is_safe(self, text: str) -> bool:
        """
        Quick check if text is safe (no prompt injection).

        Args:
            text: Text to check

        Returns:
            True if safe, False if prompt injection detected
        """
        result = self.sanitize(text)
        return result.is_safe


# ==================================
# Module-level singleton instance
# ==================================

_sanitizer: Optional[Sanitizer] = None


def get_sanitizer() -> Sanitizer:
    """
    Get the singleton Sanitizer instance.

    Returns:
        Sanitizer instance
    """
    global _sanitizer
    if _sanitizer is None:
        _sanitizer = Sanitizer()
    return _sanitizer


def sanitize_input(text: str) -> SanitizationResult:
    """
    Convenience function to sanitize input text.

    Args:
        text: Text to sanitize

    Returns:
        SanitizationResult
    """
    return get_sanitizer().sanitize(text)


def is_input_safe(text: str) -> bool:
    """
    Convenience function to check if input is safe.

    Args:
        text: Text to check

    Returns:
        True if safe, False if potentially malicious
    """
    return get_sanitizer().is_safe(text)


def clean_input(text: str) -> str:
    """
    Convenience function to get cleaned text.

    Args:
        text: Text to clean

    Returns:
        Sanitized text string
    """
    result = sanitize_input(text)
    return result.sanitized_text
