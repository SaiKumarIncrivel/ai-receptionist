# AI Receptionist v2 — Multi-Agent Architecture

## Why Redesign

The current system works, but it has structural problems that limit quality:

**3 independent LLM calls per message** — intent classifier, slot extractor, and response
generator don't share context. They can disagree. Each one parses raw JSON and prays it's valid.

**600+ lines of rigid state machine** — `flow.py` + `engine.py` force a fixed collection order
(provider → date → time → patient info → confirm). A patient who says "I'm John, I need to
see Dr. Smith tomorrow at 2pm for a checkup" still gets walked through 5 turns.

**Hardcoded robotic responses** — `response.py` uses templates like "Which doctor would you
like to see?" and "What time works best for you on {date_str}?" every single time. The LLM
is only a fallback. Patients get the same scripted phrasing regardless of context or emotion.

**Tightly coupled to scheduling** — adding a new domain (FAQ, insurance questions) means
rewriting the flow manager, adding new states, new intent types, new orchestration code.

**No MCP advantage** — the Calendar Agent was built with MCP for AI-native integration,
but the AI Receptionist bypasses it with a hand-written HTTP client.

---

## Core Idea

**The AI Receptionist becomes a thin safety layer + router.**
Domain intelligence lives in specialized agents, connected via MCP.
**Every response is AI-generated. Zero hardcoded messages. Zero templates.**

```
┌──────────────────────────────────────────────────────────────────────────┐
│                         AI RECEPTIONIST v2                                │
│                                                                          │
│   Patient Message                                                        │
│        │                                                                 │
│        ▼                                                                 │
│   ┌──────────────┐                                                       │
│   │   SAFETY      │  PII detection, crisis detection, input sanitization │
│   │   PIPELINE    │  content filtering, audit logging                    │
│   │   (pre)       │                                                      │
│   └──────┬───────┘                                                       │
│          │                                                               │
│          ▼                                                               │
│   ┌──────────────┐     Single Claude call with tool_use                  │
│   │   ROUTER      │     Determines: domain + initial entities            │
│   │               │     Uses structured output (no JSON parsing)         │
│   └──────┬───────┘                                                       │
│          │                                                               │
│     ┌────┴────┬──────────┬──────────┬───────────┐                        │
│     ▼         ▼          ▼          ▼           ▼                        │
│  scheduling  faq      crisis     handoff    greeting/                    │
│     │         │          │          │        goodbye/                     │
│     ▼         ▼          ▼          ▼        out_of_scope                │
│  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐    │                       │
│  │Calendar│ │  FAQ   │ │ Crisis │ │ Human  │    ▼                        │
│  │ Agent  │ │ Agent  │ │Handler │ │Transfer│  Conversation               │
│  │ (MCP)  │ │ (MCP)  │ │ (code) │ │ (code) │  Agent (no tools)          │
│  └────┬───┘ └────┬───┘ └────────┘ └────────┘                            │
│       │          │                                                       │
│       ▼          ▼                                                       │
│   Claude + domain-specific MCP tools                                     │
│   (full conversation history, multi-turn)                                │
│       │                                                                  │
│       ▼                                                                  │
│   ┌──────────────┐                                                       │
│   │   SAFETY      │  Output filtering, PII scrubbing                     │
│   │   PIPELINE    │  Audit logging                                       │
│   │   (post)      │                                                      │
│   └──────┬───────┘                                                       │
│          │                                                               │
│          ▼                                                               │
│      Response                                                            │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## Design Principle: No Hardcoded Messages. Anywhere. Ever.

The current v1 has templates scattered everywhere:

```python
# v1 — THIS IS WHAT WE'RE KILLING
"Which doctor would you like to see?"
"What time works best for you on {date_str}?"
"Your appointment has been cancelled. Is there anything else I can help you with?"
"I'm specifically designed to help with scheduling appointments."
```

In v2, **Claude writes every response**. Every agent gets a carefully crafted system prompt
that defines its personality, tone, and constraints. Claude then generates contextually
appropriate responses every time — no two interactions feel the same.

The only non-AI responses are:

- **Crisis detection** — deterministic safety response (988 Lifeline, required by policy)
- **System errors** — when Claude API is completely down (rare fallback only)

---

## Layer 1: Safety Pipeline (UNCHANGED)

Everything in `app/safety/` stays exactly as-is:

- PII Detector (Presidio) — runs on input AND output
- Crisis Detector — pattern-matching, 988 Lifeline integration
- Input Sanitizer — prompt injection defense
- Content Filter — healthcare-aware dual-mode
- Consent Manager — patient verification
- Audit Logger — tamper-evident hash chain
- Safety Middleware — makes safety unavoidable

**Zero changes here.** This is your compliance foundation.

---

## Layer 2: Router

The router replaces the current intent classifier + slot extractor with a **single Claude
call using tool_use** (native structured output, no JSON parsing).

### What Changes

| Current (v1)                          | New (v2)                              |
|---------------------------------------|---------------------------------------|
| LLM Call 1: Intent classifier         | Single call: Router                   |
| LLM Call 2: Slot extractor            | (merged into router)                  |
| Raw JSON output → manual parsing      | tool_use → guaranteed structured data |
| Intent and slots don't share context  | Single call sees everything together  |
| Separate prompts, separate errors     | One prompt, one result                |

### Router System Prompt

```
You are the intake router for a medical clinic's AI receptionist system.

