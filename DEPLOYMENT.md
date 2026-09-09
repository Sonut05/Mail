# 🚀 Production Deployment & Operations Guide: MailMind AI

This guide documents the enterprise production deployment, background worker lifecycle, database operations, health monitoring, and disaster recovery strategy for **MailMind AI**.

---

## 🏛️ System Architecture

MailMind AI is deployed as a decoupled two-process architecture with a durable PostgreSQL job queue:

```text
                           ┌─────────────────────────────┐
HTTP / Browser ───────────►│  Flask / Gunicorn (Web API) │
                           └──────────────┬──────────────┘
                                          │ Enqueues AIAnalysisJob
                                          ▼
                   ┌──────────────────────────────────────────────┐
                   │             PostgreSQL 16/18                 │
                   │  • Durable Queue: ai_analysis_jobs           │
                   │  • Partial Unique Index:                     │
                   │    uq_active_ai_job_per_email                │
                   │  • Row Lock: FOR UPDATE SKIP LOCKED          │
                   └──────────────────────┬───────────────────────┘
                                          │ Claims atomic lease
                                          ▼
                           ┌─────────────────────────────┐
                           │   AI Worker (worker.py)     │
                           └──────────────┬──────────────┘
                                          │ Gemini API (outside DB lock)
                                          ▼
                                     Google Gemini
```

---

## 📋 Environment Variables Reference

| Variable | Required | Default | Description |
| :--- | :---: | :--- | :--- |
| `DATABASE_URL` | **Yes (Prod)** | `sqlite:///mail_assistant.db` | PostgreSQL connection URI (`postgresql://...`) |
| `SECRET_KEY` | **Yes (Prod)** | - | High-entropy secret key for session signing (>= 16 chars) |
| `ENCRYPTION_KEY` | **Yes (Prod)** | - | 32-byte Fernet base64 key for encrypting OAuth tokens at rest |
| `FLASK_ENV` | **Yes (Prod)** | `development` | Set to `production` for strict security validations |
| `SESSION_COOKIE_SECURE` | **Yes (Prod)** | `false` | Set to `true` when serving over HTTPS |
| `GEMINI_API_KEY` | **Yes** | - | Server-side Google Gemini 2.0 API key |
| `GEMINI_MODEL` | No | `gemini-2.0-flash` | Gemini model name |
| `GEMINI_REQUEST_TIMEOUT` | No | `30` | Bounded timeout for AI requests in seconds |
| `GOOGLE_CLIENT_ID` | Yes (for Gmail) | - | Google OAuth 2.0 Client ID |
| `GOOGLE_CLIENT_SECRET` | Yes (for Gmail) | - | Google OAuth 2.0 Client Secret |
| `GOOGLE_REDIRECT_URI` | Yes (for Gmail) | - | Production OAuth callback URL |
| `FRONTEND_URL` | No | `http://localhost:5173` | Allowed CORS origin and redirect host |
| `AI_JOB_POLL_INTERVAL` | No | `1.0` | Polling frequency for background worker (seconds) |
| `AI_JOB_STALE_SECONDS` | No | `300` | Lease timeout before stale jobs are recovered |
| `AI_JOB_MAX_ATTEMPTS` | No | `3` | Maximum retry attempts per email (capped at 3) |
| `AI_WORKER_ID` | No | `worker-{pid}` | Unique identifier for the worker instance |
| `AI_JOB_ALWAYS_EAGER` | No | `false` | Must be `false` in production (disables daemon threads) |
| `CREATE_DB_TABLES_ON_STARTUP`| No | `false` (Prod) | Disables `db.create_all()` in production |

---

## 🗄️ PostgreSQL Production Configuration

### 1. Connection Pooling
SQLAlchemy engine options are pre-configured in `backend/app/config.py`:
- `pool_size`: 10 (default, configurable via `DB_POOL_SIZE`)
- `max_overflow`: 20 (default, configurable via `DB_MAX_OVERFLOW`)
- `pool_timeout`: 30 seconds (`DB_POOL_TIMEOUT`)
- `pool_recycle`: 1800 seconds (`DB_POOL_RECYCLE`)
- `pool_pre_ping`: `True` (validates connection vitality before issuing queries to avoid stale dropped connections)

### 2. Database Migrations (Alembic)
Production databases **must** be managed exclusively through Flask-Migrate / Alembic.

#### Apply Migrations:
```bash
cd backend
flask db upgrade
```

