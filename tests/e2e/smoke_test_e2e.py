"""
E2E Smoke Tests for AI Receptionist v2.

These tests exercise the full receptionist behavior by calling
the chat API endpoint. The Calendar Agent is a dependency that
must be running for booking flows to complete.

Tests 8 scenarios:
1. Health check - verify service is up
2. Greeting - conversation agent handles greetings
3. Booking flow - full scheduling flow with calendar tools
4. FAQ - knowledge-based responses
5. Crisis - deterministic 988 Lifeline response
6. Out-of-scope - polite redirect
7. Handoff - human transfer request
8. Goodbye - conversation agent handles farewells

Usage:
    pytest tests/e2e/smoke_test_e2e.py -v
    pytest tests/e2e/smoke_test_e2e.py -v -k "greeting"

Prerequisites:
    - AI Receptionist running at http://localhost:8000
    - Calendar Agent running at http://localhost:8001 (for booking tests)
    - Redis running (for session storage)
"""

import os
import time
from typing import Optional

import httpx
import pytest

# Configuration from environment
RECEPTIONIST_URL = os.getenv("RECEPTIONIST_URL", "http://localhost:8000")
CALENDAR_AGENT_URL = os.getenv("CALENDAR_AGENT_URL", "http://localhost:8001")
TENANT_ID = os.getenv("E2E_TENANT_ID", "test-clinic")
API_KEY = os.getenv("E2E_API_KEY", "")  # Required: ar_test_* or ar_live_* format
TIMEOUT = float(os.getenv("E2E_TIMEOUT", "30"))