Your ONLY job is to classify the patient's message and extract any relevant information.
You do NOT write a response to the patient. You only analyze their message.

DOMAINS:
- scheduling: Patient wants to BOOK, CANCEL, RESCHEDULE, or CHECK an appointment.
  This includes any message that mentions doctors, appointments, availability, times, or dates
  in the context of wanting to see someone.
- faq: Patient is ASKING A QUESTION about the clinic — hours, location, insurance accepted,
  services offered, parking, what to bring, policies, costs. They want information, not an appointment.
- crisis: Patient is expressing self-harm, suicidal thoughts, or acute emotional/psychological
  distress. Err on the side of caution — if in doubt, classify as crisis.
- handoff: Patient explicitly asks to speak with a real person, human, manager, supervisor,
  or front desk staff. Must be explicit — frustration alone is not a handoff request.
- greeting: Patient is saying hello, hi, good morning, etc. This is ONLY for the very first
  message or a standalone greeting with no other content.
- goodbye: Patient is ending the conversation — bye, thanks, that's all, etc.
- out_of_scope: Message is completely unrelated to healthcare or the clinic. Recipes, weather,
  homework, etc.

SUB-INTENTS (for scheduling domain):
- book: Wants a new appointment
- cancel: Wants to cancel an existing appointment
- reschedule: Wants to move an existing appointment
- check: Wants to know about an upcoming appointment
- provide_info: Answering a question the receptionist asked (giving name, date, time, doctor)
- confirm_yes: Confirming something (yes, correct, book it, sounds good, perfect)
- confirm_no: Rejecting something (no, wrong, that's not right, change it)
- correction: Correcting a misunderstanding (no I said Tuesday, not Dr. Smith — Dr. Patel)
- select_option: Picking from options shown (the first one, option 2, the 3pm one, Dr. Smith)

SUB-INTENTS (for faq domain):
- question: General question about the clinic

ENTITY EXTRACTION:
Extract ONLY what is explicitly stated. Never guess or infer.
- Dates: Convert relative dates using today = {today}
  "tomorrow" = {tomorrow}, "next Monday" = {next_monday}, etc.
- Times: Convert to 24h format. "2pm" = "14:00", "morning" = flexible
- Names: Extract as spoken. "Dr. Smith" → "Smith", "Doctor Jane Smith" → "Jane Smith"
- Phone: Extract any phone number format
- If something is ambiguous, omit it. Better to ask than to guess wrong.

CONVERSATION CONTEXT:
{session_context}

Use the context to understand what the patient is responding to. If the receptionist just asked
"what time works for you?" and the patient says "3pm", that's provide_info, not a new booking request.
```

### Router Tool Schema

```python
response = await client.messages.create(
    model="claude-3-5-haiku-20241022",
    system=ROUTER_SYSTEM_PROMPT,
    messages=[
        *conversation_history_for_router,
        {"role": "user", "content": patient_message}
    ],
    tools=[{
        "name": "route_message",
        "description": "Classify patient message and extract key information",
        "input_schema": {
            "type": "object",
            "properties": {
                "domain": {
                    "type": "string",
                    "enum": ["scheduling", "faq", "crisis", "handoff",
                             "greeting", "goodbye", "out_of_scope"]
                },
                "confidence": {
                    "type": "number",
                    "minimum": 0, "maximum": 1
                },
                "sub_intent": {
                    "type": "string",
                    "enum": ["book", "cancel", "reschedule", "check",
                             "provide_info", "confirm_yes", "confirm_no",
                             "correction", "select_option", "question"]
                },
                "entities": {
                    "type": "object",
                    "properties": {
                        "provider_name": {"type": "string"},
                        "date": {"type": "string", "description": "ISO YYYY-MM-DD"},
                        "time": {"type": "string", "description": "24h HH:MM"},
                        "date_raw": {"type": "string", "description": "Original text"},
                        "time_raw": {"type": "string", "description": "Original text"},
                        "is_flexible": {"type": "boolean"},
                        "patient_name": {"type": "string"},
                        "patient_phone": {"type": "string"},
                        "patient_email": {"type": "string"},
                        "reason": {"type": "string"},
                        "appointment_type": {"type": "string"},
                        "booking_id": {"type": "string"},
                        "faq_topic": {"type": "string"},
                        "selected_option": {"type": "string",
                            "description": "Which option patient picked, e.g. '1', 'first', 'Dr. Smith'"}
                    }
                },
                "urgency": {
                    "type": "string",
                    "enum": ["low", "medium", "high"]
                }
            },
            "required": ["domain", "confidence", "sub_intent"]
        }
    }],
    tool_choice={"type": "tool", "name": "route_message"}
)

# Always a clean Python dict — no JSON parsing, no markdown stripping
route = response.content[0].input
```

### Fallback Strategy

If Haiku confidence < 0.7, retry with Sonnet (same as current approach, but now it's
one retry instead of two separate classifiers failing independently).

---

## Layer 3: Agent Dispatch

Based on the router's `domain`, we dispatch to the right handler.

### The Key Safety Decision: Intent-Gated Tool Access

**Claude only gets the MCP tools for the active domain.** This is the healthcare safety gate.

- Router says "scheduling" → Claude gets Calendar Agent MCP tools ONLY
- Router says "faq" → Claude gets FAQ Agent MCP tools ONLY
- Router says "crisis" → NO AI agent, deterministic code handles it
- Router says "handoff" → NO AI agent, transfer logic runs

This means during a booking, Claude literally cannot call FAQ tools. During FAQ,
Claude cannot accidentally book an appointment. The router is the gatekeeper.

### Dispatch Logic (Replaces engine.py + flow.py)

```python
async def dispatch(
    route: RouteResult,
    session: SessionData,
    message: str,
    tenant_id: str,
) -> str:
    """Dispatch to the right agent based on router decision."""

    # Track agent switching
    if route.domain != session.active_agent:
        session.previous_agent = session.active_agent
        session.active_agent = route.domain

    match route.domain:
        case "scheduling":
            return await scheduling_agent.handle(
                message=message,
                session=session,
                route=route,
                tenant_id=tenant_id,
            )

        case "faq":
            return await faq_agent.handle(
                message=message,
                session=session,
                route=route,
            )

        case "crisis":
            # Deterministic — no AI. This is the ONE exception.
            return crisis_handler.respond(message, session)

        case "handoff":
            # AI writes the transfer message
            return await handoff_agent.handle(message, session)

        case "greeting" | "goodbye" | "out_of_scope":
            return await conversation_agent.handle(
                message=message,
                session=session,
                route=route,
            )
```

---

## Layer 4: Domain Agents

Every agent follows the same pattern:
1. Receives message + session + route
2. Builds full conversation history for Claude
3. Calls Claude with domain-specific system prompt + MCP tools (if any)
4. Processes tool calls in a loop until Claude produces a final text response
5. Returns the response

**Claude writes EVERY response.** The system prompt shapes the personality and constraints.
The tools give Claude real capabilities. The conversation history gives context.

---

### Agent: Scheduling (Calendar Agent via MCP)

This is the main agent. It handles booking, cancellation, rescheduling, and appointment checks.

#### System Prompt

```
You are a receptionist at a medical clinic. You're warm, professional, and genuinely
helpful — like a real person at a front desk who cares about patients.

YOUR PERSONALITY:
- You're friendly and natural, not robotic or scripted
- You use conversational language, not corporate-speak
- You're empathetic — if someone mentions pain or worry, acknowledge it briefly
- You're efficient — don't waste the patient's time with unnecessary small talk
- You adapt your tone to the patient: casual if they're casual, formal if they're formal
- You use the patient's name naturally once you know it (not in every sentence)
- You say "I" not "we" — you're a person, not a committee

WHAT YOU CAN DO:
You have access to the clinic's scheduling system. You can:
- Look up available doctors and their specialties
- Find open appointment times
- Book appointments
- Cancel appointments
- Reschedule appointments
- Check on existing appointments

HOW TO HAVE A CONVERSATION:
- If the patient gives you everything at once ("I need to see Dr. Smith tomorrow at 2pm,
  my name is John"), don't ask for info you already have. Go straight to checking availability.
- If they're vague ("I need an appointment"), ask naturally — don't interrogate.
  "Sure! Do you have a particular doctor in mind, or would you like me to help find the right one?"
- When presenting time slots, be concise but clear. Use natural language, not a formatted list.
  "Dr. Smith has openings tomorrow at 9:30am, 11am, and 2:15pm. Which works best for you?"
- Before booking, always confirm the details conversationally:
  "Perfect — so that's Dr. Smith, tomorrow February 6th at 2:15pm. Want me to go ahead and book that?"
- After booking, be warm but brief:
  "All set! Your appointment with Dr. Smith is booked for tomorrow at 2:15pm. You'll get a
  reminder beforehand. Anything else I can help with?"
- If something goes wrong (slot taken, no availability), be helpful, not apologetic:
  "Looks like that slot just got taken. Dr. Smith also has a 3pm opening, or I can check
  Thursday if that works better?"

WHAT YOU NEED BEFORE BOOKING:
- Which doctor (or let you recommend one)
- What date
- What time
- Patient's name
Collect these naturally through conversation. Don't list them out like a form.

WHAT YOU ALREADY KNOW ABOUT THIS PATIENT:
{collected_data}

IMPORTANT RULES:
- NEVER make up availability. Always use the tools to check.
- NEVER confirm a booking without explicitly asking the patient first.
- NEVER share other patients' information.
- If a patient seems upset or frustrated, acknowledge it: "I understand that's frustrating,
  let me see what I can do."
- If you genuinely can't help, offer to connect them with front desk staff.
- Keep responses to 1-3 sentences unless you're presenting multiple options.
```

#### Tool Call Flow

```python
class SchedulingAgent:
    async def handle(self, message, session, route, tenant_id):
        # Merge any entities the router already extracted
        session.merge_entities(route.entities)

        # Build full Anthropic-format conversation history
        messages = session.get_claude_messages()
        messages.append({"role": "user", "content": message})

        # Claude with Calendar Agent's MCP tools
        response = await self.client.messages.create(
            model="claude-sonnet-4-20250514",
            system=self._build_system_prompt(session),
            messages=messages,
            tools=self.calendar_tools,
            max_tokens=1024,
        )

        # Process tool calls in a loop until Claude gives final text
        final_text, full_interaction = await self._process_tool_loop(
            response, messages, session, tenant_id
        )

        # Store the full interaction in session
        # (includes tool calls + results so Claude has context next turn)
        session.store_turn(message, full_interaction, final_text)

        return final_text

    async def _process_tool_loop(self, response, messages, session, tenant_id):
        """Handle Claude's tool calls until we get a text response."""
        all_messages = list(messages)

        while response.stop_reason == "tool_use":
            tool_blocks = [b for b in response.content if b.type == "tool_use"]
            tool_results = []

            for call in tool_blocks:
                # Audit log every tool call (HIPAA)
                await self.audit.log_tool_call(
                    session_id=session.session_id,
                    tool=call.name,
                    input=call.input,
                    tenant_id=tenant_id,
                )

                # Execute via Calendar Agent (MCP bridge or HTTP)
                result = await self.calendar_client.execute_tool(
                    call.name, call.input, tenant_id
                )

                # Audit log the result
                await self.audit.log_tool_result(
                    session_id=session.session_id,
                    tool=call.name,
                    result=result,
                )

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": call.id,
                    "content": json.dumps(result),
                })

            # Append to conversation and continue
            all_messages.append({"role": "assistant", "content": response.content})
            all_messages.append({"role": "user", "content": tool_results})

            response = await self.client.messages.create(
                model="claude-sonnet-4-20250514",
                system=self._build_system_prompt(session),
                messages=all_messages,
                tools=self.calendar_tools,
            )

        # Extract final text
        text_blocks = [b for b in response.content if b.type == "text"]
        final_text = text_blocks[0].text if text_blocks else \
            "I'm having a bit of trouble right now. Let me connect you with the front desk."

        return final_text, all_messages