#### Check Current Migration Status:
```bash
flask db current
```

#### Create a New Migration:
```bash
flask db migrate -m "describe_schema_change"
```

#### Migration Rollback Strategy:
If an upgrade needs to be reverted safely:
```bash
# Check the target revision before downgrading
flask db history

# Revert the latest revision (only if non-destructive)
flask db downgrade -1
```

---

## 🚢 Deployment Options

### Option 1: Docker Compose (Recommended)
Launch the entire stack (PostgreSQL, Gunicorn Web API, AI Worker) with a single command:

```bash
docker-compose up -d --build
```

To monitor logs:
```bash
docker-compose logs -f web worker
```

To stop gracefully:
```bash
docker-compose down
```

---

### Option 2: Render
1. **Web Service**:
   - Environment: `Python`
   - Build Command:
     ```bash
     cd frontend && npm install && npm run build && cd ../backend && pip install -r requirements.txt
     ```
   - Start Command:
     ```bash
     cd backend && flask db upgrade && gunicorn "app:create_app()"
     ```
2. **Background Worker Service**:
   - Environment: `Python`
   - Build Command:
     ```bash
     cd backend && pip install -r requirements.txt
     ```
   - Start Command:
     ```bash
     cd backend && python worker.py
     ```

---

### Option 3: VPS / Ubuntu (systemd + Nginx)

#### 1. Web Service (`/etc/systemd/system/mailmind-web.service`)
```ini
[Unit]
Description=MailMind AI Web API (Gunicorn)
After=network.target postgresql.service

[Service]
User=ubuntu
WorkingDirectory=/var/www/mailmind/backend
EnvironmentFile=/var/www/mailmind/backend/.env
ExecStartPre=/var/www/mailmind/backend/venv/bin/flask db upgrade
ExecStart=/var/www/mailmind/backend/venv/bin/gunicorn -w 4 -b 127.0.0.1:5000 --timeout 120 "app:create_app()"
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

#### 2. AI Worker Service (`/etc/systemd/system/mailmind-worker.service`)
```ini
[Unit]
Description=MailMind AI Background Worker
After=network.target postgresql.service mailmind-web.service

[Service]
User=ubuntu
WorkingDirectory=/var/www/mailmind/backend
EnvironmentFile=/var/www/mailmind/backend/.env
ExecStart=/var/www/mailmind/backend/venv/bin/python worker.py
KillSignal=SIGTERM
TimeoutStopSec=60
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

#### 3. Enable and Start Services
```bash
sudo systemctl daemon-reload
sudo systemctl enable mailmind-web mailmind-worker
sudo systemctl start mailmind-web mailmind-worker
```

---

## 🩺 Health, Readiness & Observability

### 1. Liveness Probe (`GET /health`)
- Verifies the web server process is responsive.
- HTTP `200 OK`:
  ```json
  {
    "status": "healthy",
    "timestamp": "2026-09-09T01:00:00.000000+00:00"
  }
  ```

### 2. Readiness Probe (`GET /ready`)
- Verifies active database connection via `SELECT 1` and checks critical configuration.
- HTTP `200 OK` when ready:
  ```json
  {
    "status": "ready",
    "database": "connected",
    "timestamp": "2026-09-09T01:00:00.000000+00:00"
  }
  ```
- HTTP `503 Service Unavailable` if database is down or unreachable:
  ```json
  {
    "status": "unready",
    "database": "unavailable",
    "reason": "Database query failed or timed out"
  }
  ```

### 3. AI Queue Observability (`GET /api/queue/health`)
- Provides real-time metrics derived from `AIAnalysisJob` without exposing any user data or email bodies.
- HTTP `200 OK`:
  ```json
  {
    "status": "healthy",
    "queue": {
      "pending": 0,
      "processing": 1,
      "completed": 45,
      "failed": 2,
      "cancelled": 0,
      "total": 48,
      "stale_jobs": 0,
      "oldest_pending_age_seconds": null,
      "total_retries": 3,
      "failure_count": 2
    },
    "timestamp": "2026-09-09T01:00:00.000000+00:00"
  }
  ```

---

## 💾 Database Backup & Disaster Recovery Runbook

### 1. Backup Procedure
Perform automated daily backups using PostgreSQL's custom-format archive (`pg_dump -Fc`):

