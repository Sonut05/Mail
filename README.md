# 📬 MailMild — Smart AI Email Assistant & Productivity Platform

**MailMild** (also branded as **MailMind AI**) is a modern, enterprise-ready email intelligence and productivity platform. It seamlessly connects raw Gmail inboxes with generative AI comprehension, human decision-making, and schedule management.

```text
               ┌───────────────────────────────────────────┐
               │         Connected Gmail Accounts          │
               └─────────────────────┬─────────────────────┘
                                     │ Google OAuth 2.0 (gmail.readonly)
                                     ▼
               ┌───────────────────────────────────────────┐
               │   Mailbox Sync Engine (sync_service.py)   │
               │   • Initial Full Sync (bounded batches)   │
               │   • Incremental Sync (via historyId)      │
               └─────────────────────┬─────────────────────┘
                                     │ MIME parse & upsert
                                     ▼
               ┌───────────────────────────────────────────┐
               │    Local Storage: EmailMessage (SQLite)   │
               │      (Completely decoupled from AI)       │
               └─────────────────────┬─────────────────────┘
                                     │ Async / On-Demand
                                     ▼
               ┌───────────────────────────────────────────┐
               │   Gemini 2.0 AI Intelligence Engine       │
               │   • Summary & Action Required             │
               │   • Category, Priority, Sentiment         │
               │   • Deadline & Entity Extraction          │
               │   • Proposed Tasks & Calendar Events      │
               └─────────────────────┬─────────────────────┘
                                     │ Suggestions ONLY
                                     ▼
                      ╔═════════════════════════════╗
                      ║     HUMAN CONFIRMATION      ║
                      ║   (No autonomous writes)    ║
                      ╚══════════════╤══════════════╝
                                     │ User Confirms
                     ┌───────────────┴───────────────┐
                     ▼                               ▼
        ┌─────────────────────────┐     ┌─────────────────────────┐
        │       Smart Tasks       │     │     Calendar Events     │
        │ • Status Lifecycle      │     │ • Time Validation       │
        │ • Deadline Inheritance  │     │ • Conflict Detection    │
        │ • Urgency Badges        │     │ • Meeting Link Capture  │
        │ • Duplicate Guard       │     │ • Non-blocking Warnings │
        └────────────┬────────────┘     └────────────┬────────────┘
                     │                               │
                     └───────────────┬───────────────┘
                                     ▼
               ┌───────────────────────────────────────────┐
               │      Unified Productivity Dashboard       │
               │ • Metrics, Deadlines & Agenda Views       │
               │ • Interactive Three.js 3D Visual Core     │
               └───────────────────────────────────────────┘
```

> **Guiding Architectural Rule**: AI provides suggestions and intelligence **only**. Tasks and calendar events are **never** autonomously written to the database without explicit human confirmation.

---

## 🌟 Key Features by System Phase

### 1. Gmail Synchronization Engine (Phases 1, 2 & 3)
* **Google OAuth 2.0 Authentication**: Secure OAuth flow with cryptographically signed, timed CSRF state tokens (`itsdangerous`).
* **Zero Risky Scopes**: Adheres strictly to the principle of least privilege (`openid`, `userinfo.email`, `userinfo.profile`, `gmail.readonly`). No calendar write scopes or broad admin scopes required.
* **Token Security at Rest**: OAuth access and refresh tokens are encrypted at rest using symmetric 128-bit AES in CBC mode with HMAC SHA-256 (`cryptography.fernet`). Plaintext tokens are never stored.
* **Initial Full Mailbox Sync**:
  * Paginates messages in bounded batches (25–50 messages).
  * Robust MIME extraction handles plain text, HTML, `multipart/alternative`, `multipart/mixed`, and nested email parts.
  * Idempotent persistence prevents duplicate records.
