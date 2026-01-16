# AI Receptionist - Architecture Overview

## Complete Module Structure

```
ai-receptionist/
├── app/
│   ├── api/                    # HTTP Layer (Phase 1)
│   │   ├── routes/
│   │   │   ├── health.py       # Health check endpoints
│   │   │   ├── chat.py         # Main chat endpoint
│   │   │   └── webhooks.py     # External webhooks (DrChrono, Twilio)
│   │   └── middleware/
│   │       ├── auth.py         # API key authentication
│   │       └── rate_limit.py   # Rate limiting
│   │
│   ├── core/                   # Business Logic Layer
│   │   ├── safety/             # Phase 2: Safety & Compliance
│   │   │   ├── gate.py         # 4-layer safety gate
│   │   │   ├── phi.py          # Presidio PHI detection
│   │   │   ├── crisis.py       # Crisis detection
│   │   │   └── emergency.py    # Emergency handler
│   │   │
│   │   ├── intent/             # Phase 3: Intelligence Layer
│   │   │   ├── router.py       # Intent classification
│   │   │   ├── slot_filler.py  # Extract entities (date, time, provider)
│   │   │   └── context.py      # Build conversation context
│   │   │
│   │   ├── session/            # Phase 3: Session Management
│   │   │   └── manager.py      # Conversation state tracking
│   │   │
│   │   ├── scheduling/         # Phase 4: Scheduling Engine
│   │   │   ├── engine.py       # Main scheduling orchestration
│   │   │   ├── state_machine.py # Booking flow state machine
│   │   │   └── validator.py    # Business rules validation
│   │   │
│   │   └── response/           # Phase 5: Response Generation
│   │       ├── generator.py    # Claude-powered responses
│   │       └── handoff.py      # Human escalation logic
│   │
│   ├── mcp/                    # External Tools Layer (Phase 4)
│   │   ├── tools/              # MCP tool definitions
│   │   │   ├── availability.py # get_availability tool
│   │   │   ├── booking.py      # book_appointment tool
│   │   │   ├── cancel.py       # cancel_appointment tool
│   │   │   └── patient.py      # get_patient tool
│   │   │
│   │   └── adapters/           # EHR System Adapters
│   │       ├── base.py         # Abstract adapter interface
│   │       ├── drchrono.py     # DrChrono implementation
│   │       └── google_cal.py   # Google Calendar implementation
│   │
│   ├── infra/                  # Infrastructure Layer (Phase 1+)
│   │   ├── database.py         # PostgreSQL connection
│   │   ├── redis.py            # Redis session store
│   │   ├── claude.py           # Claude API client (Phase 5)
│   │   └── notifications.py    # SMS/Email sending (Phase 5)
│   │
│   └── models/                 # Data Models (Phase 1)
│       └── database.py         # SQLAlchemy models
│
├── tests/
│   ├── unit/                   # Unit tests (per module)
│   ├── integration/            # Integration tests
│   └── api/                    # API endpoint tests
│
├── alembic/                    # Database migrations
├── docs/                       # Documentation
└── scripts/                    # Utility scripts
```

## Architecture Layers (Request Flow)

```
┌────────────────────────────────────────────────────────────────┐
│                         API LAYER                              │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────┐       │
│  │   Routes    │  │     Auth     │  │  Rate Limiter  │       │
│  └─────────────┘  └──────────────┘  └────────────────┘       │
└────────────────────────────┬───────────────────────────────────┘
                             │
                             ▼
┌────────────────────────────────────────────────────────────────┐
│                      SAFETY LAYER (Phase 2)                    │
│  ┌──────────┐  ┌───────────┐  ┌──────────┐  ┌──────────────┐ │
│  │  Crisis  │→ │ Emergency │→ │  Content │→ │  PHI Filter  │ │
│  └──────────┘  └───────────┘  └──────────┘  └──────────────┘ │
└────────────────────────────────┬───────────────────────────────┘
                                 │
                                 ▼
┌────────────────────────────────────────────────────────────────┐
│                   INTELLIGENCE LAYER (Phase 3)                 │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────┐       │
│  │   Intent    │→ │ Slot Filler  │→ │    Context     │       │
│  │   Router    │  │  (Entities)  │  │    Builder     │       │
│  └─────────────┘  └──────────────┘  └────────────────┘       │
└────────────────────────────────┬───────────────────────────────┘
                                 │
                                 ▼
┌────────────────────────────────────────────────────────────────┐
│                   SCHEDULING ENGINE (Phase 4)                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐│
│  │     State    │→ │   MCP Tools  │→ │   EHR Adapters      ││
│  │   Machine    │  │ (get/book/   │  │ (DrChrono, Epic,    ││
│  │              │  │  cancel)     │  │  Cerner, etc.)      ││
│  └──────────────┘  └──────────────┘  └──────────────────────┘│
└────────────────────────────────┬───────────────────────────────┘
                                 │
                                 ▼
┌────────────────────────────────────────────────────────────────┐
│                    RESPONSE LAYER (Phase 5)                    │
│  ┌────────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │    Claude API  │→ │   Response   │→ │   Notifications  │  │
│  │   Generation   │  │   Formatter  │  │   (SMS/Email)    │  │
│  └────────────────┘  └──────────────┘  └──────────────────┘  │
└────────────────────────────────────────────────────────────────┘
```

