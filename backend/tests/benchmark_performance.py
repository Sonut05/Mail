"""
Phase 9 Performance Benchmark and Queue Throughput Profiler.
Measures real response latency percentiles (p50, p95, p99, max) and error rates
across core MailMind endpoints under controlled concurrency.
"""

import json
import os
import sys
import time
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
import numpy as np

from app import create_app
from app.config import Config
from app.extensions import db
from app.models.user import User
from app.models.email_message import EmailMessage
from app.models.action_item import ActionItem, ActionType, ActionStatus
from app.models.notification import Notification, NotificationType, NotificationSeverity
from app.models.saved_search import SavedSearch
from app.models.ai_analysis_job import AIAnalysisJob
from app.services.action_center_service import sync_actions
from app.services.job_queue_service import enqueue_ai_job, claim_next_ai_job


def run_benchmark():
    test_db = f"perf_bench_{uuid.uuid4().hex[:8]}.db"

    class BenchConfig(Config):
        TESTING = True
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{test_db}"
        SECRET_KEY = "perf-benchmark-secret-key-32-chars"
        ENCRYPTION_KEY = "T8gjWZab-gRjl9cfFcdGHPP1zYmVPMOaDCGTO3QScik="
        CREATE_DB_TABLES_ON_STARTUP = True

    app = create_app(BenchConfig)

    with app.app_context():
        with db.engine.connect() as conn:
            conn.execute(db.text("PRAGMA journal_mode=WAL;"))
            conn.execute(db.text("PRAGMA synchronous=NORMAL;"))
        db.create_all()
        # Seed user and realistic data
        user = User(id=str(uuid.uuid4()), email="bench_user@example.com", name="Benchmark User")
        db.session.add(user)
        db.session.commit()
        user_id = user.id

        # Seed 50 emails
        emails = []
        for i in range(50):
            em = EmailMessage(
                id=str(uuid.uuid4()),
                user_id=user_id,
                message_id=f"msg-bench-{i}",
                thread_id=f"thread-bench-{i % 10}",
                from_address=f"sender{i % 5}@example.com",
                subject=f"Important Benchmark Email {i}",
                body_text=f"Body content for benchmark test email {i}.",
                received_at=datetime.now(timezone.utc) - timedelta(hours=i),
                ai_action_required=(i % 3 == 0),
                ai_next_action=f"Follow up on task {i}" if (i % 3 == 0) else None,
                ai_priority="high" if (i % 2 == 0) else "medium",
                ai_importance_score=75 + (i % 20),
            )
            emails.append(em)
        db.session.add_all(emails)
        db.session.commit()

        # Seed notifications
        notifs = []
        for i in range(20):
            n = Notification(
                id=str(uuid.uuid4()),
                user_id=user_id,
                type=NotificationType.IMPORTANT_EMAIL.value,
                title=f"Notification {i}",
                message=f"Benchmark notification {i}",
                severity=NotificationSeverity.INFO.value,
            )
            notifs.append(n)
        db.session.add_all(notifs)
        db.session.commit()

        # Sync action center
        sync_actions(user_id)
        email_ids = [em.id for em in emails]

    endpoints = [
        ("/api/dashboard/stats", "GET"),
        ("/api/emails", "GET"),
        ("/api/actions", "GET"),
        ("/api/notifications", "GET"),
        ("/api/digest", "GET"),
        ("/api/analytics/productivity?period=7d", "GET"),
    ]

    results = []

    print("\n--- PHASE 9 ENDPOINT PERFORMANCE BENCHMARK ---")

    for endpoint, method in endpoints:
        for concurrency in [10, 25]:
            latencies = []
            errors = 0
            total_requests = 50

            def make_request():
                client = app.test_client()
                with client.session_transaction() as sess:
                    sess["user_id"] = user_id

                t0 = time.perf_counter()
                try:
                    if method == "GET":
                        resp = client.get(endpoint)
                    else:
                        resp = client.post(endpoint)
                    t1 = time.perf_counter()
                    if resp.status_code != 200:
                        return None, True
                    return (t1 - t0) * 1000.0, False  # ms
                except Exception:
                    return None, True

            start_all = time.perf_counter()
            with ThreadPoolExecutor(max_workers=concurrency) as executor:
                futures = [executor.submit(make_request) for _ in range(total_requests)]
                for f in as_completed(futures):
                    lat, err = f.result()
                    if err or lat is None:
                        errors += 1
                    else:
                        latencies.append(lat)
            elapsed_all = time.perf_counter() - start_all

            throughput = total_requests / elapsed_all if elapsed_all > 0 else 0
            error_rate = (errors / total_requests) * 100.0

            p50 = np.percentile(latencies, 50) if latencies else 0.0
            p95 = np.percentile(latencies, 95) if latencies else 0.0
            p99 = np.percentile(latencies, 99) if latencies else 0.0
            max_lat = np.max(latencies) if latencies else 0.0

            res_entry = {
                "endpoint": endpoint.split("?")[0],
                "concurrency": concurrency,
                "requests": total_requests,
                "p50_ms": round(float(p50), 2),
                "p95_ms": round(float(p95), 2),
                "p99_ms": round(float(p99), 2),
                "max_ms": round(float(max_lat), 2),
                "throughput_rps": round(float(throughput), 2),
                "error_rate_pct": round(float(error_rate), 2),
            }
            results.append(res_entry)
            print(f"[{res_entry['endpoint']}] conc={concurrency}: p50={p50:.2f}ms, p95={p95:.2f}ms, p99={p99:.2f}ms, rps={throughput:.1f}, err={error_rate:.1f}%")

    # Queue Latency Benchmark
    print("\n--- PHASE 9 DURABLE QUEUE PERFORMANCE BENCHMARK ---")
    with app.app_context():
        enqueue_latencies = []
        for i in range(30):
            em_id = email_ids[i % len(email_ids)]
            t0 = time.perf_counter()
            job, _ = enqueue_ai_job(em_id, user_id)
            t1 = time.perf_counter()
            enqueue_latencies.append((t1 - t0) * 1000.0)

        claim_latencies = []
        for i in range(20):
            t0 = time.perf_counter()
            claim = claim_next_ai_job(f"bench-worker-{i}")
            t1 = time.perf_counter()
            if claim:
                claim_latencies.append((t1 - t0) * 1000.0)

        queue_results = {
            "enqueue_p50_ms": round(float(np.percentile(enqueue_latencies, 50)), 2),
            "enqueue_p95_ms": round(float(np.percentile(enqueue_latencies, 95)), 2),
            "claim_p50_ms": round(float(np.percentile(claim_latencies, 50)), 2) if claim_latencies else 0.0,
            "claim_p95_ms": round(float(np.percentile(claim_latencies, 95)), 2) if claim_latencies else 0.0,
        }
        print(f"Queue Enqueue: p50={queue_results['enqueue_p50_ms']}ms, p95={queue_results['enqueue_p95_ms']}ms")
        print(f"Queue Claim:   p50={queue_results['claim_p50_ms']}ms, p95={queue_results['claim_p95_ms']}ms")

    # Clean up test db
    with app.app_context():
        db.session.remove()
        db.drop_all()
    if os.path.exists(test_db):
        try:
            os.remove(test_db)
        except OSError:
            pass

    out_file = os.path.join(os.path.dirname(__file__), "benchmark_results.json")
    with open(out_file, "w") as f:
        json.dump({"endpoints": results, "queue": queue_results}, f, indent=2)
    print(f"\nSaved benchmark results to {out_file}")


if __name__ == "__main__":
    run_benchmark()