* **Incremental Synchronization (`historyId`)**:
  * Tracks mailbox delta changes since the last sync cursor.
  * Captures `messagesAdded`, `messagesDeleted`, `labelsAdded`, and `labelsRemoved`.
  * **Exhaustive History Pagination**: Follows `nextPageToken` until `None` before advancing the stored `historyId`, ensuring no changes are dropped.
  * **Resync Safety**: Detects expired history IDs (`404` or `INVALID_ARGUMENT`) and automatically triggers or guides a clean resync.
* **Sync-AI Decoupling**: Mailbox ingestion operates completely independently of the AI layer. AI API rate limits or network hiccups will never disrupt email sync.
* **Multi-Account Support**: Connect multiple Gmail accounts per user; disconnect anytime with automatic token revocation at Google's OAuth endpoint.

---

### 2. Email Intelligence & AI Comprehension (Phase 4)
* **Google Gemini 2.0 Integration**: Enriches emails using Gemini 2.0 Flash (`gemini-2.0-flash` / `gemini-3.6-flash`) with structured JSON schema outputs.
* **Resilient Heuristic Fallback Engine**: If the Gemini API key is missing or quota is exceeded, an intelligent local rule-based fallback automatically classifies emails, extracts deadlines, and parses meeting links, ensuring the platform never crashes.
* **Prompt Injection Defense**: Incoming email text is sanitized, bounded within explicit delimiters, and treated strictly as untrusted data.
* **Extracted Intelligence Fields**:
  * **Category Classification**: `Work`, `Finance`, `Education`, `Recruitment`, `Social`, `Personal`, `Meeting`, `Support`, `Promotions`, `Updates`, `Other`.
  * **Priority Scoring**: `Urgent`, `High`, `Medium`, `Low`.
  * **Sentiment Analysis**: `Positive`, `Neutral`, `Negative` with confidence metrics.
  * **Executive Summary**: High-signal summary of lengthy email threads.
  * **Action Required Detection**: Identifies whether the email demands immediate user intervention.
  * **Deadline Extraction**: Automatically extracts explicit submission or response deadlines in ISO 8601 format.
  * **Named Entity Recognition (NER)**: Identifies people, organizations, locations, monetary amounts, and dates.
  * **Smart Replies**: Generates contextual draft replies with selectable tones (`Professional`, `Friendly`, `Direct`), complete with user editing, sending, and discarding capabilities.
* **Batch Analysis**: Analyze up to 20 emails simultaneously with concurrency safeguards.
* **Recopilot Form Autopilot**: Matches parsed resume profiles with incoming job/recruitment application emails to assist in autofilling registration forms.

---

### 3. Smart Tasks & Action Items (Phase 5)
* **Dual Creation Workflow**: Create manual tasks directly or convert email-detected suggestions into tasks with one click.
* **Deadline Inheritance**: Email-linked tasks inherit the email's AI deadline (`EmailMessage.ai_deadline`) if an explicit due date is not specified. Explicit user dates always take precedence.
* **Duplicate Confirmation Guard**: Protects against duplicate task creation if an AI suggestion is confirmed multiple times (returns `409 Conflict` for identical title + email, while allowing multiple distinct tasks per email).
* **Task Lifecycle Management**: Tracks tasks across `pending`, `in_progress`, `completed`, and `cancelled` states. Automatically records `completed_at` upon completion and clears it upon reopening.
* **Dynamic Urgency Badges**: Friendly, real-time status labels (`Overdue`, `Due Today`, `Due Tomorrow`, `Due in X days`, `No Deadline`).
* **Smart Sorting Algorithm**:
  $$\text{Overdue First} \longrightarrow \text{Urgent Priority} \longrightarrow \text{High Priority} \longrightarrow \text{Earliest Due Date} \longrightarrow \text{Remaining}$$
* **Flexible Filtering**: Filter task boards by `All`, `Pending`, `In Progress`, `Completed`, `Overdue`, `Due Today`, `Due This Week`, or priority level.
* **Source Email Traceability**: Directly navigate from any task card back to its originating email in the inbox.

---

