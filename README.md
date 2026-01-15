# AI Receptionist

Multi-tenant medical appointment scheduling system powered by conversational AI.

## Architecture

This project follows a **Modular Monolith** architecture - code is organized like microservices but deployed as a single container for simplicity and cost efficiency.

```
┌────────────────────────────────────────────────────────────────────────┐
│                         AI RECEPTIONIST SYSTEM                         │
│                                                                        │
│  ┌─────────┐   ┌─────────┐   ┌─────────┐   ┌─────────┐   ┌─────────┐ │
│  │   API   │ → │ SAFETY  │ → │  INTEL  │ → │ SCHED   │ → │ RESPONSE│ │
│  │  LAYER  │   │  LAYER  │   │  LAYER  │   │ ENGINE  │   │  LAYER  │ │
│  └─────────┘   └─────────┘   └─────────┘   └─────────┘   └─────────┘ │
│       │                           │              │             │       │
│       └───────────────────────────┴──────────────┴─────────────┘       │
│                                   │                                    │
│                          ┌────────┴────────┐                          │
│                          │   DATA LAYER    │                          │
│                          │ PostgreSQL Redis│                          │
│                          └─────────────────┘                          │
└────────────────────────────────────────────────────────────────────────┘
```

## Project Structure

```
ai-receptionist/
├── app/
│   ├── main.py                 # FastAPI entry point
│   ├── config.py               # Configuration management
│   │
│   ├── api/                    # HTTP Layer
│   │   ├── routes/
│   │   │   ├── chat.py         # Main chat endpoint
│   │   │   ├── webhook.py      # EHR webhooks
│   │   │   └── health.py       # Health checks
│   │   └── middleware/
│   │       ├── auth.py         # API key authentication
│   │       └── rate_limit.py   # Rate limiting
│   │
│   ├── core/                   # Business Logic
│   │   ├── safety/             # Phase 2: Safety Layer
│   │   │   ├── gate.py
│   │   │   ├── phi_detector.py
│   │   │   └── emergency.py
│   │   ├── intent/             # Phase 3: Intelligence
│   │   │   ├── router.py
│   │   │   └── patterns.py
│   │   ├── scheduling/         # Phase 4: Scheduling Engine
│   │   │   ├── engine.py
│   │   │   └── state_machine.py
│   │   └── session/
│   │       └── manager.py
│   │
│   ├── mcp/                    # MCP Tools Layer
│   │   ├── tools/
│   │   │   ├── calendar.py
│   │   │   └── patient.py
│   │   └── adapters/
│   │       ├── base.py
│   │       ├── drchrono.py
│   │       └── google_cal.py
│   │
│   ├── infra/                  # Infrastructure
│   │   ├── database.py
│   │   ├── redis.py
│   │   └── claude.py
│   │
│   └── models/                 # Shared Models
│       ├── database.py         # SQLAlchemy models
│       ├── requests.py         # Pydantic request schemas
│       └── responses.py        # Pydantic response schemas
│
├── tests/
│   ├── unit/
│   ├── integration/
│   └── api/
│
├── scripts/
│   └── seed_data.py
│
├── docs/
│   └── architecture.drawio
│
├── alembic/                    # Database migrations
│   └── versions/
│
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── requirements-dev.txt
├── alembic.ini
├── railway.toml
├── .env.example
└── README.md
```

## Tech Stack

| Component | Technology |
|-----------|------------|
| Framework | FastAPI |
| Database | PostgreSQL |
| Cache/Sessions | Redis |
| ORM | SQLAlchemy 2.0 |
| Migrations | Alembic |
| LLM | Claude (Anthropic) |
| PHI Detection | Microsoft Presidio |
| EHR Integration | DrChrono API |
| Deployment | Railway |

## Quick Start

### Prerequisites

- Python 3.11+
- PostgreSQL 15+
- Redis 7+
- Docker (optional)

### Local Development

1. **Clone the repository**
   ```bash
   git clone git@github.com:incrivelsoft/ai-receptionist.git
   cd ai-receptionist
   ```

2. **Create virtual environment**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   pip install -r requirements-dev.txt
   ```

4. **Set up environment variables**
   ```bash
   cp .env.example .env
   # Edit .env with your configuration
   ```

5. **Run database migrations**
   ```bash
   alembic upgrade head
   ```

6. **Start the server**
   ```bash
   uvicorn app.main:app --reload --port 8000
   ```

### Using Docker

```bash
docker-compose up -d
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Basic health check |
| `/health/ready` | GET | Readiness probe (DB + Redis) |
| `/health/live` | GET | Liveness probe |
| `/api/v1/chat` | POST | Main chat endpoint |
| `/api/v1/webhook/drchrono` | POST | DrChrono webhook handler |

## Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `DATABASE_URL` | PostgreSQL connection string | Yes |
| `REDIS_URL` | Redis connection string | Yes |
| `ANTHROPIC_API_KEY` | Claude API key | Yes |
| `DRCHRONO_CLIENT_ID` | DrChrono OAuth client ID | Yes |
| `DRCHRONO_CLIENT_SECRET` | DrChrono OAuth client secret | Yes |
| `SECRET_KEY` | Application secret key | Yes |

## Implementation Phases

- [x] **Phase 1**: Foundation & Data Layer (Week 1)
- [ ] **Phase 2**: Safety & Compliance Layer (Week 2)
- [ ] **Phase 3**: Intelligence Layer (Week 3-4)
- [ ] **Phase 4**: Scheduling Engine & MCP (Week 4-6)
- [ ] **Phase 5**: Response Layer & Deployment (Week 6-7)

## License

Proprietary - Incrivelsoft © 2025
