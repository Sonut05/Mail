import os
import sys
import time
import statistics
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, ".")
from app import create_app
from app.config import Config
from app.extensions import db
from app.models import User, ConnectedEmailAccount, EmailMessage, Task, CalendarEvent, ActionItem, Notification

PG_PORT = 5433
PG_HOST = "localhost"
PG_USER = "postgres"
BENCHMARK_DB = "mailmind_bench_all"

import subprocess
import psycopg2

PG_CTL_BIN = r"C:\Program Files\PostgreSQL\18\bin\pg_ctl.exe"
PG_DATA_DIR = os.path.join(os.environ.get("TEMP", r"C:\temp"), "pg_test_cluster_p61")

# Ensure PG is running
subprocess.Popen([PG_CTL_BIN, "-D", PG_DATA_DIR, "-o", f"-p {PG_PORT}", "start"])
for _ in range(20):
    time.sleep(1)
    try:
        c = psycopg2.connect(dbname="postgres", user=PG_USER, host=PG_HOST, port=PG_PORT, connect_timeout=1)
        c.close()
        break
    except Exception:
        pass

# Ensure BENCHMARK_DB exists
conn = psycopg2.connect(dbname="postgres", user=PG_USER, host=PG_HOST, port=PG_PORT)
conn.autocommit = True
cur = conn.cursor()
cur.execute(f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '{BENCHMARK_DB}' AND pid <> pg_backend_pid();")
cur.execute(f"DROP DATABASE IF EXISTS {BENCHMARK_DB};")
cur.execute(f"CREATE DATABASE {BENCHMARK_DB};")
conn.close()

class BenchmarkConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = f"postgresql://{PG_USER}@{PG_HOST}:{PG_PORT}/{BENCHMARK_DB}"
    SECRET_KEY = "benchmark-secret-key-32-chars-long!"
    ENCRYPTION_KEY = "T8gjWZab-gRjl9cfFcdGHPP1zYmVPMOaDCGTO3QScik="
    CREATE_DB_TABLES_ON_STARTUP = True
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_size": 30,
        "max_overflow": 20,
        "pool_timeout": 30,
        "pool_recycle": 1800,
        "pool_pre_ping": True,
    }

app = create_app(BenchmarkConfig)

with app.app_context():
    db.drop_all()
    db.create_all()
    u = User(id="bench_u1", email="bench1@example.com", name="Benchmark User")
    ca = ConnectedEmailAccount(id="bench_ca1", user_id="bench_u1", email_address="bench1@example.com", encrypted_access_token="tok", encrypted_refresh_token="ref")
    db.session.add_all([u, ca])
    db.session.commit()

    # Seed 100 emails, 20 tasks, 20 actions, 20 notifications
    emails = []
    for i in range(100):
        em = EmailMessage(
            id=f"em_{i}",
            user_id="bench_u1",
            connected_account_id="bench_ca1",
            message_id=f"msg_{i}",
            thread_id=f"th_{i % 20}",
            subject=f"Important Project Update {i}",
            from_address=f"colleague{i % 5}@example.com",
            body_text=f"Hello, this is email body {i} with some action items.",
            ai_importance_score=80 if i % 2 == 0 else 40,
            priority="high" if i % 3 == 0 else "medium",
            category="work",
        )
        emails.append(em)
    db.session.bulk_save_objects(emails)

    tasks = [Task(id=f"t_{i}", user_id="bench_u1", task_title=f"Task {i}", priority="high") for i in range(20)]
    db.session.bulk_save_objects(tasks)

    actions = [ActionItem(id=f"act_{i}", user_id="bench_u1", title=f"Action {i}", action_type="REPLY_NEEDED", source_email_id=f"em_{i}", status="OPEN") for i in range(20)]
    db.session.bulk_save_objects(actions)

    notifs = [Notification(id=f"notif_{i}", user_id="bench_u1", title=f"Notif {i}", message=f"Message {i}", type="INFO", severity="info") for i in range(20)]
    db.session.bulk_save_objects(notifs)
    db.session.commit()

endpoints = [
    ("/api/dashboard/stats", "GET"),
    ("/api/actions", "GET"),
    ("/api/digest", "GET"),
    ("/api/emails", "GET"),
    ("/api/notifications", "GET"),
]

client = app.test_client()
# Set session cookie
with client.session_transaction() as sess:
    sess["user_id"] = "bench_u1"

print("\n--- MULTI-ENDPOINT BENCHMARK (PostgreSQL 18.4) ---")

results = []

for endpoint, method in endpoints:
    for concurrency in [10, 25]:
        total_requests = concurrency * 4  # e.g., 40 requests for 10, 100 for 25
        durations = []
        errors = 0

        def send_req(_):
            t0 = time.perf_counter()
            try:
                resp = client.get(endpoint)
                elapsed = (time.perf_counter() - t0) * 1000
                if resp.status_code != 200:
                    return None, 1
                return elapsed, 0
            except Exception:
                return None, 1

        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            res = list(executor.map(send_req, range(total_requests)))

        valid_durations = [d for d, err in res if d is not None]
        errors = sum(err for _, err in res)

        valid_durations.sort()
        n = len(valid_durations)
        if n > 0:
            p50 = valid_durations[int(n * 0.50)]
            p95 = valid_durations[min(int(n * 0.95), n - 1)]
            p99 = valid_durations[min(int(n * 0.99), n - 1)]
        else:
            p50 = p95 = p99 = 0.0

        status = "PASS" if p95 < 500 and errors == 0 else "FAIL"
        results.append({
            "endpoint": endpoint,
            "concurrency": concurrency,
            "requests": total_requests,
            "errors": errors,
            "p50": round(p50, 2),
            "p95": round(p95, 2),
            "p99": round(p99, 2),
            "result": status,
        })
        print(f"{endpoint:25} | C={concurrency:2} | Req={total_requests:3} | p50={p50:6.2f}ms | p95={p95:6.2f}ms | Errors={errors} | {status}")
