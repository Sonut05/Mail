import os
import sys
import time
import subprocess
import psycopg2

sys.path.insert(0, ".")

from app import create_app
from app.config import Config
from app.extensions import db
from app.models import User, EmailMessage, Task, CalendarEvent, ActionItem, Notification, SavedSearch, AIAnalysisJob

PG_PORT = 5433
PG_HOST = "localhost"
PG_USER = "postgres"
SOURCE_DB = "mailmind_backup_source"
TARGET_DB = "mailmind_backup_target"

PG_CTL_BIN = r"C:\Program Files\PostgreSQL\18\bin\pg_ctl.exe"
PG_DATA_DIR = os.path.join(os.environ.get("TEMP", r"C:\temp"), "pg_test_cluster_p61")
PG_DUMP_BIN = r"C:\Program Files\PostgreSQL\18\bin\pg_dump.exe"
PG_RESTORE_BIN = r"C:\Program Files\PostgreSQL\18\bin\pg_restore.exe"
BACKUP_FILE = os.path.join(os.environ.get("TEMP", r"C:\temp"), "mailmind_drill_backup.dump")

# 0. Ensure PG is running
subprocess.Popen([PG_CTL_BIN, "-D", PG_DATA_DIR, "-o", f"-p {PG_PORT}", "start"])
for _ in range(20):
    time.sleep(1)
    try:
        c = psycopg2.connect(dbname="postgres", user=PG_USER, host=PG_HOST, port=PG_PORT, connect_timeout=1)
        c.close()
        break
    except Exception:
        pass

# 1. Setup Source DB with data
conn = psycopg2.connect(dbname="postgres", user=PG_USER, host=PG_HOST, port=PG_PORT)
conn.autocommit = True
cur = conn.cursor()
for db_name in [SOURCE_DB, TARGET_DB]:
    cur.execute(f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '{db_name}' AND pid <> pg_backend_pid();")
    cur.execute(f"DROP DATABASE IF EXISTS {db_name};")
    cur.execute(f"CREATE DATABASE {db_name};")
conn.close()

class SourceConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = f"postgresql://{PG_USER}@{PG_HOST}:{PG_PORT}/{SOURCE_DB}"
    SECRET_KEY = "backup-secret-key-32-chars-long!"
    ENCRYPTION_KEY = "T8gjWZab-gRjl9cfFcdGHPP1zYmVPMOaDCGTO3QScik="
    CREATE_DB_TABLES_ON_STARTUP = True

src_app = create_app(SourceConfig)
with src_app.app_context():
    db.create_all()
    u = User(id="u1", email="user1@example.com", name="Backup User")
    em = EmailMessage(id="e1", user_id="u1", message_id="m1", thread_id="th1", subject="Subject 1", from_address="s@test.com")
    t = Task(id="t1", user_id="u1", task_title="Task 1", priority="high")
    job = AIAnalysisJob(id="j1", email_id="e1", user_id="u1", status=AIAnalysisJob.STATUS_PENDING)
    db.session.add_all([u, em, t, job])
    db.session.commit()

# 2. Measure backup duration & size
t0_backup = time.perf_counter()
dump_res = subprocess.run(
    [PG_DUMP_BIN, "-h", PG_HOST, "-p", str(PG_PORT), "-U", PG_USER, "-d", SOURCE_DB, "-Fc", "-f", BACKUP_FILE],
    capture_output=True, text=True
)
t1_backup = time.perf_counter()
backup_duration_s = t1_backup - t0_backup
backup_size_bytes = os.path.getsize(BACKUP_FILE) if os.path.exists(BACKUP_FILE) else 0

# 3. Measure restore duration into TARGET_DB
t0_restore = time.perf_counter()
restore_res = subprocess.run(
    [PG_RESTORE_BIN, "-h", PG_HOST, "-p", str(PG_PORT), "-U", PG_USER, "-d", TARGET_DB, "--clean", "--if-exists", "--no-owner", BACKUP_FILE],
    capture_output=True, text=True
)
t1_restore = time.perf_counter()
restore_duration_s = t1_restore - t0_restore

# 4. Verify restored application data
class TargetConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = f"postgresql://{PG_USER}@{PG_HOST}:{PG_PORT}/{TARGET_DB}"
    SECRET_KEY = "backup-secret-key-32-chars-long!"
    ENCRYPTION_KEY = "T8gjWZab-gRjl9cfFcdGHPP1zYmVPMOaDCGTO3QScik="
    CREATE_DB_TABLES_ON_STARTUP = False

target_app = create_app(TargetConfig)
with target_app.app_context():
    restored_u = User.query.filter_by(id="u1").first()
    restored_em = EmailMessage.query.filter_by(id="e1").first()
    restored_t = Task.query.filter_by(id="t1").first()
    restored_j = AIAnalysisJob.query.filter_by(id="j1").first()

    restore_success = (
        restored_u is not None and
        restored_em is not None and
        restored_t is not None and
        restored_j is not None
    )

print(f"BACKUP DURATION: {backup_duration_s:.3f} s")
print(f"BACKUP SIZE: {backup_size_bytes} bytes ({backup_size_bytes / 1024:.2f} KB)")
print(f"RESTORE DURATION: {restore_duration_s:.3f} s")
print(f"RESTORE SUCCESS: {restore_success}")
assert restore_success, "Restored data verification failed!"