### 4. Calendar Intelligence & Conflict Detection (Phase 5)
* **Manual & Email-Linked Scheduling**: Schedule events manually or confirm AI-extracted meeting suggestions with extracted dates, times, and attendees.
* **Meeting Link Extraction**: Automatically extracts Google Meet, Zoom, Microsoft Teams, and Webex meeting URLs.
* **Server-Side Time Validation**: Strictly verifies that event end time is after start time (`end > start`), returning `400 Bad Request` on invalid times.
* **Real-Time Schedule Conflict Engine**: Checks for overlapping events for the user:
  $$\text{new\_start} < \text{existing\_end} \quad \text{AND} \quad \text{new\_end} > \text{existing\_start}$$
* **Non-Blocking Conflict Alerts**: Notifies the user of overlapping event titles and time ranges without forcibly blocking scheduling.
* **Self-Conflict Exclusion**: Updating an existing event automatically excludes itself from conflict checks.
* **Source Email Traceability**: Jump directly to the originating email from any scheduled event card.

---

### 5. Multi-User Tenant Isolation
* **Strict Ownership Scoping**: Every database query and API mutation is scoped to the authenticated user's ID (`user_id`).
* **Cross-User Protection**: User A cannot view, edit, or delete User B's emails, tasks, calendar events, or dashboard metrics.
* **Cross-User Linking Prevention**: Attempting to attach a task or event to an email owned by another user is strictly rejected with `403 Forbidden`.

---

### 6. Interactive Dashboard & Productivity Analytics
* **Live Operational Metrics**: Real-time counters for Emails Summarized, Time Saved, Priority Pending items, and AI Core activity.
* **Task Productivity Breakdown**: Visual distribution of Pending, In Progress, Completed, and Overdue tasks.
* **Upcoming Deadlines Timeline**: Chronological agenda of impending task commitments.
* **Upcoming Events Schedule**: Agenda view of upcoming meetings and deadlines.
* **Category & Priority Distribution**: Visual breakdown of incoming email topics.
* **Three.js Visual Core**: Interactive 3D ambient particle sphere reflecting real-time AI processing status.

---

## 🛠️ Technology Stack

| Layer | Technology | Details |
| :--- | :--- | :--- |
| **Backend Framework** | Python 3.10+, Flask 3.1, Gunicorn | Lightweight, fast REST API server |
| **ORM & Database** | SQLAlchemy 3.1, SQLite / PostgreSQL | Robust relational modeling with Alembic batch migrations |
| **Database Migrations** | Flask-Migrate 4.1 (Alembic) | Version-controlled database schema migrations |
| **Security & Auth** | Google OAuth 2.0, Fernet AES-128, bcrypt | Industry-standard encryption & password hashing |
| **AI Comprehension** | Google Gemini API (`gemini-2.0-flash`) | Structured JSON email intelligence & replies |
| **PDF Processing** | `pypdf` 5.1 | Resume extraction and parsing for Recopilot |
| **Frontend Framework** | React 19, Vite 6, React Router v7 | Blazing-fast SPA with Hot Module Replacement |
| **Styling & UI** | Vanilla CSS (Glassmorphism design system) | Pure CSS variables, dark mode, Lucide React icons |
| **3D Graphics** | Three.js | Ambient 3D particle sphere visualizer |
| **Testing** | Pytest, Unittest | 82 automated backend test cases (100% passing) |

---

## 📁 Repository Structure

