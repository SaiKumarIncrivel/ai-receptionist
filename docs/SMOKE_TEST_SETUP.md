# E2E Smoke Test Setup

This document explains how to run the E2E smoke tests for the AI Receptionist v2 architecture.

## Overview

The smoke tests exercise the full receptionist behavior by calling the chat API endpoint. They test 8 key scenarios:

1. **Health Check** - Service is up and responding
2. **Greeting** - Conversation agent handles greetings warmly
3. **Booking Flow** - Full scheduling flow with calendar tools
4. **FAQ** - Knowledge-based responses
5. **Crisis** - Deterministic 988 Lifeline response
6. **Out-of-Scope** - Polite redirect for off-topic messages
7. **Handoff** - Human transfer requests
8. **Goodbye** - Friendly farewell handling

## Prerequisites

### Required Services

| Service | Default URL | Required For |
|---------|-------------|--------------|
| AI Receptionist | http://localhost:8000 | All tests |
| Calendar Agent | http://localhost:8001 | Booking tests |
| Redis | localhost:6379 | Session storage |

### Python Dependencies

```bash
pip install pytest httpx
```

Or if using the project's requirements:
```bash
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

## Running the Tests

### Quick Start

```bash
# Run all smoke tests
pytest tests/e2e/smoke_test_e2e.py -v

# Run a specific test category
pytest tests/e2e/smoke_test_e2e.py -v -k "greeting"
pytest tests/e2e/smoke_test_e2e.py -v -k "crisis"
pytest tests/e2e/smoke_test_e2e.py -v -k "booking"
```

### With Custom Configuration

```bash
# Custom receptionist URL
RECEPTIONIST_URL=http://192.168.1.10:8000 pytest tests/e2e/smoke_test_e2e.py -v

# Custom calendar agent URL
CALENDAR_AGENT_URL=http://192.168.1.10:8001 pytest tests/e2e/smoke_test_e2e.py -v

# Custom tenant ID
E2E_TENANT_ID=my-clinic pytest tests/e2e/smoke_test_e2e.py -v

# Custom timeout (seconds)
E2E_TIMEOUT=60 pytest tests/e2e/smoke_test_e2e.py -v
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `RECEPTIONIST_URL` | http://localhost:8000 | AI Receptionist base URL |
| `CALENDAR_AGENT_URL` | http://localhost:8001 | Calendar Agent base URL |
| `E2E_TENANT_ID` | test-clinic | Tenant ID for X-Tenant-ID header |
| `E2E_TIMEOUT` | 30 | Request timeout in seconds |

## Test Scenarios

### 1. Health Check (`TestHealthCheck`)

Verifies the service is up:
- `/health` endpoint returns 200
- `/chat` endpoint accepts requests

### 2. Greeting (`TestGreeting`)

Tests conversation agent greeting handling:
- "Hi", "Hello", "Good morning" get warm responses
- Session persists across greetings

### 3. Booking Flow (`TestBookingFlow`)

Tests full scheduling with Calendar Agent:
- Booking intent detection
- Provider-specific requests
- Cancellation requests

**Note:** Requires Calendar Agent to be running.

### 4. FAQ (`TestFAQ`)

Tests knowledge-based responses:
- Office hours questions
- Insurance questions
- Location questions
- Doctor information

### 5. Crisis (`TestCrisis`)

Tests deterministic 988 Lifeline response:
- "I want to hurt myself" → 988 Lifeline info
- Does NOT route to scheduling
- Empathetic, not dismissive

**Critical:** This is a safety-critical test. The response must always include 988.

### 6. Out-of-Scope (`TestOutOfScope`)

Tests polite redirect for off-topic:
- Weather questions
- Math questions
- Jokes
- Redirects to clinic-related help

### 7. Handoff (`TestHandoff`)

Tests human transfer requests:
- "I want to speak to a human"
- "Transfer me to the front desk"
- Acknowledges and offers to connect

### 8. Goodbye (`TestGoodbye`)

Tests farewell handling:
- "Bye", "Goodbye", "Thanks, bye!"
- Friendly closing response

## Troubleshooting

### Tests Failing to Connect

```
httpx.ConnectError: All connection attempts failed
```

**Solution:** Ensure the AI Receptionist is running:
```bash
# Start the receptionist
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Booking Tests Skipped

```
SKIPPED [1] tests/e2e/smoke_test_e2e.py: Calendar Agent URL not configured
```

**Solution:** Set the Calendar Agent URL:
```bash
CALENDAR_AGENT_URL=http://localhost:8001 pytest tests/e2e/smoke_test_e2e.py -v
```

### Timeout Errors

```
httpx.ReadTimeout: timed out
```

**Solution:** Increase the timeout:
```bash
E2E_TIMEOUT=60 pytest tests/e2e/smoke_test_e2e.py -v
```

### Session/Redis Errors

Ensure Redis is running:
```bash
# Check Redis
redis-cli ping

# Start Redis (if using Docker)
docker run -d -p 6379:6379 redis
```

### Missing X-Tenant-ID

```
400 Bad Request: X-Tenant-ID header is required
```

The tests automatically include this header. If you're testing manually:
```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -H "X-Tenant-ID: test-clinic" \
  -d '{"message": "Hello"}'
```

## Running with Docker

If running services in Docker:

```bash
# Assuming services are in a docker-compose network
RECEPTIONIST_URL=http://ai-receptionist:8000 \
CALENDAR_AGENT_URL=http://calendar-agent:8001 \
pytest tests/e2e/smoke_test_e2e.py -v
```

## CI/CD Integration

Example GitHub Actions workflow:

```yaml
name: E2E Smoke Tests

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  smoke-test:
    runs-on: ubuntu-latest

    services:
      redis:
        image: redis
        ports:
          - 6379:6379

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install -r requirements-dev.txt

      - name: Start AI Receptionist
        run: |
          uvicorn app.main:app --host 0.0.0.0 --port 8000 &
          sleep 5

      - name: Run smoke tests
        run: pytest tests/e2e/smoke_test_e2e.py -v
        env:
          RECEPTIONIST_URL: http://localhost:8000
          E2E_TENANT_ID: test-clinic
```

## Extending the Tests

To add new test scenarios:

1. Create a new test class in `smoke_test_e2e.py`
2. Use the `client` fixture for single-turn tests
3. Use `client_with_session` for multi-turn conversations
4. Assert on `response["state"]` and `response["message"]`

Example:

```python
class TestNewFeature:
    """Test new feature X."""

    def test_feature_works(self, client):
        response = client.send("Trigger new feature")

        assert response["state"] in ("expected_state", "idle")
        assert "expected text" in response["message"].lower()
```