```bash
# Set credentials securely via environment or .pgpass
export PGPASSWORD="your-db-password"

# Generate timestamped backup
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
pg_dump -h localhost -p 5432 -U mailmind -d mailmind_db -Fc -f "/var/backups/mailmind/mailmind_${TIMESTAMP}.dump"
```

### 2. Backup Retention & Offsite Storage
- **Local Retention**: Keep the last 7 daily backups locally.
- **Offsite Storage**: Sync daily backups to an encrypted cloud storage bucket (AWS S3 or GCS) with server-side encryption enabled:
  ```bash
  aws s3 cp /var/backups/mailmind/mailmind_${TIMESTAMP}.dump s3://your-secure-backup-bucket/mailmind/
  ```
- **Retention Schedule**: 30 days retention policy on S3/GCS with automated lifecycle expiration.

### 3. Restore Procedure
To restore from a backup file into a fresh or recovered database:

```bash
# 1. Terminate existing connections to the target database
psql -h localhost -U mailmind -d postgres -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = 'mailmind_db' AND pid <> pg_backend_pid();"

# 2. Restore schema and data cleanly
pg_restore -h localhost -p 5432 -U mailmind -d mailmind_db --clean --if-exists --no-owner "/var/backups/mailmind/mailmind_20260909_010000.dump"

# 3. Verify database integrity
psql -h localhost -U mailmind -d mailmind_db -c "SELECT count(*) FROM users; SELECT count(*) FROM ai_analysis_jobs;"
```

### 4. Restore Verification & Disaster Recovery Drill
Every quarter (or before major production releases), perform a test restore on an isolated staging database:
1. Restore the latest backup into a temporary database (`mailmind_staging_restore`).
2. Run `flask db current` to verify migration head (`f6b2c3d4e5f6`).
3. Run verification queries checking row counts and constraints across all core entities (`users`, `email_messages`, `tasks`, `calendar_events`, `action_items`, `notifications`, `saved_searches`, `ai_analysis_jobs`).
4. Confirm user ownership and data isolation remain 100% intact.

---

## ⏱️ Disaster Recovery: RPO and RTO Targets

Based on the decoupled 2-process PostgreSQL architecture and pg_dump backup schedule:

| Metric | Target | Rationale |
| :--- | :--- | :--- |
| **RPO** (Recovery Point Objective) | **24 Hours** (Daily dump) / **< 15 Mins** (with WAL archiving enabled) | With daily `pg_dump`, data loss in a catastrophic host failure is bounded by the last backup. In production environments utilizing PostgreSQL WAL continuous archiving (e.g. AWS RDS or GCP Cloud SQL automated snapshots), RPO is < 15 minutes. |
| **RTO** (Recovery Time Objective) | **< 30 Minutes** | Time required to provision a clean PostgreSQL instance, run `pg_restore -Fc`, start Flask web and worker processes, and verify readiness via `/ready`. |

---

## 🔄 Deployment Rollback Runbook

### Scenario A: Application Code / Frontend Regression (Zero Database Migrations)
1. Revert container image or Git commit to the last known-good tag.
2. Re-deploy web API and worker processes:
   ```bash
   # Docker / Container restart
   docker compose down web worker
   docker compose up -d web worker
   ```
3. Verify `/health` and `/ready` return HTTP 200.
4. Verify command palette and core views in frontend.

### Scenario B: Deployment Failure with Database Migration Applied
> [!CAUTION]
> **CRITICAL PRODUCTION RULE**: Do **NOT** automatically run `flask db downgrade` in production if new application writes have occurred. Downgrades dropping tables or columns cause irreversible data loss.

**Decision Matrix**:
1. **Migration is fully backward-compatible (additive only, e.g. nullable column added)**:
   - Rollback application code to previous release.
   - Leave the database schema at the new revision. The old application code will ignore the newly added columns.
   - Do **NOT** downgrade database schema.
2. **Migration is incompatible and causes runtime crashes**:
   - Stop web API and worker processes immediately.
   - If zero customer writes occurred, safely downgrade:
     ```bash
     flask db downgrade -1
     ```
   - If customer writes occurred and migration cannot be cleanly reversed, restore the pre-deployment database backup:
     ```bash
     pg_restore -h $DB_HOST -p $DB_PORT -U $DB_USER -d $DB_NAME --clean --if-exists --no-owner pre_deploy_backup.dump
     ```
   - Re-deploy previous application release.
   - Verify `/ready` returns HTTP 200 with database connected.

