# 🚀 Netlify Staging Deployment & Operations Guide: MailMind AI

This guide documents the architecture, configuration, environment setup, database migrations, worker orchestration, and verification procedures for deploying **MailMind AI** to **Netlify** as the unified staging platform.

---

## 🏛️ System Architecture

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                            Netlify Edge Network                             │
│                                                                             │
│  Browser / Client ───► https://<your-staging-domain>.netlify.app            │
│       │                                                                     │
│       ├─── /api/* ────────► Netlify Functions (AWS Lambda Python 3.11)      │
│       │                      • WSGI Adapter (netlify/functions/api.py)      │
│       │                      • Flask Web Application                        │
│       │                      • Cookie Session Management (mailmild_session) │
│       │                      • Enqueues durable AIAnalysisJob               │
│       │                                                                     │
│       └─── /* (All other) ─► Netlify High-Performance CDN                   │
│                              • React 19 + Vite Production Bundle            │
│                              • Client-side SPA routing (index.html fallback)│
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                                       ▼
             ┌──────────────────────────────────────────────────┐
             │            Hosted PostgreSQL Database            │
             │           (Neon / Supabase / AWS RDS)            │
             │  • 100% Durable schema (f6b2c3d4e5f6 head)       │
             │  • Durable Queue: ai_analysis_jobs               │
             │  • Atomic claiming: SELECT FOR UPDATE SKIP LOCKED│
             │  • Multi-user isolation & foreign key cascades   │
             └─────────────────────────┬────────────────────────┘
                                       │
                                       ▼
             ┌──────────────────────────────────────────────────┐
             │       Standalone AI Worker (worker.py)           │
             │   (Render Background Worker / VM / Container)    │
             │  • Claims jobs atomically via lease tokens       │
             │  • Executes Gemini analysis outside DB locks     │
             │  • Enforces exponential backoff & max 3 retries  │
             │  • Recovers stale jobs automatically             │
             └──────────────────────────────────────────────────┘
```

---

## ⚠️ Staging Database Requirement

> [!IMPORTANT]
> **NO EPHEMERAL SQLITE FOR REAL STAGING**
> Serverless instances on Netlify Functions are stateless and ephemeral. Local filesystem paths like `/tmp/mail_assistant.db` are destroyed on cold starts and cannot be shared across concurrent function instances.
> 
> **For real staging, `DATABASE_URL` MUST point to a hosted PostgreSQL database.**
> Supported cloud providers include:
> - [Neon](https://neon.tech) (Serverless PostgreSQL with connection pooling)
> - [Supabase](https://supabase.com) (Managed PostgreSQL)
> - [Render PostgreSQL](https://render.com)
> - [AWS RDS PostgreSQL](https://aws.amazon.com/rds/postgresql/)
> 
> If no hosted PostgreSQL instance is configured, the staging environment reports **STAGING DATABASE REQUIRED** and will fail production validation.

---

## 📋 Netlify Dashboard Environment Variables

Configure these environment variables in your Netlify site settings (**Site configuration** $\rightarrow$ **Environment variables**):

| Variable | Required | Production Value / Description |
| :--- | :---: | :--- |
| `FLASK_ENV` | **Yes** | `production` (enforces strict security validation) |
| `SECRET_KEY` | **Yes** | Cryptographically strong random string (>= 16 chars) for signing session cookies |
| `ENCRYPTION_KEY` | **Yes** | 32-byte Fernet base64 string for encrypting OAuth tokens at rest |
| `DATABASE_URL` | **Yes** | Hosted PostgreSQL URI (`postgresql://user:password@host/dbname?sslmode=require`) |
| `GEMINI_API_KEY` | **Yes** | Google Gemini API Key |
| `GEMINI_MODEL` | No | `gemini-3.6-flash` (or `gemini-2.0-flash`) |
| `GOOGLE_CLIENT_ID` | Yes (for Gmail) | Google Cloud Console OAuth 2.0 Web Client ID |
| `GOOGLE_CLIENT_SECRET`| Yes (for Gmail) | Google Cloud Console OAuth 2.0 Web Client Secret |
| `GOOGLE_REDIRECT_URI` | Yes (for Gmail) | `https://<your-site>.netlify.app/api/auth/google/callback` |
| `FRONTEND_URL` | Yes | `https://<your-site>.netlify.app` |
| `AI_JOB_ALWAYS_EAGER` | No | `false` (preserves durable background queue in PostgreSQL) |
| `CREATE_DB_TABLES_ON_STARTUP` | No | `false` (schema managed exclusively by Alembic migrations) |
| `SESSION_COOKIE_SECURE` | Yes | `true` (enforces HTTPS-only cookies in production) |

---

## 🛠️ Step-by-Step Staging Deployment

### 1. Push Repository to GitHub
Ensure the latest code including `netlify.toml`, `package.json`, `scripts/prepare-netlify.js`, and `netlify/functions/api.py` is committed and pushed to your remote GitHub repository.

### 2. Connect Site in Netlify
1. Log into [Netlify](https://app.netlify.com).
2. Click **Add new site** $\rightarrow$ **Import an existing project**.
3. Authorize GitHub and select the `Mail` / `MailMind` repository.
4. Netlify will automatically detect `netlify.toml` with the following pre-configured build settings:
   - **Base directory**: (leave blank / root)
   - **Build command**: `npm run build:netlify`
   - **Publish directory**: `frontend/dist`
   - **Functions directory**: `netlify/functions`

### 3. Apply Alembic Migrations to Hosted Database
Before the first deployment, run database migrations against your hosted PostgreSQL instance:

```bash
# Set your hosted PostgreSQL URL
export DATABASE_URL="postgresql://user:password@host:5432/dbname?sslmode=require"

# Navigate to backend and apply all migrations to head
cd backend
flask db upgrade

# Verify single head matches f6b2c3d4e5f6
flask db current
```

### 4. Configure Google Cloud OAuth Callback
In your [Google Cloud Console](https://console.cloud.google.com/apis/credentials):
1. Navigate to **APIs & Services** $\rightarrow$ **Credentials**.
2. Edit your OAuth 2.0 Web Client.
3. Under **Authorized JavaScript origins**, add:
   ```text
   https://<your-staging-site>.netlify.app
   ```
4. Under **Authorized redirect URIs**, add:
   ```text
   https://<your-staging-site>.netlify.app/api/auth/google/callback
   ```
5. Click **Save**.

### 5. Start Background AI Worker
The durable PostgreSQL AI queue (`ai_analysis_jobs`) requires a worker process to claim and process jobs using atomic `SELECT FOR UPDATE SKIP LOCKED` and lease tokens.

Deploy `worker.py` on a background service (e.g., Render Background Worker, Railway, Fly.io, or an AWS EC2/ECS instance) with the identical `DATABASE_URL`, `GEMINI_API_KEY`, and `ENCRYPTION_KEY`:

```bash
# Run standalone background worker
python worker.py
```

---

## 🔍 Verification & Health Checks

Once deployed, verify the staging deployment against these live endpoints:

### 1. Liveness & Readiness Probes
```bash
# Verify process health
curl -I https://<your-site>.netlify.app/api/health
# Expected: 200 OK, {"status": "healthy"}

# Verify database connectivity
curl -i https://<your-site>.netlify.app/api/ready
# Expected: 200 OK, {"status": "ready", "database": "connected"}

# Verify queue health
curl -i https://<your-site>.netlify.app/api/queue/health
# Expected: 200 OK, {"status": "healthy", "queue": {...}}
```

### 2. Cookie Security Inspection
Inspect response headers from `/api/auth/login`:
```http
Set-Cookie: mailmild_session=...; Path=/; HttpOnly; Secure; SameSite=Lax
```
- `HttpOnly`: Enforces protection against client-side script access.
- `Secure`: Enforces HTTPS-only transmission.
- `SameSite=Lax`: Prevents CSRF while allowing top-level navigation.

### 3. Security Headers Inspection
Inspect response headers from any route:
```http
X-Content-Type-Options: nosniff
X-Frame-Options: SAMEORIGIN
Referrer-Policy: strict-origin-when-cross-origin
Content-Security-Policy: default-src 'self'; ...
Strict-Transport-Security: max-age=31536000; includeSubDomains
```

---

## 🔄 Rollback Procedures

### 1. Application Rollback (Netlify Instant Rollback)
Netlify preserves every production and preview deployment as an immutable snapshot:
1. In the Netlify Dashboard, navigate to **Deploys**.
2. Locate the previous known-good deployment.
3. Click **Publish deploy**.
4. Rollback takes effect globally across the CDN within seconds with zero downtime.

### 2. Database Migration Rollback (Alembic Downgrade)
If an application rollback requires schema reversion, execute Alembic downgrade targeting the previous revision:

```bash
cd backend
export DATABASE_URL="postgresql://..."
flask db downgrade <target-revision-id>
flask db current
```

---

## 🛡️ Security Invariants Maintained

- **Least-Privilege Scopes**: Strictly `openid`, `userinfo.email`, `userinfo.profile`, `gmail.readonly`. Zero write/send/modify scopes.
- **Calendar Protection**: Zero autonomous Google Calendar write operations.
- **Action Confirmation**: Mandatory explicit user confirmation boundary for bulk tasks and calendar meetings.
- **Secret Redaction**: Automatic scrubbing of Gemini API keys, OAuth tokens, and encryption keys from logs and API error responses.
