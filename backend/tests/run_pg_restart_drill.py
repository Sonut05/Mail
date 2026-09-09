import os
import sys
import time
import subprocess
import psycopg2

sys.path.insert(0, ".")

from app import create_app
from app.config import Config
from app.extensions import db
from app.models import User, EmailMessage, Task, AIAnalysisJob
from app.services.job_queue_service import enqueue_ai_job, claim_next_ai_job, recover_stale_jobs

PG_PORT = 5433
PG_HOST = "localhost"
PG_USER = "postgres"
PG_DB = "mailmind_crash_drill"

PG_CTL_BIN = r"C:\Program Files\PostgreSQL\18\bin\pg_ctl.exe"
PG_DATA_DIR = os.path.join(os.environ.get("TEMP", r"C:\temp"), "pg_test_cluster_p61")

class DrillConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = f"postgresql://{PG_USER}@{PG_HOST}:{PG_PORT}/{PG_DB}"
    SECRET_KEY = "drill-secret-key-32-chars-long!"
    ENCRYPTION_KEY = "T8gjWZab-gRjl9cfFcdGHPP1zYmVPMOaDCGTO3QScik="
    CREATE_DB_TABLES_ON_STARTUP = True
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_size": 10,
        "max_overflow": 5,
        "pool_pre_ping": True,
        "pool_timeout": 5,
    }

# 1. Ensure PG is running and DB exists
subprocess.run([PG_CTL_BIN, "-D", PG_DATA_DIR, "-o", f"-p {PG_PORT}", "start", "-w"], check=False)
time.sleep(1)

conn = psycopg2.connect(dbname="postgres", user=PG_USER, host=PG_HOST, port=PG_PORT)
conn.autocommit = True
cur = conn.cursor()
cur.execute(f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '{PG_DB}' AND pid <> pg_backend_pid();")
cur.execute(f"DROP DATABASE IF EXISTS {PG_DB};")
cur.execute(f"CREATE DATABASE {PG_DB};")
conn.close()

app = create_app(DrillConfig)

with app.app_context():
    db.create_all()
    user = User(id="drill-user-1", email="drill@example.com", name="Drill User")
    em = EmailMessage(
        id="drill-msg-1",
        user_id="drill-user-1",
        message_id="msg-drill-1",
        thread_id="th-1",
        from_address="sender@example.com",
        subject="Drill Subject",
    )
    db.session.add_all([user, em])
    db.session.commit()
    job, _ = enqueue_ai_job("drill-msg-1", "drill-user-1")

client = app.test_client()

print("--- STEP 1: INITIAL READINESS CHECK ---")
resp = client.get("/ready")
print(f"Readiness: {resp.status_code}, data={resp.get_json()}")
assert resp.status_code == 200

print("\n--- STEP 2: HARD STOPPING POSTGRESQL PROCESS ---")
stop_res = subprocess.run([PG_CTL_BIN, "-D", PG_DATA_DIR, "-m", "immediate", "stop", "-w"], capture_output=True, text=True)
print(f"pg_ctl stop immediate: {stop_res.returncode}")

print("\n--- STEP 3: OBSERVING APPLICATION UNDER DATABASE OUTAGE ---")
resp_down = client.get("/ready")
print(f"Readiness during outage: {resp_down.status_code}, data={resp_down.get_json()}")
assert resp_down.status_code == 503

print("\n--- STEP 4: RESTARTING POSTGRESQL PROCESS ---")
subprocess.Popen([PG_CTL_BIN, "-D", PG_DATA_DIR, "-o", f"-p {PG_PORT}", "start"])

print("Waiting for PostgreSQL to complete crash recovery and accept connections...")
recovered = False
for _ in range(30):
    time.sleep(1)
    try:
        c = psycopg2.connect(dbname="postgres", user=PG_USER, host=PG_HOST, port=PG_PORT, connect_timeout=1)
        c.close()
        recovered = True
        break
    except Exception:
        pass

print(f"PostgreSQL recovered: {recovered}")
assert recovered, "PostgreSQL failed to restart within 30 seconds"

print("\n--- STEP 5: OBSERVING AUTOMATIC RECOVERY VIA POOL_PRE_PING ---")
resp_up = client.get("/ready")
print(f"Readiness after recovery: {resp_up.status_code}, data={resp_up.get_json()}")
assert resp_up.status_code == 200

with app.app_context():
    # Verify queries work
    u = User.query.filter_by(id="drill-user-1").first()
    print(f"User query verification: {u.email if u else None}")
    assert u is not None

    # Verify worker claim and queue durability
    claim = claim_next_ai_job("drill-worker-1")
    print(f"Worker claim verification: {claim}")
    assert claim is not None
    assert claim["email_id"] == "drill-msg-1"

print("\n--- CRASH & RESTART DRILL COMPLETED SUCCESSFULLY ---")