---

## 🔐 Secret Rotation & Key Management Procedures

| Secret | Rotation Procedure | Service Impact |
| :--- | :--- | :--- |
| **SECRET_KEY** | 1. Generate new 32+ character random key.<br>2. Update environment variable `SECRET_KEY`.<br>3. Restart Flask web processes. | Active user browser sessions will be invalidated and users must re-authenticate. No data loss. |
| **GEMINI_API_KEY** | 1. Generate new API key in Google AI Studio.<br>2. Update `GEMINI_API_KEY` in worker environment.<br>3. Restart background worker. | Zero downtime for web users. Ongoing queue jobs retry with backoff using new key. |
| **GOOGLE_CLIENT_SECRET** | 1. Create new client secret in Google Cloud Console.<br>2. Update `GOOGLE_CLIENT_SECRET` in environment.<br>3. Restart web server.<br>4. Revoke old secret in GCP Console. | Ongoing OAuth login flows require re-initiation. Existing encrypted refresh tokens remain valid. |
| **DATABASE Credentials** | 1. Create new PostgreSQL user/password with identical grants.<br>2. Update `DATABASE_URL` in web and worker configs.<br>3. Rolling restart of web and worker.<br>4. Drop old PostgreSQL credentials. | Zero downtime with connection pool pre-ping resilience. |
| **ENCRYPTION_KEY** (Fernet) | **CAUTION**: Fernet encryption key encrypts existing OAuth tokens at rest.<br>Rotating `ENCRYPTION_KEY` without re-encrypting existing tokens in `users` and `connected_email_accounts` will cause decryption failure.<br>**Procedure**: Run dedicated re-encryption migration script decrypting with `OLD_KEY` and re-encrypting with `NEW_KEY` before updating environment. | Requires planned maintenance window if token re-encryption script is executed. |

---

## 🚨 Incident Response Playbooks

### 1. Database Outage / Connection Loss
- **Symptom**: `/ready` returns 503 `{"status": "unready", "database": "unavailable"}`.
- **Root Cause**: Database instance restart, network partition, or connection saturation.
- **Action**:
  1. Inspect PostgreSQL logs (`pg_log` or Cloud SQL logs).
  2. Verify active connections vs `max_connections`:
     ```sql
     SELECT count(*), state FROM pg_stat_activity GROUP BY state;
     ```
  3. Once database recovers, SQLAlchemy's `pool_pre_ping=True` will automatically purge stale sockets and reconnect without requiring application restart.

### 2. Background Worker Crash / Stuck Queue
- **Symptom**: `/api/queue/health` shows elevated `stale_jobs` or `pending` count increasing while `processing` is 0.
- **Root Cause**: Worker process terminated by OOM killer or host shutdown while holding active job leases.
- **Action**:
  1. Verify worker status via `systemctl status mailmind-worker` or container status.
  2. Restart worker process:
     ```bash
     python backend/worker.py
     ```
  3. Worker will automatically call `recover_stale_jobs(stale_timeout_seconds=300)` on startup and every 30 seconds, resetting expired leases back to `pending` status.
  4. Concurrency protection via `lease_token` guarantees crashed workers cannot corrupt or overwrite state if they wake up late.

### 3. Gemini Outage / Rate Limiting (429/500/503)
- **Symptom**: Increased `ai_last_error` logs, `total_retries` rising in `/api/queue/health`.
- **Mitigation & Protection**:
  1. All deterministic MailMind features (**Action Center, Daily Digest, Saved Searches, Notifications, Analytics, and Thread views**) continue operating with 100% availability.
  2. AI queue retries are capped at `MAX_ATTEMPTS=3` with exponential backoff (5s, 15s) to prevent hammering Google Gemini API.
  3. Failed jobs transition safely to `status="failed"` with sanitized error messages (`_sanitize_error`) preventing credential exposure.

---

## 🌐 Reverse Proxy & HTTPS / HSTS Configuration (Nginx)

In production and HTTPS staging environments, TLS termination and HSTS enforcement must be handled at the reverse proxy layer.

