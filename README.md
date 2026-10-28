# Cloze

Cloze is an open-source platform for running controlled, monitored studies of human–AI conversation in mental health research. Researchers configure which large language models participants converse with, how the AI is instructed, how conversations are scheduled over time, and the safety constraints that always apply — while every message is captured with full provenance (model version, prompt configuration, timing). It supports OpenAI, Anthropic, Google, and locally hosted open-weight models (via Ollama) behind one interface, and runs in the cloud or fully on premises so participant data need never leave an institution. Cloze is research infrastructure for building an evidence base on human–AI interaction in mental health — not a therapeutic product.

Live at [cloze.uk](https://cloze.uk)

## Quick Start

### Prerequisites

- Python 3.9+
- [Homebrew](https://brew.sh) (macOS)

### Installation

```bash
git clone https://github.com/MattMatt27/cloze.git
cd cloze

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Configuration

```bash
cp .env.example .env
```

Add at least one LLM provider API key to `.env`:

```
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
GOOGLE_API_KEY=AI...
```

### Run

```bash
python manage.py
```

Open [http://localhost:5051](http://localhost:5051). The first run seeds the database with demo users.

**Demo accounts:**

| Role | Username | Password |
|------|----------|----------|
| Admin | `admin` | `admin123` |
| Provider | `provider1` | `provider123` |
| Participant | `user1` | `user123` |

### PDF Reports (optional)

```bash
brew install pango
```

This enables PDF export alongside HTML. Without it, PDF downloads fall back to HTML.

### Local LLM with Ollama (optional)

```bash
brew install ollama
ollama serve              # keep running in one terminal
ollama pull llama3.2:1b   # in another terminal
```

Provides on-device AI summaries in reports without cloud API calls.

## Architecture

Flask + SQLAlchemy + Jinja2 templates + Tailwind CSS (CDN). SQLite for local development; PostgreSQL in production (AWS RDS).

```
cloze/
├── llm_chat/                 # Flask application
│   ├── models/               # SQLAlchemy models
│   │   ├── core.py           #   User, ProviderPatient
│   │   ├── chat.py           #   Model, Conversation, Message, SavedSelection
│   │   ├── chat_window.py    #   ChatWindow, ChatTemplate
│   │   ├── study_flow.py     #   StudyFlow, FlowPhase, FlowChat, FlowEnrollment
│   │   ├── safety_plan.py    #   SafetyPlan
│   │   ├── audit.py          #   AuditLog, EscalationEvent
│   │   ├── report.py         #   Report
│   │   └── settings.py       #   SystemPrompt, Provider/Admin/UserSettings, ProviderFeatureFlags
│   ├── routes/               # API + page routes
│   │   ├── auth.py           #   Login/logout
│   │   ├── admin.py          #   Admin dashboard
│   │   ├── provider.py       #   Provider dashboard + patient management
│   │   ├── chat_windows.py   #   Window CRUD, conversation lifecycle
│   │   ├── conversations.py  #   Patient-facing pages
│   │   ├── reports.py        #   Report generation, download, config
│   │   └── safety_plan.py    #   Safety plan CRUD + approval workflow
│   ├── services/
│   │   ├── llm_interface.py  #   Multi-provider LLM client (OpenAI, Anthropic, Google, Ollama)
│   │   ├── guard.py          #   CLOZE-Guard keyword pre-classifier
│   │   ├── notifications.py  #   CLOZE-Guard alert emails (AWS SES)
│   │   ├── report_utils.py   #   Report generation orchestration
│   │   └── report_scheduler.py
│   └── utils/
│       ├── decorators.py     #   @role_required
│       ├── access_hours.py   #   CLOZE-Guard access-hours windows
│       ├── passwords.py      #   Password complexity policy
│       └── settings_resolution.py  # Feature flags > admin settings > defaults
├── prompts/                  # Layered prompt system
│   ├── composer.py           #   compose_system_prompt() — assembles all layers
│   ├── registry.py           #   Domain prompt registry
│   ├── loader.py             #   Markdown prompt loading
│   ├── constitutional/       #   Layer 1: universal safety, defaults, study context
│   └── domains/              #   Layer 2: anxiety, depression, trauma, etc.
├── report/                   # Report generation pipeline
│   ├── generator.py          #   UnifiedReportGenerator orchestrator
│   ├── config.py             #   v1/v2 config normalization
│   ├── registry.py           #   Feature registry (available/coming_soon/licensed)
│   ├── base.py               #   ReportComponent base class
│   ├── components/           #   Self-contained analysis components
│   │   ├── ai_summary.py     #     LLM-generated clinical summary
│   │   ├── descriptive_stats.py
│   │   ├── nlp_analysis.py   #     Sentiment, voice, keywords
│   │   ├── cooccurrence_analysis.py
│   │   └── saved_messages.py
│   ├── analyzers/            #   Pure-function analyzers (no DB access)
│   │   ├── sentiment.py
│   │   ├── voice_analysis.py
│   │   ├── keyword_extraction.py
│   │   └── cooccurrence.py
│   ├── renderers/
│   │   ├── html_renderer.py
│   │   └── pdf_renderer.py
│   └── styles/
│       ├── base_styles.py    #   Cloze design tokens
│       ├── academic_styles.py
│       └── pdf_styles.py
├── templates/                # Jinja2 (all extend base.html)
│   ├── base.html             #   Shared layout, sidebar, Tailwind config
│   ├── login.html, admin_login.html
│   ├── admin_dashboard.html
│   ├── provider_dashboard.html, provider_chats.html, provider_chat_windows.html
│   ├── provider_settings.html, study_design.html
│   ├── user_dashboard.html, user_chat_windows.html
│   ├── conversation.html, patient_reports.html
│   └── 403.html, 404.html, 500.html
├── static/
│   ├── js/shared.js          #   Shared utilities (escapeHtml, formatDate, etc.)
│   └── images/               #   logo.svg, logo-dark.svg, logo.png
├── scripts/generate_report.py  # Generate a report from the command line
├── tests/                    # pytest suite
├── migrate_schema.py         # Idempotent schema migrations (--apply)
└── manage.py                 # Entry point + database seeder
```

## Key Concepts

### Chat Windows

A time-boxed period (e.g., one week) during which a participant can have conversations. Providers create windows with one or more **chat templates** — each template has a title, purpose, assigned LLM model, and system prompt. Windows follow a lifecycle: `scheduled` → `active` → `generating_report` → `report_ready`.

### Study Flows

Windows are organized into **study flows** that define the temporal structure of a study. Three flow types are supported:

- **Always available** — conversations are open for the duration of enrollment, with no scheduling constraints.
- **Phased** — time-bounded phases (e.g., Baseline → Intervention → Follow-up), each with its own conversation configuration.
- **Recurring** — conversations repeat on a cadence (e.g., weekly check-ins), each cycle opening a fresh window.

Flows let participants progress through structured, longitudinal designs while the platform tracks enrollment, phase progression, and completion.

### Prompt System

Four-layer prompt composition:
1. **Constitutional** — identity, safety boundaries, scope constraints (markdown files)
2. **Domain** — topical focus area (anxiety, depression, trauma, etc.)
3. **Custom instructions** — provider-written per-template guidance
4. **Safety plan** — participant-specific warning signs, coping strategies, anti-patterns

### Safety Plans

Based on the Stanley-Brown Safety Planning Intervention. The provider creates the clinical framework (anti-patterns, care team, emergency plan), and the participant fills in their sections (warning signs, coping strategies, support network, reasons for living). Versioned with approval workflow: `draft` → `pending_review` → `active` → `superseded`.

### Safety Alerting (Cloze-Guard)

Cloze-Guard monitors conversations for safety-relevant content and surfaces events to the supervising provider. The shipped version flags messages against a provider-configured keyword list, raises alerts in the provider dashboard, and can send email notifications. Each provider enables and configures it in their settings, and it operates independently of the universal crisis-protocol prompt layer (which is always active).

### Reports

Generated when a chat window closes. Both **summary** and **detailed** versions are produced. Components run independently and degrade gracefully if dependencies are unavailable:

- **AI Summary** — LLM-generated clinical narrative (requires Ollama)
- **Descriptive Stats** — message counts, durations, averages
- **NLP Analysis** — sentiment, active/passive voice, emotional keywords
- **Co-occurrence Analysis** — word network graph (matplotlib + networkx)
- **Saved Messages** — participant-flagged quotes from conversations

Download as HTML or PDF in either summary or detailed format.

### Roles

- **Participant** — has conversations, completes their safety-plan sections, views their own reports.
- **Provider** (researcher/clinician) — designs study flows, windows, and templates; configures models, prompts, and Cloze-Guard; reviews safety plans, conversations, reports, and safety alerts for assigned participants.
- **Administrator** — user management, platform settings, and the audit log.

> **A note on naming.** This README and the accompanying paper use **participant**; in the codebase that role is `user` (historically `patient`), and some model, route, and template names still read `patient`. They denote the same role.

### Research & IRB support

Features supporting human-subjects research:

- **De-identified participants** — auto-generated credentials; no name or personal email required.
- **Consent capture** — a per-study disclaimer modal participants acknowledge before conversations begin; acknowledgment is timestamped and logged.
- **Audit logging** — administrative actions (account creation, prompt edits, password resets, feature-flag changes) are recorded with timestamp and actor.
- **Data isolation** — one-provider-per-participant assignment enforced at the database level, with role-based access throughout.

## Deployment

Cloze runs as a standard Flask application. Two common setups:

- **Cloud** — a VM (e.g., AWS EC2) with managed PostgreSQL (e.g., AWS RDS), served by Gunicorn behind a reverse proxy. The reference deployment runs on EC2 behind Cloudflare, managed by `systemd`.
- **Local / on-premises** — a single machine with SQLite or local PostgreSQL and Ollama for model hosting; no cloud dependencies.

A Dockerfile is also provided:

```bash
docker build -t cloze-app .
docker run -p 5051:5001 --env-file .env cloze-app
```

Schema changes are applied separately with `python migrate_schema.py --apply` (deploys do not run migrations automatically).

## License

Cloze is released under the [GNU Affero General Public License v3.0](LICENSE). You are free to use, study, modify, and self-host it. The AGPL's network clause means that if you run a modified version of Cloze as a network service, you must make your modified source available to its users under the same license.

Copyright © 2024–2026 Francesco Cipriani, Matthew Flathers. See [NOTICE](NOTICE).