```

#### Calendar Agent MCP Tools

Already built in the Calendar Agent. Loaded at startup:

| Tool                  | What It Does                                      |
|-----------------------|---------------------------------------------------|
| `list_providers`      | Get available doctors with specialties             |
| `find_optimal_slots`  | Find best available times with preferences         |
| `book_appointment`    | Book with conflict check and validation            |
| `cancel_appointment`  | Cancel with reason tracking                        |
| `reschedule`          | Move to new time with validation                   |
| `check_conflicts`     | Explain why a time is blocked                      |
| `get_booking`         | Look up booking details                            |

---

### Agent: FAQ

Handles clinic information questions. No scheduling tools — just knowledge base access.

#### System Prompt

```
You are a receptionist at a medical clinic answering patient questions about the clinic.

YOUR PERSONALITY:
- Same warm, natural tone as always
- You're knowledgeable and helpful
- If you know the answer, give it directly — don't make patients work for it
- If you don't know something, be honest: "I'm not sure about that, but our front desk
  team can help — want me to connect you?"

WHAT YOU CAN DO:
You have access to the clinic's knowledge base. You can look up:
- Clinic hours and location
- Insurance plans accepted
- Services offered
- Provider bios and specialties
- Parking and directions
- What to bring to appointments
- Policies (cancellation, late arrivals, etc.)
- Costs and payment options