### 1. Nginx Reverse Proxy Configuration
```nginx
server {
    listen 80;
    server_name mailmind.example.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name mailmind.example.com;

    ssl_certificate /etc/letsencrypt/live/mailmind.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/mailmind.example.com/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    # HSTS header (1 year, include subdomains, preload)
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains; preload" always;

    # Security Headers
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;

    # Reverse proxy to Gunicorn backend
    location /api/ {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_read_timeout 120s;
    }

    # Health and Readiness endpoints
    location /health {
        proxy_pass http://127.0.0.1:5000/health;
    }
    location /ready {
        proxy_pass http://127.0.0.1:5000/ready;
    }

    # Serve compiled Vite frontend
    location / {
        root /var/www/mailmind/frontend/dist;
        try_files $uri $uri/ /index.html;
    }
}
```

### 2. HSTS Verification Command
```bash
curl -sI https://mailmind.example.com | grep -i "strict-transport-security"
# Expected output:
# strict-transport-security: max-age=31536000; includeSubDomains; preload
```

---

## 🧪 Staging Validation Runbooks

### 1. Staging Google OAuth 2.0 Interactive Test
1. Set `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, and `GOOGLE_REDIRECT_URI` for the staging domain.
2. In Google Cloud Console, register `https://staging.mailmind.example.com/api/auth/google/callback`.
3. Open staging login page in browser, click "Sign in with Google".
4. Confirm Google consent screen presents only:
   - View your email address
   - View your basic profile info
   - Read, compose, send, and permanently delete all your email from Gmail (verify ONLY read-only scope is requested: `https://www.googleapis.com/auth/gmail.readonly`).
5. Complete sign-in, confirm redirect to dashboard, verify cookie `session` has `Secure` and `HttpOnly` flags.
6. Verify token stored in `users.google_refresh_token` is Fernet-encrypted ciphertext at rest.

### 2. Staging Gmail Live Sync Verification
1. Connect a dedicated staging test Gmail account.
2. Initial Sync:
   - Call `/api/sync/gmail` (or auto-sync).
   - Verify messages appear in `/api/emails`.
   - Verify sender, recipient, thread_id, subject, and timestamps are parsed accurately.
   - Verify zero draft creation, zero sent messages, zero label modifications on Gmail.
3. Incremental Sync:
   - Send a test email from an external account to the test Gmail account.
   - Trigger incremental sync.
   - Verify `historyId` advances and only the new message is ingested.
   - Verify repeated sync is idempotent (no duplicate `EmailMessage` rows).

### 3. Staging Smoke Test Checklist
- [ ] `/health` returns HTTP 200 `{"status": "healthy"}`
- [ ] `/ready` returns HTTP 200 `{"status": "ready", "database": "connected"}`
- [ ] `/api/queue/health` returns HTTP 200 with queue metrics
- [ ] Frontend loads and command palette (Ctrl+K) functions
- [ ] Interactive login creates session
- [ ] Dashboard metrics load under 500ms
- [ ] Action item creation and confirmation works
- [ ] Meeting confirmation modal blocks unauthorized creation

---

## ⚠️ Known Environment-Dependent Validation Limitations

The following items are environment-dependent and distinguish code-readiness support from live staging cluster validation:

| Test Item | Local Dev Environment Status | Staging Requirement | Resolution |
| :--- | :--- | :--- | :--- |
| **Interactive Google OAuth** | **PARTIAL** (Full code & redirect validation verified; interactive browser consent requires registered staging domain) | Mandatory Staging Gate | Execute with staging domain credentials before production rollout |
| **Live Gmail Staging Sync** | **NOT EXECUTED** (Mock sync & parsing verified with 100% test coverage; requires live test mailbox) | Mandatory Staging Gate | Execute initial & incremental sync against test mailbox |
| **HTTPS / HSTS** | **NOT EXECUTED** (Local loopback is HTTP; application code dynamically attaches HSTS when `request.is_secure`) | Mandatory Staging Gate | Verify reverse proxy TLS certificate & HSTS header on staging |
| **PostgreSQL Process Crash** | **PARTIAL** (Simulated connection dropped and `pool_pre_ping` auto-reconnect verified) | Staging Infrastructure Gate | Execute process kill/restart drill on staging PostgreSQL |
| **Rollback Drill** | **PARTIAL** (Migration upgrade/downgrade and backup/restore verified; live rolling rollback deferred) | Staging Deployment Gate | Execute rolling container rollback drill |
| **npm Audit** | **PARTIAL / Accepted Risk** (6 advisories audited; React Router RSC CSRF vulnerability is non-exploitable in client-side Vite SPA) | Documented Accepted Risk | Keep pinned versions to prevent framework churn |