```text
Mail/
├── DEPLOYMENT.md                     # Production deployment guide (Render, Heroku, VPS)
├── README.md                         # Complete project documentation
├── backend/
│   ├── run.py                        # Backend application entry point (port 5000)
│   ├── requirements.txt              # Python dependencies
│   ├── .env                          # Local environment secrets & credentials
│   ├── .env.example                  # Template for environment configuration
│   ├── instance/
│   │   └── mail_assistant.db         # Local SQLite database
│   ├── migrations/                   # Alembic database migration versions
│   │   └── versions/
│   │       ├── dfccaaaa782e_baseline_schema.py
│   │       ├── b5ebee75f549_add_phase2_email_message_sync_fields.py
│   │       ├── 1e3c96d0b0a0_add_phase4_email_intelligence_fields.py
│   │       └── 28814bc4372b_phase5_smart_tasks_calendar.py
│   ├── app/
│   │   ├── __init__.py               # Flask app factory (registers blueprints, CORS, static hosting)
│   │   ├── config.py                 # Configuration class & environment loader
│   │   ├── extensions.py             # SQLAlchemy & Migrate instances
│   │   ├── models/                   # Relational database models
│   │   │   ├── __init__.py
│   │   │   ├── user.py               # User account credentials & profile
│   │   │   ├── connected_email_account.py # OAuth tokens, sync state, historyId
│   │   │   ├── email_message.py      # Synced messages & AI intelligence fields
│   │   │   ├── task.py               # Tasks, deadlines, statuses, user/email relations
│   │   │   ├── calendar_event.py     # Calendar events, time ranges, meeting URLs
│   │   │   ├── entity.py             # Extracted NER entities
│   │   │   └── reminder.py           # Reminder notifications
│   │   ├── routes/                   # REST API Blueprints
│   │   │   ├── __init__.py
│   │   │   ├── auth.py               # Local auth, Google OAuth login/callback, session /me
│   │   │   ├── mail_accounts.py      # Account management, full & incremental sync triggers
│   │   │   ├── emails.py             # Email listing, single email view, batch AI analysis, replies
│   │   │   ├── tasks.py              # Task CRUD, lifecycle filters, complete, reopen
│   │   │   ├── calendar.py           # Calendar CRUD, conflict detection, time validation
│   │   │   ├── dashboard.py          # Aggregated productivity metrics & statistics
│   │   │   └── resume.py             # Recopilot resume parsing & autofill
│   │   └── services/                 # Core business logic & integrations
│   │       ├── gmail_service.py      # Low-level Gmail API client & reply sender
│   │       ├── sync_service.py       # Full & incremental sync engines, MIME parsers
│   │       ├── ai_service.py         # Gemini API prompt engineering & heuristic fallback
│   │       ├── encryption.py         # Fernet token encryption/decryption
│   │       └── resume_service.py     # Resume extraction & form-field matching
│   └── tests/                        # Comprehensive test suite (82 tests)
│       ├── conftest.py               # Pytest fixtures, test database setup
│       ├── test_auth.py              # Local auth & Google OAuth tests
│       ├── test_phase2_sync.py       # Initial mailbox sync tests
│       ├── test_phase3_incremental.py# historyId sync & pagination safety tests
│       ├── test_phase4_ai.py         # Gemini intelligence & prompt injection tests
│       └── test_phase5_tasks_calendar.py # Task lifecycle, conflicts, and multi-user isolation
└── frontend/
    ├── index.html                    # Frontend HTML template
    ├── package.json                  # Node.js dependencies and build scripts
    ├── vite.config.js                # Vite development server and API proxy config
    ├── dist/                         # Compiled production assets
    └── src/
        ├── main.jsx                  # React application entry point
        ├── App.jsx                   # Layout, top-level routing, navigation
        ├── context/
        │   └── AppContext.jsx        # Global reactive state (auth, emails, tasks, events, sync)
        ├── services/
        │   └── api.js                # Unified Axios/Fetch API client
        ├── pages/
        │   ├── Dashboard.jsx         # Executive overview, productivity stats, 3D Core
        │   ├── Inbox.jsx             # Email split-view, AI analysis panel, related tasks/events
        │   ├── TaskBoard.jsx         # Task board, filters, manual creation & edit modals
        │   ├── CalendarView.jsx      # Agenda schedule, conflict warnings, event modals
        │   ├── Settings.jsx          # Gmail account connection, resume profiles, preferences
        │   └── Auth.jsx              # Login, registration, Google OAuth entry
        ├── components/               # Reusable UI widgets (Sidebar, TopNav, ThreeCore)
        └── styles/
            └── index.css             # Unified CSS design system (glassmorphism, animations)
```

---

## 🚀 Getting Started