HOW TO RESPOND:
- Be direct. If someone asks "what are your hours?", lead with the hours.
  Don't say "Great question! Let me look that up for you."
- If the answer naturally leads to booking, gently offer:
  "We're open Monday through Friday, 8am to 5pm. Would you like to schedule an appointment?"
- Keep it conversational. "We accept Blue Cross, Aetna, United, and most major plans.
  If you tell me yours, I can double-check for you."

IMPORTANT:
- Never guess about insurance coverage or costs — always use the tools if available.
- If a question is about a specific medical condition or treatment, suggest they
  discuss it with a doctor and offer to book an appointment.

WHAT YOU KNOW ABOUT THIS PATIENT:
{collected_data}
```

#### Tools (Future MCP Server)

| Tool                     | What It Does                                  |
|--------------------------|-----------------------------------------------|
| `search_knowledge_base`  | Search clinic information by topic             |
| `get_clinic_hours`       | Get hours for specific day/department          |
| `check_insurance`        | Verify if a specific plan is accepted          |
| `get_provider_info`      | Get bio, specialties, credentials for a doctor |
| `get_policies`           | Get specific policy details                    |

For v2 Phase 1, FAQ can work WITHOUT MCP tools — just Claude with a detailed system prompt
containing the clinic's info. MCP tools come later when the knowledge base grows.

---

### Agent: Conversation (Greetings, Goodbyes, Out-of-Scope)

Handles the "social" parts of the conversation. No tools needed — just Claude being natural.

#### System Prompt

```
You are a receptionist at a medical clinic. You're handling the social parts of
the conversation — greetings, goodbyes, and off-topic messages.

