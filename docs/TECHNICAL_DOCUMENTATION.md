# AI Receptionist - Technical Documentation

**Version:** 1.0.0
**Last Updated:** February 2, 2026
**Status:** Production Ready

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Architecture](#2-architecture)
3. [API Reference](#3-api-reference)
4. [Core Components](#4-core-components)
5. [Data Models](#5-data-models)
6. [Safety & Compliance](#6-safety--compliance)
7. [Authentication & Authorization](#7-authentication--authorization)
8. [Configuration](#8-configuration)
9. [Deployment](#9-deployment)
10. [Monitoring & Observability](#10-monitoring--observability)
11. [Development Guide](#11-development-guide)
12. [Troubleshooting](#12-troubleshooting)

---

## 1. System Overview

### 1.1 Purpose

AI Receptionist is a production-ready, multi-tenant medical scheduling assistant that handles appointment booking, cancellations, and rescheduling through natural language conversations. It integrates with Electronic Health Record (EHR) systems and provides HIPAA-compliant patient interactions.

### 1.2 Key Features

| Feature | Description |
|---------|-------------|
| **Multi-tenant Architecture** | Isolated data per clinic with API key authentication |
| **Natural Language Processing** | Claude AI for intent classification and slot extraction |
| **Conversational State Machine** | Maintains context across multiple conversation turns |
| **Safety Pipeline** | PII detection, crisis detection, content filtering |
| **HIPAA Compliance** | Consent management, audit logging, data encryption |
| **EHR Integration** | Adapters for DrChrono, Epic, Cerner, Google Calendar |
| **Real-time Rate Limiting** | Per-clinic sliding window with Redis |

### 1.3 Technology Stack

```
Backend Framework:    FastAPI (Python 3.11+)
Database:            PostgreSQL 16
Cache/Sessions:      Redis 7
AI/LLM:              Claude 3.5 (Anthropic)
PII Detection:       Microsoft Presidio
ORM:                 SQLAlchemy 2.0 (async)
Migrations:          Alembic
HTTP Server:         Uvicorn (ASGI)
Deployment:          Docker, Railway
```

---

## 2. Architecture

### 2.1 High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         CLIENT LAYER                                 │
│   Web App │ Mobile App │ SMS (Twilio) │ Voice │ API Clients         │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                       API GATEWAY LAYER                              │
│   FastAPI │ Auth Middleware │ Rate Limiter │ CORS │ Routes          │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                  SAFETY & COMPLIANCE LAYER                           │
│   Sanitizer │ PII Detector │ Crisis Detector │ Content Filter       │
│   Consent Manager │ Audit Logger                                     │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     INTELLIGENCE LAYER                               │
│   Intent Classifier │ Slot Extractor │ Session Manager              │
│   State Machine (BookingState)                                       │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    SCHEDULING ENGINE                                 │
│   Flow Manager │ Calendar Client │ Response Generator │ Handoff     │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                  DATA & INFRASTRUCTURE                               │
│   PostgreSQL │ Redis │ Claude API │ Calendar Agent │ EHR Systems    │
└─────────────────────────────────────────────────────────────────────┘
```

### 2.2 Directory Structure

```
ai-receptionist/
├── app/
│   ├── main.py                 # Application entry point
│   ├── config.py               # Configuration management
│   │
│   ├── api/                    # HTTP Layer
│   │   ├── routes/
│   │   │   ├── chat.py        # POST /api/v1/chat
│   │   │   ├── health.py      # Health check endpoints
│   │   │   └── webhooks.py    # External webhooks
│   │   └── middleware/
│   │       ├── auth.py        # API key authentication
│   │       └── rate_limit.py  # Rate limiting
│   │
│   ├── core/                   # Business Logic
│   │   ├── safety/            # Safety pipeline
│   │   ├── intelligence/      # AI/ML components
│   │   ├── scheduling/        # Booking engine
│   │   └── response/          # Response generation
│   │
│   ├── infra/                  # Infrastructure
│   │   ├── database.py        # SQLAlchemy setup
│   │   ├── redis.py           # Redis client
│   │   └── claude.py          # Claude API wrapper
│   │
│   ├── models/                 # Data Models
│   │   └── database.py        # ORM models
│   │
│   └── mcp/                    # MCP Tools & EHR Adapters
│       ├── tools/
│       └── adapters/
│
├── alembic/                    # Database migrations
├── tests/                      # Test suites
├── docs/                       # Documentation
├── Dockerfile                  # Container definition
├── docker-compose.yml          # Local dev environment
└── railway.toml                # Railway deployment config
```

### 2.3 Request Flow

```
1. Client sends POST /api/v1/chat
   Headers: X-API-Key, X-Tenant-ID
   Body: {"message": "...", "session_id": "..."}

2. AuthMiddleware
   ├── Validate API key format (ar_live_* or ar_test_*)
   ├── Hash key with SHA-256
   ├── Check Redis cache → Database fallback
   ├── Verify clinic status is ACTIVE
   └── Set ClinicContext (ContextVar)

3. RateLimitMiddleware
   ├── Get clinic's rate limit tier
   ├── Check sliding window in Redis
   └── Add X-RateLimit-* headers

4. Route Handler (chat.py)
   └── Call engine.process()

5. Scheduling Engine
   ├── Load/create session
   ├── Safety Pipeline (input)
   ├── Intent Classification (Claude)
   ├── Slot Extraction (Claude)
   ├── Flow Manager (determine next state)
   ├── Calendar Agent (if booking/searching)
   ├── Response Generation (Claude)
   ├── Safety Pipeline (output)
   └── Save session

6. Return ChatResponse
```

---

## 3. API Reference

### 3.1 Chat Endpoint

**Endpoint:** `POST /api/v1/chat`

**Purpose:** Process a conversational message and return AI response.

#### Request

**Headers:**
| Header | Required | Description |
|--------|----------|-------------|
| `X-API-Key` | Yes | Clinic API key (`ar_live_*` or `ar_test_*`) |
| `X-Tenant-ID` | Yes | Clinic UUID |
| `Content-Type` | Yes | `application/json` |
| `X-Request-ID` | No | Request tracking ID (auto-generated if missing) |

**Body:**
```json
{
  "message": "I'd like to schedule an appointment with Dr. Smith",
  "session_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `message` | string | Yes | User's message (1-2000 chars) |
| `session_id` | string | No | Existing session UUID for continuity |

#### Response

**Success (200 OK):**
```json
{
  "message": "I'd be happy to help you schedule an appointment with Dr. Smith. What date works best for you?",
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "state": "collect_date",
  "intent": "scheduling",
  "confidence": 0.95,
  "booking_id": null,
  "collected_data": {
    "provider_name": "Dr. Smith"
  },
  "available_slots": null,
  "processing_time_ms": 245.5
}
```

| Field | Type | Description |
|-------|------|-------------|
| `message` | string | AI response message |
| `session_id` | string | Session UUID for next request |
| `state` | string | Current conversation state |
| `intent` | string | Detected intent |
| `confidence` | float | Intent confidence (0.0-1.0) |
| `booking_id` | string | Booking ID if created |
| `collected_data` | object | Extracted slots |
| `available_slots` | array | Available time slots |
| `processing_time_ms` | float | Processing time |

**Error Responses:**

| Code | Error | Description |
|------|-------|-------------|
| 400 | Validation error | Invalid request body |
| 401 | Missing API key | X-API-Key header required |
| 403 | Invalid API key | Key not found or inactive |
| 429 | Rate limit exceeded | Too many requests |
| 500 | Internal error | Server error |
| 503 | Service unavailable | Database/Redis down |

### 3.2 Health Endpoints

```
GET /health         → Basic health check
GET /health/ready   → Readiness (includes DB/Redis)
GET /health/live    → Liveness check
GET /health/detailed → Full system status (protected)
```

### 3.3 Webhook Endpoints

```
POST /webhooks/drchrono    → DrChrono EHR webhooks
POST /webhooks/twilio/sms  → Twilio SMS webhooks
POST /webhooks/twilio/voice → Twilio Voice webhooks
```

---

## 4. Core Components

### 4.1 Scheduling Engine

**File:** `app/core/scheduling/engine.py`

The central orchestrator that coordinates all components.

```python
class SchedulingEngine:
    async def process(
        self,
        tenant_id: str,
        message: str,
        session_id: Optional[str] = None
    ) -> EngineResponse:
        """
        Main entry point for processing chat messages.

        Flow:
        1. Load/create session
        2. Safety pipeline (input)
        3. Intent classification
        4. Slot extraction
        5. Flow management
        6. Calendar operations (if needed)
        7. Response generation
        8. Safety pipeline (output)
        9. Save session
        """
```

### 4.2 Intent Classifier

**File:** `app/core/intelligence/intent/classifier.py`

Uses Claude AI to classify user intent.

**Supported Intents:**
| Intent | Description | Example |
|--------|-------------|---------|
| `SCHEDULING` | Book new appointment | "I need to see Dr. Smith" |
| `CANCELLATION` | Cancel existing | "Cancel my appointment" |
| `RESCHEDULE` | Modify existing | "Can I move my appointment?" |
| `CHECK_APPOINTMENT` | View upcoming | "What appointments do I have?" |
| `CONFIRMATION` | Yes/no response | "Yes, that works" |
| `CORRECTION` | Fix information | "Actually, I meant Tuesday" |
| `HANDOFF` | Request human | "Can I speak to someone?" |
| `INFORMATION` | General questions | "What are your hours?" |
| `GREETING` | Hello | "Hi there" |
| `GOODBYE` | Farewell | "Thanks, bye" |
| `OUT_OF_SCOPE` | Unrelated | "What's the weather?" |
| `UNKNOWN` | Unclear | Ambiguous input |

### 4.3 Slot Extractor

**File:** `app/core/intelligence/slots/extractor.py`

Extracts structured data from messages.

**Slot Types:**
| Slot | Fields | Example |
|------|--------|---------|
| Provider | name, specialty | "Dr. Smith", "cardiologist" |
| DateTime | date, time, flexibility | "next Tuesday", "afternoon" |
| Appointment | type, reason | "checkup", "back pain" |
| Patient | name, phone, dob | "John Doe", "555-1234" |

### 4.4 Session Manager

**File:** `app/core/intelligence/session/manager.py`

Manages conversation state persistence.

```python
class SessionData:
    session_id: str
    clinic_id: str
    patient_id: Optional[str]
    current_state: BookingState
    previous_state: Optional[BookingState]
    collected_data: Dict[str, Any]
    intent_history: List[str]
    message_history: List[ConversationTurn]  # Last 10
    shown_slots: List[TimeSlot]
    selected_slot: Optional[TimeSlot]
    booking_id: Optional[str]
    created_at: datetime
    updated_at: datetime
    expires_at: datetime
```

### 4.5 State Machine

**File:** `app/core/intelligence/session/state.py`

```
States:
  IDLE                → Starting state
  COLLECT_PROVIDER    → Getting doctor name
  COLLECT_DATE        → Getting preferred date
  COLLECT_TIME        → Getting preferred time
  COLLECT_PATIENT_INFO → Getting patient details
  COLLECT_REASON      → Getting visit reason
  SEARCHING           → Searching for slots
  SHOWING_SLOTS       → Displaying options
  CONFIRM_BOOKING     → Confirming selection
  BOOKED              → Successfully booked
  CANCELLED           → Appointment cancelled
  HANDED_OFF          → Escalated to human
  COMPLETED           → Conversation ended
  ERROR               → Error state

Valid Transitions:
  IDLE → COLLECT_PROVIDER, COLLECT_DATE, SEARCHING
  COLLECT_PROVIDER → COLLECT_DATE, SEARCHING
  COLLECT_DATE → COLLECT_TIME, SEARCHING
  SEARCHING → SHOWING_SLOTS, ERROR
  SHOWING_SLOTS → CONFIRM_BOOKING, SEARCHING
  CONFIRM_BOOKING → BOOKED, SHOWING_SLOTS
  BOOKED → COMPLETED
  Any → HANDED_OFF, ERROR
```

### 4.6 Flow Manager

**File:** `app/core/scheduling/flow.py`

Determines conversation flow based on state and intent.

```python
class FlowAction:
    next_state: BookingState
    action_type: str  # collect, confirm, book, cancel, show_slots, handoff
    prompt_for: Optional[str]  # What to ask for
    should_search_slots: bool
    should_book: bool
    should_cancel: bool
```

### 4.7 Response Generator

**File:** `app/core/scheduling/response.py`

Generates natural language responses using Claude.

**Features:**
- Context-aware responses
- Template fallback if LLM fails
- Concise, professional tone
- Includes relevant data (slots, booking info)

---

## 5. Data Models

### 5.1 Database Schema

#### Clinic (Tenant)
```sql
CREATE TABLE clinics (
    id UUID PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    slug VARCHAR(100) UNIQUE NOT NULL,
    email VARCHAR(255),
    phone VARCHAR(50),
    address TEXT,
    timezone VARCHAR(50) NOT NULL,
    api_key_hash VARCHAR(255) NOT NULL,
    settings JSONB NOT NULL DEFAULT '{}',
    ehr_provider VARCHAR(50),
    ehr_credentials JSONB,
    business_hours JSONB NOT NULL,
    status clinic_status NOT NULL,  -- ACTIVE, SUSPENDED, INACTIVE
    default_reminder_hours INTEGER NOT NULL DEFAULT 24,
    rate_limit_tier VARCHAR(20) NOT NULL DEFAULT 'standard',
    rate_limit_rpm INTEGER NOT NULL DEFAULT 60,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
    deleted_at TIMESTAMP
);
```

#### Provider (Doctor)
```sql
CREATE TABLE providers (
    id UUID PRIMARY KEY,
    clinic_id UUID REFERENCES clinics(id) ON DELETE CASCADE,
    external_id VARCHAR(100),  -- EHR system ID
    first_name VARCHAR(100) NOT NULL,
    last_name VARCHAR(100) NOT NULL,
    title VARCHAR(50),
    specialty VARCHAR(100),
    email VARCHAR(255),
    phone VARCHAR(50),
    status provider_status NOT NULL,  -- ACTIVE, INACTIVE, ON_LEAVE
    schedule JSONB,
    default_appointment_duration INTEGER NOT NULL DEFAULT 30,
    accepting_new_patients BOOLEAN NOT NULL DEFAULT TRUE,
    npi VARCHAR(20),
    bio TEXT,
    languages JSONB NOT NULL DEFAULT '["en"]',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
    deleted_at TIMESTAMP
);
```

#### Patient
```sql
CREATE TABLE patients (
    id UUID PRIMARY KEY,
    clinic_id UUID REFERENCES clinics(id) ON DELETE CASCADE,
    external_id VARCHAR(100),
    first_name VARCHAR(100) NOT NULL,
    last_name VARCHAR(100) NOT NULL,
    email VARCHAR(255),
    phone VARCHAR(50),
    date_of_birth DATE,
    gender VARCHAR(20),
    street_address VARCHAR(255),
    city VARCHAR(100),
    state VARCHAR(50),
    zip_code VARCHAR(20),
    notes TEXT,
    phone_verified BOOLEAN NOT NULL DEFAULT FALSE,
    email_verified BOOLEAN NOT NULL DEFAULT FALSE,
    preferred_language VARCHAR(10) NOT NULL DEFAULT 'en',
    sms_opt_in BOOLEAN NOT NULL DEFAULT FALSE,
    email_opt_in BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
    deleted_at TIMESTAMP
);
```

#### Appointment
```sql
CREATE TABLE appointments (
    id UUID PRIMARY KEY,
    clinic_id UUID REFERENCES clinics(id) ON DELETE CASCADE,
    provider_id UUID REFERENCES providers(id) ON DELETE CASCADE,
    patient_id UUID REFERENCES patients(id) ON DELETE CASCADE,
    external_id VARCHAR(100),
    scheduled_start TIMESTAMP NOT NULL,
    scheduled_end TIMESTAMP NOT NULL,
    duration_minutes INTEGER NOT NULL,
    visit_type VARCHAR(100),
    reason TEXT,
    notes TEXT,
    status appointment_status NOT NULL,  -- SCHEDULED, CONFIRMED, etc.
    confirmed_at TIMESTAMP,
    reminder_sent_at TIMESTAMP,
    cancelled_at TIMESTAMP,
    cancellation_reason TEXT,
    cancelled_by VARCHAR(50),
    checked_in_at TIMESTAMP,
    completed_at TIMESTAMP,
    is_new_patient_visit BOOLEAN NOT NULL DEFAULT FALSE,
    special_instructions TEXT,
    rescheduled_from_id UUID REFERENCES appointments(id),
    booked_via VARCHAR(50) NOT NULL,  -- web, sms, voice, api
    reminder_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
    deleted_at TIMESTAMP
);
```

#### Session
```sql
CREATE TABLE sessions (
    id UUID PRIMARY KEY,
    clinic_id UUID REFERENCES clinics(id) ON DELETE CASCADE,
    channel VARCHAR(50) NOT NULL,  -- web, sms, voice
    channel_user_id VARCHAR(255),
    patient_id UUID REFERENCES patients(id),
    state JSONB NOT NULL,  -- Full SessionData
    expires_at TIMESTAMP NOT NULL,
    message_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### AuditLog
```sql
CREATE TABLE audit_logs (
    id UUID PRIMARY KEY,
    clinic_id UUID REFERENCES clinics(id) ON DELETE CASCADE,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    action audit_action NOT NULL,
    resource_type VARCHAR(50),
    resource_id VARCHAR(100),
    details JSONB,
    session_id UUID,
    ip_address VARCHAR(50),
    user_agent VARCHAR(500),
    severity VARCHAR(20) NOT NULL  -- info, warning, error, critical
);
```

### 5.2 Redis Data Structures

```
Key Patterns:
  receptionist:v1:session:{session_id}     → SessionData JSON (TTL: 30min)
  receptionist:v1:auth:{key_hash}          → ClinicContext JSON (TTL: 5min)
  receptionist:v1:ratelimit:{clinic_id}    → Counter (TTL: 60sec)
```

---

## 6. Safety & Compliance

### 6.1 Safety Pipeline

**File:** `app/safety/pipeline.py`

All messages pass through a multi-stage safety pipeline.

#### Input Processing (5 Stages)

| Stage | Component | Purpose |
|-------|-----------|---------|
| 1 | Sanitizer | Clean input, detect injection |
| 2 | Consent Manager | Verify patient consent |
| 3 | PII Detector | Detect & redact sensitive data |
| 4 | Crisis Detector | Identify emergencies |
| 5 | Content Filter | Block inappropriate content |

#### Output Processing (2 Stages)

| Stage | Component | Purpose |
|-------|-----------|---------|
| 1 | PII Leakage Detector | Prevent AI from revealing PII |
| 2 | Content Filter | Block medical hallucinations |

### 6.2 PII Detection

**File:** `app/safety/pii_detector.py`

Uses Microsoft Presidio analyzer.

**Detected Entities:**
- Social Security Numbers (SSN)
- Credit Card Numbers
- Email Addresses
- Phone Numbers
- Person Names
- Medical Record Numbers (MRN)
- Driver's License Numbers

**Actions:**
- Redact PII from input before LLM processing
- Log all PII incidents to audit trail
- Block if confidence > threshold

### 6.3 Crisis Detection

**File:** `app/safety/crisis_detector.py`

Detects mental health emergencies.

**Detection Patterns:**
- Suicide/self-harm mentions
- Violence threats
- Severe distress indicators

**Severity Levels:**
| Level | Action |
|-------|--------|
| LOW | Continue with gentle redirect |
| MEDIUM | Provide resources, offer human |
| HIGH | Immediate escalation to human |
| CRITICAL | Block AI, emergency resources |

**Crisis Resources Provided:**
- 988 Suicide & Crisis Lifeline
- Crisis Text Line (741741)
- 911 for immediate danger

### 6.4 Audit Logging

**File:** `app/safety/audit_logger.py`

Immutable audit trail for HIPAA compliance.

**Logged Events:**
| Action | Description |
|--------|-------------|
| CREATE | Resource created |
| UPDATE | Resource modified |
| DELETE | Resource deleted |
| LOGIN | Authentication attempt |
| SAFETY_TRIGGER | Safety check triggered |
| EMERGENCY | Crisis detected |
| PHI_DETECTED | PII found in message |
| APPOINTMENT_BOOKED | Booking completed |
| APPOINTMENT_CANCELLED | Cancellation |

### 6.5 HIPAA Compliance

| Requirement | Implementation |
|-------------|----------------|
| Access Control | API key auth, clinic isolation |
| Audit Controls | Comprehensive audit logging |
| Data Integrity | Database constraints, validations |
| Transmission Security | HTTPS only, encrypted connections |
| Consent | Explicit consent tracking |
| Minimum Necessary | Only collect required data |

---

## 7. Authentication & Authorization

### 7.1 API Key Format

```
ar_{environment}_{32_random_bytes_base64}

Examples:
  ar_live_abc123def456...  (production)
  ar_test_xyz789ghi012...  (sandbox)
```

### 7.2 Key Generation

```python
import secrets
import hashlib

def generate_api_key(environment: str = "live") -> str:
    random_bytes = secrets.token_urlsafe(32)
    return f"ar_{environment}_{random_bytes}"

def hash_api_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode()).hexdigest()
```

### 7.3 Authentication Flow

```
1. Extract X-API-Key header
2. Validate format (ar_live_* or ar_test_*)
3. Compute SHA-256 hash
4. Check Redis cache for hash
5. If cache miss, query database
6. Verify clinic status is ACTIVE
7. Set ClinicContext via ContextVar
8. Cache result in Redis (5-min TTL)
```

### 7.4 ClinicContext

```python
class ClinicContext:
    id: UUID
    name: str
    slug: str
    timezone: str
    status: str
    rate_limit_tier: str
    rate_limit_rpm: int
    ehr_provider: Optional[str]
    settings: dict
```

Accessible anywhere via:
```python
from app.api.middleware.auth import get_current_clinic
clinic = get_current_clinic()
```

### 7.5 Rate Limiting

**Algorithm:** Sliding Window Counter

**Tiers:**
| Tier | Requests/Minute |
|------|-----------------|
| free | 10 |
| standard | 60 |
| professional | 200 |
| enterprise | 1000 |
| unlimited | No limit |

**Headers:**
```
X-RateLimit-Limit: 60
X-RateLimit-Remaining: 45
X-RateLimit-Reset: 1706846400
Retry-After: 30  (on 429)
```

---

## 8. Configuration

### 8.1 Environment Variables

```bash
# Application
APP_ENV=production          # development, staging, production
DEBUG=false
HOST=0.0.0.0
PORT=8000
SECRET_KEY=your-secret-key

# Database
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/db

# Redis
REDIS_URL=redis://host:6379/0

# Claude AI
ANTHROPIC_API_KEY=sk-ant-...
CLAUDE_INTENT_MODEL=claude-3-5-haiku-20241022
CLAUDE_FALLBACK_MODEL=claude-sonnet-4-20250514
CLAUDE_INTENT_CONFIDENCE_THRESHOLD=0.7

# Calendar Agent
CALENDAR_AGENT_URL=http://localhost:8001

# Rate Limiting
RATE_LIMIT_REQUESTS=60
RATE_LIMIT_WINDOW=60

# Session
REDIS_SESSION_TTL=1800

# CORS
CORS_ORIGINS=["http://localhost:3000"]
```

### 8.2 Configuration Classes

**File:** `app/config.py`

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    app_env: str = "development"
    debug: bool = False
    database_url: str
    redis_url: str
    anthropic_api_key: str
    # ... more settings

    class Config:
        env_file = ".env"
        case_sensitive = False

settings = Settings()
```

---

## 9. Deployment

### 9.1 Docker

**Multi-stage Dockerfile:**
```dockerfile
# Stage 1: Builder
FROM python:3.11-slim as builder
WORKDIR /app
RUN apt-get update && apt-get install -y build-essential libpq-dev
COPY requirements.txt .
RUN pip wheel --no-cache-dir --wheel-dir /app/wheels -r requirements.txt

# Stage 2: Production
FROM python:3.11-slim as production
WORKDIR /app
RUN groupadd -r appuser && useradd -r -g appuser appuser
RUN apt-get update && apt-get install -y libpq5 curl
COPY --from=builder /app/wheels /wheels
RUN pip install --no-cache /wheels/*
COPY --chown=appuser:appuser . .
USER appuser
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### 9.2 Docker Compose (Development)

```yaml
version: '3.8'
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_DB: ai_receptionist
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data

  redis:
    image: redis:7
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data

volumes:
  postgres_data:
  redis_data:
```

### 9.3 Railway Deployment

**railway.toml:**
```toml
[build]
builder = "dockerfile"
dockerfilePath = "Dockerfile"

[deploy]
healthcheckPath = "/health"
healthcheckTimeout = 30
restartPolicyType = "on_failure"
restartPolicyMaxRetries = 3
startCommand = "sh -c 'uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}'"

[env]
APP_ENV = "production"
DEBUG = "false"
LOG_LEVEL = "INFO"
```

### 9.4 Database Migrations

```bash
# Create new migration
alembic revision --autogenerate -m "description"

# Run migrations
alembic upgrade head

# Rollback
alembic downgrade -1
```

---

## 10. Monitoring & Observability

### 10.1 Health Checks

| Endpoint | Purpose | Checks |
|----------|---------|--------|
| `/health` | Basic | App is running |
| `/health/ready` | Readiness | DB + Redis connected |
| `/health/live` | Liveness | Process healthy |
| `/health/detailed` | Full status | All dependencies |

### 10.2 Logging

**Format (Production):** JSON
```json
{
  "timestamp": "2026-02-02T04:00:00Z",
  "level": "INFO",
  "message": "Auth success",
  "clinic_id": "uuid",
  "ip": "1.2.3.4",
  "processing_time_ms": 245
}
```

**Log Levels:**
- DEBUG: Detailed debugging
- INFO: Normal operations
- WARNING: Potential issues
- ERROR: Errors (recoverable)
- CRITICAL: Fatal errors

### 10.3 Metrics (Future)

Planned Prometheus metrics:
- `receptionist_requests_total` - Total requests
- `receptionist_request_duration_seconds` - Latency histogram
- `receptionist_active_sessions` - Active sessions gauge
- `receptionist_intent_classification_seconds` - LLM latency
- `receptionist_safety_blocks_total` - Safety blocks

---

## 11. Development Guide

### 11.1 Local Setup

```bash
# Clone repository
git clone https://github.com/your-org/ai-receptionist.git
cd ai-receptionist

# Create virtual environment
python -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows

# Install dependencies
pip install -r requirements.txt

# Start databases
docker-compose up -d

# Run migrations
alembic upgrade head

# Create test data
psql $DATABASE_URL < scripts/seed_data.sql

# Start server
uvicorn app.main:app --reload
```

### 11.2 Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=app --cov-report=html

# Run specific test file
pytest tests/unit/test_intent_classifier.py

# Run integration tests
pytest tests/integration/
```

### 11.3 Adding New Features

**Adding a new intent:**
1. Add to `app/core/intelligence/intent/types.py`
2. Update classifier prompt in `classifier.py`
3. Add flow handling in `app/core/scheduling/flow.py`
4. Add tests

**Adding new EHR adapter:**
1. Create `app/mcp/adapters/new_ehr.py`
2. Implement `EHRAdapter` interface
3. Register in adapter factory
4. Add configuration

**Adding new safety check:**
1. Create `app/safety/new_check.py`
2. Implement check function
3. Add to pipeline in `pipeline.py`
4. Add audit logging

---

## 12. Troubleshooting

### 12.1 Common Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| 403 Invalid API key | Wrong hash in DB | Regenerate hash with `hash_api_key()` |
| 403 Clinic inactive | Status != ACTIVE | Update clinic status in DB |
| 429 Rate limited | Too many requests | Wait for window reset |
| 503 Service unavailable | DB/Redis down | Check database connectivity |
| Session not found | Expired/invalid | Start new conversation |
| Low intent confidence | Ambiguous message | Rephrase or provide more context |

### 12.2 Debug Mode

Enable in `.env`:
```
DEBUG=true
LOG_LEVEL=DEBUG
```

### 12.3 Database Queries

```sql
-- Check clinic status
SELECT id, name, status, api_key_hash FROM clinics WHERE slug = 'demo';

-- View recent sessions
SELECT * FROM sessions ORDER BY created_at DESC LIMIT 10;

-- Check audit logs
SELECT * FROM audit_logs WHERE clinic_id = 'uuid' ORDER BY timestamp DESC;

-- View appointments
SELECT a.*, p.first_name, pr.last_name as provider_name
FROM appointments a
JOIN patients p ON a.patient_id = p.id
JOIN providers pr ON a.provider_id = pr.id
WHERE a.clinic_id = 'uuid';
```

### 12.4 Redis Commands

```bash
# Connect to Redis
redis-cli

# View all keys
KEYS receptionist:*

# Get session
GET receptionist:v1:session:{session_id}

# Check rate limit
GET receptionist:v1:ratelimit:{clinic_id}

# Clear auth cache
DEL receptionist:v1:auth:{key_hash}
```

---

## Appendix A: API Error Codes

| Code | Error | Description |
|------|-------|-------------|
| 400 | Bad Request | Invalid request format |
| 401 | Unauthorized | Missing API key |
| 403 | Forbidden | Invalid key or inactive clinic |
| 404 | Not Found | Resource not found |
| 422 | Validation Error | Request validation failed |
| 429 | Too Many Requests | Rate limit exceeded |
| 500 | Internal Error | Server error |
| 503 | Service Unavailable | Dependency unavailable |

## Appendix B: Glossary

| Term | Definition |
|------|------------|
| **Clinic** | Tenant organization (medical practice) |
| **Provider** | Healthcare provider (doctor, nurse) |
| **Intent** | User's goal/purpose in message |
| **Slot** | Extracted entity from message |
| **Session** | Conversation context |
| **State** | Current position in booking flow |
| **EHR** | Electronic Health Record system |
| **PII** | Personally Identifiable Information |

---

**Document maintained by:** Engineering Team
**Questions:** engineering@yourcompany.com