### 1. Prerequisites
* **Python**: 3.10 or higher
* **Node.js**: v18 or higher (with `npm`)
* **Google Cloud Console Credentials**: OAuth 2.0 Web Client ID and Secret with Gmail API enabled.
* **Google Gemini API Key**: From Google AI Studio (optional for basic testing; intelligent local fallback is built-in).

---

### 2. Backend Installation & Setup

1. **Navigate to the backend directory**:
   ```bash
   cd backend
   ```

2. **Create and activate a virtual environment**:
   ```bash
   # Windows (PowerShell)
   python -m venv venv
   .\venv\Scripts\Activate.ps1

   # macOS / Linux
   python3 -m venv venv
   source venv/bin/activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure Environment Variables**:
   Create a `.env` file in the `backend/` directory:
   ```ini
   FLASK_APP=run.py
   FLASK_ENV=development
   SECRET_KEY=generate-a-secure-random-secret-key
   ENCRYPTION_KEY=generate-a-32-byte-base64-fernet-key
   SQLALCHEMY_DATABASE_URI=sqlite:///instance/mail_assistant.db

   # Google OAuth 2.0 Credentials
   GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
   GOOGLE_CLIENT_SECRET=your-client-secret
   GOOGLE_REDIRECT_URI=http://localhost:5000/api/auth/google/callback

   # Google Gemini API
   GEMINI_API_KEY=your-gemini-api-key
   GEMINI_MODEL=gemini-2.0-flash

   # Frontend URL (for OAuth redirect)
   FRONTEND_URL=http://localhost:3000
   ```

   *Generate a valid Fernet encryption key:*
   ```bash
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```

5. **Apply Database Migrations**:
   ```bash
   flask db upgrade
   ```

6. **Start the Flask Backend**:
   ```bash
   python run.py
   ```
   *The backend will be running on `http://127.0.0.1:5000`.*

---

### 3. Frontend Installation & Setup

1. **Navigate to the frontend directory**:
   ```bash
   cd frontend
   ```

2. **Install Node.js packages**:
   ```bash
   npm install
   ```

3. **Start the Vite Development Server**:
   ```bash
   npm run dev
   ```
   *The frontend application will be live at `http://localhost:3000`.*

4. **Compile for Production**:
   ```bash
   npm run build
   ```
   *Compiles minified production bundles into `frontend/dist/`, which Flask can serve directly in production.*

---

## 🧪 Running Automated Tests

MailMild includes an extensive suite of 82 automated tests covering all 5 architectural phases:

```bash
cd backend
pytest -q
```

### Test Coverage Breakdown:
| Test Suite | Coverage & Scope |
| :--- | :--- |
| `test_auth.py` | Local auth, registration, token encryption/decryption, session validation, OAuth state signature |
| `test_phase2_sync.py` | Initial mailbox ingestion, MIME decoding, multipart payload parsing, idempotent storage |
| `test_phase3_incremental.py` | Incremental sync using `historyId`, exhaustive pagination, label tracking, expired history recovery |
| `test_phase4_ai.py` | Gemini 2.0 email intelligence, structured output parsing, smart replies, prompt injection defense |
| `test_phase5_tasks_calendar.py` | Manual tasks, lifecycle transitions, overdue calculations, calendar conflicts, end > start validation, deadline inheritance, and multi-user isolation |

*All 82 tests pass cleanly with 100% regression stability.*

---

## 📡 Complete API Reference

### 🔐 Authentication (`/api/auth`)
| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `POST` | `/api/auth/register` | Register a new user (`email`, `password`, `name`, `contact_no`) |
| `POST` | `/api/auth/login` | Local email and password login |
| `POST` | `/api/auth/logout` | Clears active server-side session |
| `GET` | `/api/auth/me` | Retrieves the currently authenticated user session |
| `GET` | `/api/auth/google/login` | Generates cryptographically signed state and redirects to Google OAuth |
| `GET` | `/api/auth/google/callback` | Exchanges authorization code, creates/links user, and encrypts OAuth tokens |