YOUR PERSONALITY:
- Warm and genuine, like a real person at a desk
- Brief — don't over-explain what you can do unless the patient seems lost
- Natural — match the patient's energy

FOR GREETINGS:
- Keep it simple and warm. "Hi there! How can I help you today?" is fine.
- If it's a returning patient and you know their name, use it naturally.
  "Hey Sarah! What can I do for you?"
- Don't list all your capabilities unprompted. Let them tell you what they need.
- If they seem unsure, a gentle nudge: "I can help you book an appointment,
  answer questions about the clinic, or pretty much anything else. What's on your mind?"

FOR GOODBYES:
- Match their energy. If they say "thanks bye!", keep it light: "Bye! Take care."
- If they just finished booking, tie it together: "See you on Thursday! Take care."
- Don't be over-the-top: no "Thank you SO much for choosing our clinic! We look
  forward to serving you!" — that's corporate, not human.

FOR OUT-OF-SCOPE:
- Be honest and light about it. "Ha, I wish I could help with that, but I'm
  really just the scheduling person here. Anything clinic-related I can help with?"
- Don't lecture about what you can and can't do. One sentence, redirect naturally.
- If they persist with off-topic, stay friendly: "I'm honestly not the best help
  for that, but I'm here whenever you need anything clinic-related."

WHAT YOU KNOW ABOUT THIS PATIENT:
{collected_data}
```

---

### Agent: Handoff

Transfers to human staff. Claude writes the message, system triggers the transfer.

#### System Prompt

```
You are a receptionist at a medical clinic. The patient has asked to speak with
a real person on the staff.

YOUR JOB:
- Acknowledge their request warmly
- Let them know you're connecting them
- If you know WHY they want a human (from conversation context), briefly note it
  so the staff member has context
- Keep it to 1-2 sentences

EXAMPLES OF GOOD RESPONSES:
- "Absolutely, let me connect you with someone at the front desk. One moment."
- "Of course! I'll get a staff member on the line. They'll be able to help
  with your insurance question."
- "Sure thing — transferring you now. They'll have our conversation for context."

DON'T:
- Try to solve the problem yourself
- Ask "are you sure?"
- Apologize excessively
- Be slow about it — they asked, just do it

WHAT YOU KNOW ABOUT THIS PATIENT:
{collected_data}
```

---

### Handler: Crisis (DETERMINISTIC — NO AI)

**This is the one place where we do NOT use AI for the response.**

Crisis detection runs in the safety pipeline (Layer 1). If detected, the response is
deterministic and medically/legally safe. We don't risk Claude generating an inappropriate
response to someone in crisis.

```python
class CrisisHandler:
    """Deterministic crisis response. No AI. No variation."""

    def respond(self, message: str, session: SessionData) -> str:
        return (
            "I hear you, and I want you to know that help is available right now. "
            "Please reach out to the 988 Suicide & Crisis Lifeline — "
            "you can call or text 988 anytime, 24/7. "
            "You can also chat at 988lifeline.org. "
            "Would you like me to connect you with someone at the clinic who can help?"
        )