## Key Design Patterns

### 1. Modular Monolith
- Deploy as ONE server
- Organized into clear modules internally
- Each module has single responsibility
- Can split into microservices later if needed

### 2. Adapter Pattern (for EHRs)
- `mcp/adapters/base.py` defines interface
- Each EHR implements the same interface
- Easy to add new EHR systems without changing core logic

### 3. Layered Architecture
- One-way dependencies: `api` → `core` → `mcp` → `infra`
- Core business logic isolated from infrastructure
- Easy to test each layer independently

### 4. Multi-Tenant Design
- Each clinic is a tenant
- API key identifies tenant
- Data isolation via `clinic_id` foreign key

## Database Schema (PostgreSQL)

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Clinic    │────<│  Provider   │     │   Patient   │
│ (tenant)    │     │ (doctors)   │     │             │
└─────────────┘     └──────┬──────┘     └──────┬──────┘
                           │                   │
                           └───────┬───────────┘
                                   │
                           ┌───────▼───────┐
                           │  Appointment  │
                           └───────────────┘

Additional Tables:
- sessions (Redis-backed conversation state)
- audit_logs (HIPAA compliance)
```

## Technology Stack

| Layer | Technology |
|-------|------------|
| **Framework** | FastAPI (async Python) |
| **Database** | PostgreSQL 15 |
| **Cache** | Redis 7 |
| **ORM** | SQLAlchemy 2.0 (async) |
| **Migrations** | Alembic |
| **AI** | Claude 3.5 Sonnet (Anthropic API) |
| **Safety** | Microsoft Presidio (PHI detection) |
| **Deployment** | Railway / Docker |
| **Testing** | pytest, pytest-asyncio |

## Implementation Phases

| Phase | Duration | Status |
|-------|----------|--------|
| **Phase 1: Foundation** | 1 week | 🔄 In Progress |
| **Phase 2: Safety** | 1 week | ⏳ Pending |
| **Phase 3: Intelligence** | 1.5 weeks | ⏳ Pending |
| **Phase 4: Scheduling** | 2 weeks | ⏳ Pending |
| **Phase 5: Response & Deploy** | 1.5 weeks | ⏳ Pending |

## Future Extensibility

### Adding New Channels (Voice, WhatsApp, etc.)
If needed later, add `app/channels/` module:
```
app/channels/
├── base.py         # Abstract channel interface
├── web.py          # Web chat
├── sms.py          # SMS (Twilio)
└── voice.py        # Voice calls (speech-to-text)
```

### Adding New EHR Systems
Just add new adapter:
```
app/mcp/adapters/
├── drchrono.py     # Existing
├── epic.py         # NEW
├── cerner.py       # NEW
└── athena.py       # NEW
```

### Adding New Safety Checks
Add to safety layer:
```
app/core/safety/
├── gate.py             # Existing
├── spam_detection.py   # NEW
└── fraud_detection.py  # NEW
```

## Directory-Specific READMEs

Each major module will have its own README:
- `app/api/README.md` - HTTP layer documentation
- `app/core/safety/README.md` - Safety layer documentation
- `app/core/scheduling/README.md` - Scheduling engine documentation
- `app/mcp/README.md` - MCP tools documentation