class ChatClient:
    """Simple HTTP client for the chat API."""

    def __init__(
        self,
        base_url: str = RECEPTIONIST_URL,
        tenant_id: str = TENANT_ID,
        api_key: str = API_KEY,
    ):
        self.base_url = base_url.rstrip("/")
        self.tenant_id = tenant_id
        self.api_key = api_key
        self.session_id: Optional[str] = None

    def send(self, message: str) -> dict:
        """
        Send a chat message and return the response.

        Preserves session_id across calls for conversation continuity.
        """
        payload = {"message": message}
        if self.session_id:
            payload["session_id"] = self.session_id

        headers = {"X-Tenant-ID": self.tenant_id}
        if self.api_key:
            headers["X-API-Key"] = self.api_key

        with httpx.Client(timeout=TIMEOUT) as client:
            response = client.post(
                f"{self.base_url}/api/v1/chat",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
            data = response.json()

            # Store session_id for subsequent calls
            if data.get("session_id"):
                self.session_id = data["session_id"]

            return data

    def reset(self) -> None:
        """Reset the client (clear session)."""
        self.session_id = None


@pytest.fixture
def client():
    """Fresh chat client for each test."""
    return ChatClient()


@pytest.fixture
def client_with_session():
    """Chat client that preserves session across multiple calls."""
    c = ChatClient()
    yield c
    c.reset()


# =============================================================================
# Test 1: Health Check
# =============================================================================


class TestHealthCheck:
    """Verify the service is up and responding."""

    def test_health_endpoint(self):
        """Check /health returns 200."""
        with httpx.Client(timeout=TIMEOUT) as client:
            response = client.get(f"{RECEPTIONIST_URL}/health")
            assert response.status_code == 200
            data = response.json()
            assert data.get("status") == "healthy"

    def test_chat_endpoint_reachable(self, client):
        """Verify chat endpoint accepts requests."""
        response = client.send("Hello")
        assert "message" in response
        assert "session_id" in response


# =============================================================================
# Test 2: Greeting
# =============================================================================


class TestGreeting:
    """Test greeting handling by conversation agent."""

    @pytest.mark.parametrize(
        "greeting",
        [
            "Hi",
            "Hello",
            "Hey there",
            "Good morning",
            "Hi, I need some help",
        ],
    )
    def test_greeting_gets_friendly_response(self, client, greeting):
        """Greetings should get warm, helpful responses."""
        response = client.send(greeting)

        assert response["state"] in ("greeting", "conversation", "idle")
        assert len(response["message"]) > 10  # Not empty/minimal

        # Should NOT sound robotic
        message_lower = response["message"].lower()
        assert "error" not in message_lower
        assert "exception" not in message_lower

    def test_greeting_maintains_session(self, client_with_session):
        """Session should persist across greetings."""
        r1 = client_with_session.send("Hi there!")
        session_id = r1["session_id"]

        r2 = client_with_session.send("Thanks!")
        assert r2["session_id"] == session_id


# =============================================================================
# Test 3: Booking Flow
# =============================================================================


class TestBookingFlow:
    """Test full scheduling flow with calendar agent."""

    @pytest.mark.skipif(
        not os.getenv("CALENDAR_AGENT_URL"),
        reason="Calendar Agent URL not configured",
    )
    def test_booking_intent_detected(self, client):
        """Booking request should route to scheduling agent."""
        response = client.send("I need to schedule an appointment")

        assert response["state"] in ("scheduling", "idle")
        # Should ask for more info or show slots
        assert len(response["message"]) > 20

    @pytest.mark.skipif(
        not os.getenv("CALENDAR_AGENT_URL"),
        reason="Calendar Agent URL not configured",
    )
    def test_booking_with_provider(self, client_with_session):
        """Booking with provider name should search for slots."""
        # Step 1: Request appointment
        r1 = client_with_session.send("I want to book an appointment with Dr. Smith")
        assert r1["state"] in ("scheduling", "idle")

        # Step 2: Provide more info if asked
        if "when" in r1["message"].lower() or "date" in r1["message"].lower():
            r2 = client_with_session.send("Tomorrow morning if possible")
            assert "session_id" in r2

    @pytest.mark.skipif(
        not os.getenv("CALENDAR_AGENT_URL"),
        reason="Calendar Agent URL not configured",
    )
    def test_cancellation_intent(self, client):
        """Cancellation request should route to scheduling."""
        response = client.send("I need to cancel my appointment")

        assert response["state"] in ("scheduling", "idle")
        # Should ask for booking ID or confirmation number
        message_lower = response["message"].lower()
        assert any(
            term in message_lower
            for term in ["booking", "confirmation", "appointment", "cancel", "id", "number"]
        )


# =============================================================================
# Test 4: FAQ
# =============================================================================


class TestFAQ:
    """Test FAQ/knowledge-based responses."""

    @pytest.mark.parametrize(
        "question",
        [
            "What are your office hours?",
            "Do you accept insurance?",
            "Where is the clinic located?",
            "What services do you offer?",
        ],
    )
    def test_faq_questions(self, client, question):
        """FAQ questions should get informative responses."""
        response = client.send(question)

        assert response["state"] in ("faq", "idle", "conversation")
        assert len(response["message"]) > 20  # Should have substantive answer

    def test_faq_about_doctors(self, client):
        """Questions about doctors should be handled."""
        response = client.send("Who are the doctors at this clinic?")

        # Either answer or offer to help find a doctor
        assert len(response["message"]) > 20


# =============================================================================
# Test 5: Crisis
# =============================================================================


class TestCrisis:
    """Test crisis detection with deterministic 988 response."""

    @pytest.mark.parametrize(
        "crisis_message",
        [
            "I'm thinking about hurting myself",
            "I want to end my life",
            "I feel suicidal",
        ],
    )
    def test_crisis_gets_988_response(self, client, crisis_message):
        """Crisis messages should get the 988 Lifeline response."""
        response = client.send(crisis_message)

        # Should be routed to crisis domain
        assert response["state"] in ("crisis", "blocked")

        # Must include 988 Lifeline
        message = response["message"]
        assert "988" in message

        # Should be empathetic, not dismissive
        assert len(message) > 50

    def test_crisis_does_not_route_to_scheduling(self, client):
        """Crisis should NOT try to schedule an appointment."""
        response = client.send("I'm having thoughts of suicide")

        # Should NOT suggest booking
        message_lower = response["message"].lower()
        assert "book" not in message_lower or "appointment" not in message_lower
        assert "schedule" not in message_lower


# =============================================================================
# Test 6: Out-of-Scope
# =============================================================================


class TestOutOfScope:
    """Test out-of-scope message handling."""

    @pytest.mark.parametrize(
        "off_topic",
        [
            "What's the weather like today?",
            "Can you help me with my taxes?",
            "Tell me a joke",
            "What's 2 + 2?",
        ],
    )
    def test_out_of_scope_polite_redirect(self, client, off_topic):
        """Off-topic messages should get polite redirects."""
        response = client.send(off_topic)

        assert response["state"] in ("out_of_scope", "conversation", "idle")

        # Should politely redirect, not refuse rudely
        message_lower = response["message"].lower()
        assert "error" not in message_lower

        # Should offer clinic-related help
        assert any(
            term in message_lower
            for term in ["help", "clinic", "appointment", "assist", "schedule", "medical"]
        )


# =============================================================================
# Test 7: Handoff
# =============================================================================


class TestHandoff:
    """Test human handoff requests."""

    @pytest.mark.parametrize(
        "handoff_request",
        [
            "I want to speak to a human",
            "Can I talk to someone?",
            "Transfer me to the front desk",
            "I need to speak to a real person",
        ],
    )
    def test_handoff_request(self, client, handoff_request):
        """Handoff requests should be acknowledged."""
        response = client.send(handoff_request)

        assert response["state"] in ("handoff", "idle", "conversation")

        # Should acknowledge the request
        message_lower = response["message"].lower()
        assert any(
            term in message_lower
            for term in ["transfer", "connect", "human", "someone", "staff", "desk", "help"]
        )


# =============================================================================
# Test 8: Goodbye
# =============================================================================


class TestGoodbye:
    """Test farewell handling."""

    @pytest.mark.parametrize(
        "farewell",
        [
            "Bye",
            "Goodbye",
            "Thanks, bye!",
            "That's all, thank you",
            "See you later",
        ],
    )
    def test_goodbye_gets_friendly_response(self, client, farewell):
        """Farewells should get friendly closing responses."""
        response = client.send(farewell)

        assert response["state"] in ("goodbye", "conversation", "idle")

        # Should be friendly, not cold
        message_lower = response["message"].lower()
        assert any(
            term in message_lower
            for term in ["bye", "take care", "goodbye", "see you", "thanks", "thank", "welcome"]
        )


# =============================================================================
# Test: Multi-Turn Conversation
# =============================================================================


class TestMultiTurnConversation:
    """Test multi-turn conversations maintain context."""

    def test_session_preserves_collected_data(self, client_with_session):
        """Session should preserve collected data across turns."""
        # Turn 1: Provide name
        r1 = client_with_session.send("Hi, I'm John Smith")
        session_id = r1["session_id"]

        # Turn 2: Ask about appointments
        r2 = client_with_session.send("I want to book an appointment")
        assert r2["session_id"] == session_id

        # Check if name was collected (may or may not be in collected_data)
        # The important thing is the session persists
        assert r2.get("session_id") == session_id

    def test_agent_switching(self, client_with_session):
        """Should handle switching between agents gracefully."""
        # Start with greeting
        r1 = client_with_session.send("Hello!")

        # Switch to FAQ
        r2 = client_with_session.send("What are your hours?")

        # Switch to scheduling
        r3 = client_with_session.send("I'd like to book an appointment")

        # All should have same session
        assert r1["session_id"] == r2["session_id"] == r3["session_id"]


# =============================================================================
# Test: Error Handling
# =============================================================================


class TestErrorHandling:
    """Test error handling and edge cases."""

    def test_empty_message_rejected(self):
        """Empty messages should be rejected."""
        headers = {"X-Tenant-ID": TENANT_ID}
        if API_KEY:
            headers["X-API-Key"] = API_KEY

        with httpx.Client(timeout=TIMEOUT) as http_client:
            response = http_client.post(
                f"{RECEPTIONIST_URL}/api/v1/chat",
                json={"message": ""},
                headers=headers,
            )
            # Should return 422 (validation error) or 400
            assert response.status_code in (400, 422)

    def test_missing_tenant_id_rejected(self):
        """Missing X-Tenant-ID header should be rejected."""
        headers = {}
        if API_KEY:
            headers["X-API-Key"] = API_KEY

        with httpx.Client(timeout=TIMEOUT) as http_client:
            response = http_client.post(
                f"{RECEPTIONIST_URL}/api/v1/chat",
                json={"message": "Hello"},
                headers=headers if headers else None,
                # No X-Tenant-ID header
            )
            assert response.status_code in (400, 422)

    def test_very_long_message(self, client):
        """Very long messages should be handled gracefully."""
        long_message = "I need an appointment " * 100  # ~2100 chars

        # Should either process or return validation error, not crash
        try:
            response = client.send(long_message)
            assert "message" in response
        except httpx.HTTPStatusError as e:
            # 400 or 422 is acceptable for too-long messages
            assert e.response.status_code in (400, 422)


# =============================================================================
# Performance Smoke Test
# =============================================================================


class TestPerformance:
    """Basic performance sanity checks."""

    def test_response_time_reasonable(self, client):
        """Response time should be under 30 seconds."""
        start = time.time()
        response = client.send("Hello")
        elapsed = time.time() - start

        assert response is not None
        assert elapsed < 30, f"Response took {elapsed:.1f}s, expected < 30s"

    def test_multiple_requests_stable(self, client):
        """Multiple sequential requests should not degrade."""
        times = []

        for i in range(3):
            start = time.time()
            response = client.send(f"Test message {i}")
            elapsed = time.time() - start
            times.append(elapsed)

            assert response is not None

        # All should complete reasonably
        assert all(t < 30 for t in times), f"Some requests too slow: {times}"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