```

---

## Layer 5: Session Management

The session is the backbone of natural conversation. It stores the **full Claude
conversation format** — including tool calls and results — so Claude has complete context
on every turn.

### Why This Matters

In v1, session stores stripped-down text:
```python
# v1 — Claude gets almost no context
message_history = [
    {"role": "user", "content": "I need to see Dr. Smith"},
    {"role": "assistant", "content": "What date works for you?"},
    {"role": "user", "content": "tomorrow"},
    {"role": "assistant", "content": "What time?"},
]
```

Claude sees words but doesn't know what happened behind them. It doesn't know which slots
were checked, what the patient was shown, what tools were called.

In v2, session stores the FULL interaction:
```python
# v2 — Claude sees EVERYTHING that happened
claude_messages = [
    {"role": "user", "content": "I need to see Dr. Smith tomorrow"},

    # Claude's response INCLUDING the tool call
    {"role": "assistant", "content": [
        {"type": "text", "text": "Let me check Dr. Smith's availability for tomorrow."},
        {"type": "tool_use", "id": "tc_1", "name": "find_optimal_slots",
         "input": {"provider": "Smith", "date_range": {"start": "2025-02-06"}}}
    ]},

    # The tool result
    {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "tc_1",
         "content": "[{\"slot_id\": \"s1\", \"time\": \"09:30\"}, {\"slot_id\": \"s2\", \"time\": \"11:00\"}, {\"slot_id\": \"s3\", \"time\": \"14:15\"}]"}
    ]},

    # Claude's conversational response
    {"role": "assistant", "content": "Dr. Smith has openings tomorrow at 9:30am, 11am, and 2:15pm. Which works best for you?"},

    {"role": "user", "content": "the 2:15 one"},

    # Claude KNOWS "the 2:15 one" = slot_id "s3" because it can see the tool result above
    {"role": "assistant", "content": [
        {"type": "text", "text": "Great choice!"},
        {"type": "tool_use", "id": "tc_2", "name": "book_appointment",
         "input": {"slot_id": "s3", "patient_name": "...", ...}}
    ]},
]
```

When the patient says "the 2:15 one", Claude looks back at the tool results and knows
exactly which slot that is. No state machine needed. No slot-tracking code. Claude's
context window IS the state.

### Updated Session Model

```python
@dataclass
class SessionData:
    """Session that stores full Claude conversation state."""

    # --- Identifiers ---
    session_id: str = field(default_factory=lambda: str(uuid4()))
    clinic_id: str = ""
    patient_id: Optional[str] = None

    # --- Agent tracking ---
    active_agent: Optional[str] = None       # "scheduling", "faq", etc.
    previous_agent: Optional[str] = None     # For agent switching

    # --- Collected patient data ---
    # Accumulated from router entity extraction across the whole conversation.
    # Persists across agent switches.
    collected_data: dict = field(default_factory=dict)

    # --- Full conversation history (Anthropic messages format) ---
    # Includes tool calls and results. Sent directly to Claude.
    claude_messages: list[dict] = field(default_factory=list)
    max_messages: int = 40  # ~20 turns

    # --- Condensed history for router ---
    # Text-only version without tool calls. Used by the router
    # so it doesn't process the full tool chain.
    router_context: list[dict] = field(default_factory=list)
    max_router_context: int = 10

    # --- Metadata ---
    message_count: int = 0
    booking_id: Optional[str] = None
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)

    # --- Methods ---

    def store_turn(self, user_message: str, assistant_content, text_response: str):
        """Store a complete turn (user message + assistant response)."""
        # Full history (for Claude)
        self.claude_messages.append({"role": "user", "content": user_message})
        if isinstance(assistant_content, list):
            # Includes tool calls — store all intermediate messages
            for msg in assistant_content:
                self.claude_messages.append(msg)
        else:
            self.claude_messages.append({"role": "assistant", "content": text_response})

        # Condensed history (for router)
        self.router_context.append({"role": "user", "content": user_message})
        self.router_context.append({"role": "assistant", "content": text_response})

        self.message_count += 1
        self.updated_at = _utcnow()
        self._trim()

    def get_claude_messages(self) -> list[dict]:
        """Get full message history for Claude agent calls."""
        return list(self.claude_messages)

    def get_router_context_str(self) -> str:
        """Get condensed context string for router prompt."""
        if not self.router_context:
            return "New conversation, no prior context."

        lines = []
        for msg in self.router_context[-6:]:
            role = "Patient" if msg["role"] == "user" else "Receptionist"
            content = msg["content"][:200]
            lines.append(f"{role}: {content}")

        context = "\n".join(lines)

        if self.collected_data:
            collected = ", ".join(
                f"{k}: {v}" for k, v in self.collected_data.items() if v
            )
            context += f"\n\nCollected so far: {collected}"

        if self.active_agent:
            context += f"\nCurrently in: {self.active_agent} flow"

        return context

    def merge_entities(self, entities: dict):
        """Merge router-extracted entities into collected data."""
        if entities:
            for key, value in entities.items():
                if value is not None:
                    self.collected_data[key] = value

    def _trim(self):
        """Keep histories within limits."""
        if len(self.claude_messages) > self.max_messages:
            self.claude_messages = self.claude_messages[-self.max_messages:]
        if len(self.router_context) > self.max_router_context:
            self.router_context = self.router_context[-self.max_router_context:]
