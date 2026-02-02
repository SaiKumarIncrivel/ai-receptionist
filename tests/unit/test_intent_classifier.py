"""Tests for LLM intent classification."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from dataclasses import dataclass

from app.core.intelligence.intent.types import Intent, ConfirmationType, IntentResult
from app.core.intelligence.intent.classifier import IntentClassifier


@dataclass
class MockClaudeResponse:
    """Mock Claude response."""
    content: str
    model: str = "claude-3-5-haiku-20241022"
    input_tokens: int = 100
    output_tokens: int = 50
    stop_reason: str = "end_turn"
    latency_ms: float = 50.0


class TestIntentClassifier:
    """Test LLM-based intent classifier."""

    @pytest.fixture
    def mock_claude_client(self):
        """Mock Claude client."""
        client = AsyncMock()
        return client

    @pytest.fixture
    def classifier(self, mock_claude_client):
        """Create classifier with mock client."""
        return IntentClassifier(claude_client=mock_claude_client)

    def _mock_response(self, mock_client, json_response: str):
        """Helper to mock Claude response."""
        mock_client.generate.return_value = MockClaudeResponse(content=json_response)

    @pytest.mark.asyncio
    async def test_classify_scheduling(self, classifier, mock_claude_client):
        """Test scheduling intent classification."""
        self._mock_response(
            mock_claude_client,
            '''
            {
                "intent": "scheduling",
                "confidence": 0.95,
                "confirmation_type": null,
                "reason": "back pain",
                "urgency": "medium"
            }
            ''',
        )

        result = await classifier.classify("My back is killing me, need to see someone")

        assert result.intent == Intent.SCHEDULING
        assert result.confidence >= 0.9
        assert result.reason == "back pain"

    @pytest.mark.asyncio
    async def test_classify_confirmation_yes(self, classifier, mock_claude_client):
        """Test yes confirmation."""
        self._mock_response(
            mock_claude_client,
            '''
            {
                "intent": "confirmation",
                "confidence": 0.98,
                "confirmation_type": "yes",
                "reason": null,
                "urgency": null
            }
            ''',
        )

        result = await classifier.classify("Yes, book it")

        assert result.intent == Intent.CONFIRMATION
        assert result.confirmation_type == ConfirmationType.YES

    @pytest.mark.asyncio
    async def test_classify_confirmation_no(self, classifier, mock_claude_client):
        """Test no confirmation."""
        self._mock_response(
            mock_claude_client,
            '''
            {
                "intent": "confirmation",
                "confidence": 0.95,
                "confirmation_type": "no",
                "reason": null,
                "urgency": null
            }
            ''',
        )

        result = await classifier.classify("No, that's wrong")

        assert result.intent == Intent.CONFIRMATION
        assert result.confirmation_type == ConfirmationType.NO

    @pytest.mark.asyncio
    async def test_classify_cancellation(self, classifier, mock_claude_client):
        """Test cancellation intent."""
        self._mock_response(
            mock_claude_client,
            '''
            {
                "intent": "cancellation",
                "confidence": 0.92,
                "confirmation_type": null,
                "reason": null,
                "urgency": null
            }
            ''',
        )

        result = await classifier.classify("I need to cancel my appointment")

        assert result.intent == Intent.CANCELLATION
        assert result.confidence >= 0.9

    @pytest.mark.asyncio
    async def test_classify_with_context(self, classifier, mock_claude_client):
        """Test classification uses session context."""
        self._mock_response(
            mock_claude_client,
            '''
            {
                "intent": "provide_info",
                "confidence": 0.92,
                "confirmation_type": null,
                "reason": null,
                "urgency": null
            }
            ''',
        )

        context = {
            "state": "collect_date",
            "collected": {"provider_name": "Dr. Smith"},
            "last_bot_question": "What date works for you?",
        }

        result = await classifier.classify("Next Tuesday", session_context=context)

        # Verify context was included in the prompt
        call_args = mock_claude_client.generate.call_args
        prompt = call_args.kwargs.get("prompt", "")
        assert "Dr. Smith" in prompt or "collect_date" in prompt

    @pytest.mark.asyncio
    async def test_classify_handoff(self, classifier, mock_claude_client):
        """Test handoff intent."""
        self._mock_response(
            mock_claude_client,
            '''
            {
                "intent": "handoff",
                "confidence": 0.99,
                "confirmation_type": null,
                "reason": null,
                "urgency": null
            }
            ''',
        )

        result = await classifier.classify("Let me talk to a real person")

        assert result.intent == Intent.HANDOFF

    @pytest.mark.asyncio
    async def test_classify_greeting(self, classifier, mock_claude_client):
        """Test greeting intent."""
        self._mock_response(
            mock_claude_client,
            '''
            {
                "intent": "greeting",
                "confidence": 0.99,
                "confirmation_type": null,
                "reason": null,
                "urgency": null
            }
            ''',
        )

        result = await classifier.classify("Hello!")

        assert result.intent == Intent.GREETING

    @pytest.mark.asyncio
    async def test_classify_out_of_scope(self, classifier, mock_claude_client):
        """Test out of scope intent."""
        self._mock_response(
            mock_claude_client,
            '''
            {
                "intent": "out_of_scope",
                "confidence": 0.95,
                "confirmation_type": null,
                "reason": null,
                "urgency": null
            }
            ''',
        )

        result = await classifier.classify("What's the weather today?")

        assert result.intent == Intent.OUT_OF_SCOPE

    @pytest.mark.asyncio
    async def test_empty_message(self, classifier):
        """Test empty message returns unknown."""
        result = await classifier.classify("")

        assert result.intent == Intent.UNKNOWN
        assert result.confidence == 1.0

    @pytest.mark.asyncio
    async def test_fallback_on_low_confidence(self, classifier, mock_claude_client):
        """Test fallback to Sonnet on low confidence."""
        # First call returns low confidence
        mock_claude_client.generate.side_effect = [
            MockClaudeResponse(
                content='{"intent": "unknown", "confidence": 0.4, "confirmation_type": null, "reason": null, "urgency": null}'
            ),
            MockClaudeResponse(
                content='{"intent": "scheduling", "confidence": 0.85, "confirmation_type": null, "reason": null, "urgency": null}',
                model="claude-sonnet-4-20250514",
            ),
        ]

        result = await classifier.classify("maybe I should see someone")

        assert result.fallback_used is True
        assert mock_claude_client.generate.call_count == 2


class TestIntentResult:
    """Test IntentResult model."""

    def test_to_dict(self):
        """Test conversion to dictionary."""
        result = IntentResult(
            intent=Intent.SCHEDULING,
            confidence=0.95,
            reason="checkup",
            urgency="low",
        )

        d = result.to_dict()

        assert d["intent"] == "scheduling"
        assert d["confidence"] == 0.95
        assert d["reason"] == "checkup"

    def test_is_high_confidence(self):
        """Test high confidence check."""
        high = IntentResult(intent=Intent.SCHEDULING, confidence=0.9)
        low = IntentResult(intent=Intent.SCHEDULING, confidence=0.5)

        assert high.is_high_confidence is True
        assert low.is_high_confidence is False

    def test_is_booking_related(self):
        """Test booking related check."""
        scheduling = IntentResult(intent=Intent.SCHEDULING, confidence=0.9)
        greeting = IntentResult(intent=Intent.GREETING, confidence=0.9)

        assert scheduling.is_booking_related is True
        assert greeting.is_booking_related is False
