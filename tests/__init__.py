"""
Safety Pipeline Integration Tests

This package contains integration tests for the AI Receptionist safety pipeline.

IMPORTANT: These tests require Python 3.9-3.12 due to dependencies:
- spaCy and Presidio use pydantic v1 which doesn't support Python 3.14+

Running Tests:
    # Run all tests with pytest
    pytest tests/test_safety_integration.py -v

    # Run standalone
    python tests/test_safety_integration.py

    # Run specific test
    pytest tests/test_safety_integration.py::test_crisis_detection -v

Test Coverage:
    - Safe input processing
    - PII detection and redaction
    - Crisis detection and escalation
    - Prompt injection detection
    - Content filtering
    - AI output filtering
    - Consent management
    - Patient verification
    - Audit logging
    - Full pipeline integration
"""