```

### Agent Switching (Mid-Conversation Domain Changes)

Patient is mid-booking and asks "do you accept Aetna?"

1. Router: `domain: "faq"`, `sub_intent: "question"`
2. Dispatch sees `session.active_agent = "scheduling"` → switching to "faq"
3. FAQ agent handles the question
4. `collected_data` (provider, date, etc.) is UNTOUCHED
5. Next message: "ok cool, let's continue booking"
6. Router: `domain: "scheduling"`, `sub_intent: "provide_info"`
7. Scheduling agent picks up — `claude_messages` has the full history, `collected_data` intact

Seamless. The patient never knows agents switched.

---

## Conversation Examples

### Example 1: Quick Booking (All Info at Once)

```
Patient: "Hi, I'm Sarah Chen. I need to see Dr. Patel tomorrow afternoon for a follow-up."

  [Router]: domain=scheduling, sub_intent=book
            entities={patient_name: "Sarah Chen", provider_name: "Patel",
                      date: "2025-02-06", time_raw: "afternoon",
                      is_flexible: true, appointment_type: "follow_up"}

  [Scheduling Agent]:
    Claude sees all entities. Calls find_optimal_slots.
    Gets: 1pm, 2:30pm, 4pm.

Receptionist: "Hi Sarah! Let me check Dr. Patel's afternoon availability for tomorrow.
               She has 1pm, 2:30pm, and 4pm open. What works best?"

Patient: "2:30 works"

  [Router]: domain=scheduling, sub_intent=select_option
            entities={selected_option: "2:30"}

  [Scheduling Agent]:
    Claude sees the previous tool results. Knows 2:30 = slot_id "s2".

Receptionist: "Great — Dr. Patel, tomorrow at 2:30pm for your follow-up. Shall I book that?"

Patient: "yes please"

  [Router]: domain=scheduling, sub_intent=confirm_yes

  [Scheduling Agent]:
    Claude calls book_appointment. Gets booking_id: "BK-7891".

Receptionist: "All set, Sarah! You're booked with Dr. Patel tomorrow at 2:30pm.
               We'll send you a reminder. Anything else?"

Patient: "nope, thanks!"

  [Router]: domain=goodbye

  [Conversation Agent]:

Receptionist: "See you tomorrow! Take care."
```

**v1 would take 7+ turns. v2 does it in 4.**

### Example 2: Agent Switching (FAQ Mid-Booking)

```
Patient: "I need to book an appointment"

Receptionist: "Sure! Do you have a doctor in mind, or would you like help finding one?"

Patient: "Before that — do you take Cigna?"

  [Router]: domain=faq, sub_intent=question
            entities={faq_topic: "insurance Cigna"}

  [FAQ Agent]:

Receptionist: "Yes, we accept Cigna — both PPO and HMO plans.
               Now, about that appointment — any doctor preference?"

Patient: "Dr. Kim please"

  [Router]: domain=scheduling, sub_intent=provide_info
            entities={provider_name: "Kim"}

  [Scheduling Agent resumes with full context]

Receptionist: "When would work for you to see Dr. Kim?"
```

### Example 3: Frustrated Patient

```
Patient: "I've been trying to reschedule for 20 minutes on your website and it keeps
          crashing. This is ridiculous."

  [Router]: domain=scheduling, sub_intent=reschedule, urgency=high

  [Scheduling Agent]:
    Claude reads the frustration. System prompt says acknowledge it.

Receptionist: "I'm sorry about that — that sounds really frustrating. Let me handle
               the reschedule for you right now. What's your name or booking number?"
```

### Example 4: Vague Patient

```
Patient: "umm yeah I think I need to come in? my stomach has been hurting"

  [Router]: domain=scheduling, sub_intent=book
            entities={reason: "stomach pain"}

  [Scheduling Agent]:

Receptionist: "I'm sorry to hear that. Let's get you in — do you have a regular
               doctor here, or should I find someone available soon?"

Patient: "I don't know, whoever is free I guess"

  [Scheduling Agent]:
    Claude calls find_optimal_slots with urgency preference.
    Gets slots across providers.

Receptionist: "Dr. Patel has an opening this afternoon at 3pm, and Dr. Kim can see
               you tomorrow morning at 9:30. Which sounds better?"
```

### Example 5: Multi-Turn with Correction

```
Patient: "Book me with Dr. Smith on Thursday"

Receptionist: "Dr. Smith on Thursday the 13th — what time works for you?"