---

### 📬 Mail Accounts & Synchronization (`/api/mail`)
| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/api/mail/accounts` | Lists connected accounts with safe metadata (no tokens) |
| `POST` | `/api/mail/sync` | Triggers initial full mailbox sync (background thread or synchronous with `?sync_now=true`) |
| `POST` | `/api/mail/sync/incremental` | Triggers incremental sync via `historyId` (background thread or synchronous) |
| `GET` | `/api/mail/sync-status` | Retrieves real-time sync status (`idle`, `syncing`, `completed`), progress, and `messages_synced` |
| `POST` | `/api/mail/disconnect` | Disconnects account and revokes OAuth token with Google |

---

### ✉️ Email Intelligence (`/api/emails`)
| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/api/emails` | Paginated email listing (supports `category`, `priority`, `needs_human_review`, `page`, `per_page`) |
| `GET` | `/api/emails/<id>` | Full email details with related tasks, calendar events, and extracted entities |
| `POST` | `/api/emails/<id>/analyze` | Runs Gemini AI analysis on a single email with concurrency protection |
| `POST` | `/api/emails/analyze` | Batch analyzes up to 20 emails simultaneously (`email_ids` or `limit`) |
| `POST` | `/api/emails/<id>/approve` | Approves and transmits AI-drafted reply via Gmail API |
| `POST` | `/api/emails/<id>/discard` | Discards the AI-drafted reply |
| `POST` | `/api/emails/<id>/read` | Marks an email as reviewed (`needs_human_review = False`) |
| `POST` | `/api/emails/generate-reply` | Standalone AI reply generator for arbitrary email body text |

---

### 📋 Smart Tasks (`/api/tasks`)
| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/api/tasks` | Lists tasks with filters (`status`, `overdue`, `due_today`, `due_this_week`, `priority`, `email_id`, `sort_by`) |
| `POST` | `/api/tasks` | Creates manual or email-linked task (with deadline inheritance & duplicate guard) |
| `GET` | `/api/tasks/<id>` | Retrieves task detail with linked source email metadata |
| `PATCH` | `/api/tasks/<id>` | Updates task fields (`title`, `description`, `priority`, `status`, `due_date`) |
| `POST` | `/api/tasks/<id>/complete` | Marks task as completed (`status="completed"`, records `completed_at`) |
| `POST` | `/api/tasks/<id>/reopen` | Reopens task (`status="in_progress"`, clears `completed_at`) |
| `DELETE` | `/api/tasks/<id>` | Deletes task without deleting the originating email |

---

### 📅 Calendar Intelligence (`/api/calendar`)
| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/api/calendar` | Lists scheduled events ordered by start time |
| `POST` | `/api/calendar` | Creates event with validation (`end > start`) and conflict detection |
| `GET` | `/api/calendar/<id>` | Retrieves event detail with linked source email metadata |
| `PATCH` | `/api/calendar/<id>` | Updates event with conflict detection (excluding the event itself) |
| `DELETE` | `/api/calendar/<id>` | Deletes event without deleting the originating email |

---

### 📊 Dashboard & Metrics (`/api/dashboard`)
| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/api/dashboard/stats` | Aggregated statistics for email volumes, task lifecycle, upcoming deadlines, agenda, and AI activity |

---

### 📄 Recopilot Resume Autopilot (`/api/resume`)
| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/api/resume/profiles` | Lists user's stored resume autopilot profiles |
| `POST` | `/api/resume/profiles` | Uploads and parses PDF/text resume to extract candidate profile |
| `DELETE` | `/api/resume/profiles/<id>`| Deletes a resume profile |
| `POST` | `/api/resume/autofill` | Matches profile against job application emails to generate autofill mappings |

---

## 🔒 Security & Privacy Architecture