Patient: "Actually wait, I meant Dr. Patel not Smith"

  [Router]: domain=scheduling, sub_intent=correction
            entities={provider_name: "Patel"}

  [Scheduling Agent]:
    Claude sees the correction in context. Updates naturally.

Receptionist: "No problem — Dr. Patel on Thursday. Let me check her availability.
               She has 10am, 1:30pm, and 3pm. Which works?"
```

---

## What Gets Deleted vs Added

### Deleted (~1,989 lines)

| File                              | Lines | Reason                                    |
|-----------------------------------|-------|-------------------------------------------|
| `scheduling/flow.py`             | 379   | Claude handles flow naturally              |
| `scheduling/calendar_client.py`  | 402   | Replaced by MCP bridge                    |
| `scheduling/response.py`         | 467   | Claude generates all responses             |
| `intelligence/intent/classifier.py` | 276 | Merged into router                      |
| `intelligence/slots/extractor.py`| 225   | Merged into router                         |
| `intelligence/intent/types.py`   | ~80   | Simplified                                 |
| `intelligence/slots/types.py`    | ~100  | Entities are plain dicts                   |
| `intelligence/session/state.py`  | ~60   | No more BookingState enum                  |

### Added

| Component                  | Purpose                                                  |
|----------------------------|----------------------------------------------------------|
| `router.py`                | Single tool_use call for domain + entity extraction      |
| `dispatch.py`              | Route → agent dispatch logic                             |
| `agents/base.py`           | Base agent class with tool loop + session helpers         |
| `agents/scheduling.py`     | Claude + Calendar Agent MCP tools                        |
| `agents/faq.py`            | Claude + FAQ knowledge (MCP tools later)                 |
| `agents/conversation.py`   | Greetings, goodbyes, out-of-scope (AI-generated)         |
| `agents/handoff.py`        | Human transfer (AI-written message)                      |
| `handlers/crisis.py`       | Deterministic crisis response (no AI)                    |
| `mcp/client.py`            | MCP tool bridge                                          |
| `session/models.py`        | Updated session with full Claude format                  |

### Unchanged

| Component               | Why                                                    |
|--------------------------|--------------------------------------------------------|
| `app/safety/*`           | Entire safety pipeline                                 |
| `app/infra/*`            | Redis, PostgreSQL, Claude client                       |
| `app/api/*`              | API routes, middleware, auth                           |
| `app/models/*`           | Database models                                        |
| `app/config.py`          | Configuration (add MCP endpoint)                       |

---

## MCP Transport: HTTP Bridge Now, SSE Later

**Phase 1**: Load Calendar Agent's MCP tool schemas at startup. Convert to Anthropic
tool_use format. When Claude calls a tool, forward to Calendar Agent's existing REST API.

```
Claude calls find_optimal_slots(provider="Smith", ...)
    → Bridge converts to POST /api/slots/find {...}
    → Calendar Agent REST handles it
    → Bridge converts response → tool result
    → Claude continues
```

**Later**: Add SSE transport to Calendar Agent. Switch bridge to direct MCP/SSE.
Other Incrivelsoft products connect too. AI Receptionist code doesn't change.

---

## Implementation Phases

### Phase 1: Router
- Build router with tool_use (replaces classifier + extractor)
- Wire into existing engine temporarily
- Test against current system
- **Deliverable**: Better intent + extraction, same architecture

### Phase 2: Scheduling Agent + Session v2
- Build base agent with tool loop
- Build scheduling agent with system prompt
- Build MCP tool bridge (HTTP)
- Build session with full Claude message format
- Delete engine.py, flow.py, response.py, calendar_client.py
- **Deliverable**: Natural scheduling conversations

### Phase 3: Conversation + Handoff + Dispatch
- Build conversation agent (greeting/goodbye/out-of-scope)
- Build handoff agent
- Build dispatch layer + agent switching
- **Deliverable**: Complete multi-agent system

### Phase 4: FAQ Agent
- Build FAQ agent (system prompt first, MCP tools later)
- **Deliverable**: FAQ without touching scheduling code

### Phase 5: MCP SSE + External Access
- Add SSE to Calendar Agent
- Switch HTTP bridge → MCP/SSE
- **Deliverable**: Full MCP ecosystem

---

## Open Questions

1. **Model choice for scheduling agent** — Sonnet (best quality, ~15x cost of Haiku)
   vs Haiku (fast, cheap, may struggle with complex multi-turn)? Or adaptive?

2. **Evaluation** — Do you have real patient transcripts for testing?
   Need 50-100 test conversations to measure before/after quality.

3. **FAQ scope** — What clinic info should the FAQ agent know?
   Per-tenant config or hardcoded for now?

4. **Crisis response** — Keep deterministic (safest), or explore AI with guardrails?