1. **Token Cryptography**: All OAuth tokens are encrypted using Fernet (AES-128-CBC + HMAC-SHA256). The encryption key is stored strictly in server environment variables.
2. **Session Security**: Server-side session cookies configured with `HttpOnly`, `SameSite=Lax`, and secure context compliance.
3. **Multi-Tenant Scoping**: All database operations include strict `user_id` clauses to prevent horizontal privilege escalation.
4. **Human-in-the-Loop Constraint**: The AI layer produces structured recommendations only. Database mutations for tasks, calendar events, and external email transmissions require explicit human confirmation.
5. **No Google Calendar Scopes Required**: Calendar scheduling is managed securely within the MailMild ecosystem, avoiding unnecessary third-party permissions.

---

## 🚢 Production Deployment & Phase 6.1 Worker Architecture

MailMild is architected for a two-process production architecture with an asynchronous durable queue:

```text
                 ┌───────────────┐
HTTP ───────────►│ Flask/Gunicorn│
                 └───────┬───────┘
                         │ Enqueues AIAnalysisJob
                         ▼
                  PostgreSQL Queue
                   (Partial Unique Index & Row Locks)
                         │
                         ▼
                 ┌───────────────┐
                 │   AI Worker   │  (python worker.py)
                 └───────┬───────┘
                         │ Gemini API outside DB lock
                         ▼
                       Gemini
```

### 1. Local Development
Run the local Flask development server:
```bash
cd backend
python run.py
```
By default in development/test mode, jobs can execute eagerly or through the standalone worker process.

### 2. Standalone AI Worker Process
The AI analysis queue is decoupled from the web application and executed by independent worker processes:
```bash
cd backend
python worker.py
```
Or as a Python module:
```bash
python -m worker
```

**Worker Properties**:
* **Atomic Claiming**: Uses `SELECT ... FOR UPDATE SKIP LOCKED` on PostgreSQL so multiple concurrent workers never claim or process the same email.
* **Lease Token Ownership**: Every claimed job receives a unique cryptographically-random lease token. Even if a worker experiences network lag, a recovered job will reject late writes from stale workers.
* **Stale Job Recovery**: Crashed workers or abandoned jobs are automatically recovered after `AI_JOB_STALE_SECONDS` (default: 300s).
* **Exponential Backoff**: Transient AI failures retry automatically up to `AI_JOB_MAX_ATTEMPTS` (strictly capped at 3 attempts: attempt 1 -> 5s backoff, attempt 2 -> 15s backoff, attempt 3 -> permanent failure).
* **Graceful Shutdown**: Handles `SIGTERM` and `SIGINT` cleanly, waiting for active jobs to finish or yield before exiting.

### 3. PostgreSQL Concurrency Requirements
PostgreSQL is **mandatory** for production durability and concurrency guarantees:
1. **Partial Unique Index**: `uq_active_ai_job_per_email` on `ai_analysis_jobs(email_id)` where `status IN ('pending', 'processing')` guarantees at the database level that an email has at most one active job regardless of concurrent API requests.
2. **Row-level Skip Locked**: Native `FOR UPDATE SKIP LOCKED` enables seamless horizontal scaling of multiple worker processes without contention.

### 4. Environment Configuration
Add to your production `.env`:
```ini
AI_JOB_POLL_INTERVAL=1.0
AI_JOB_STALE_SECONDS=300
AI_JOB_MAX_ATTEMPTS=3
AI_WORKER_ID=worker-prod-1
AI_JOB_ALWAYS_EAGER=false
```

Detailed instructions for deploying to **Render**, **Heroku**, or an **Ubuntu VPS (Nginx + Gunicorn)** are available in [DEPLOYMENT.md](file:///c:/Users/sonut/OneDrive/Desktop/Mail/DEPLOYMENT.md).

Quick summary for Render:
* **Web Service**:
  * **Build Command**: `cd frontend && npm install && npm run build && cd ../backend && pip install -r requirements.txt`
  * **Start Command**: `cd backend && gunicorn "app:create_app()"`
* **Background Worker Service**:
  * **Start Command**: `cd backend && python worker.py`

---

## 📄 License

This project is licensed under the MIT License — see the repository files for details.
