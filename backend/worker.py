"""
MailMild / MailMind AI — Standalone Background AI Worker Process.

Processes asynchronous AIAnalysisJob records from PostgreSQL / SQLite.
Supports:
- Atomic claiming with SELECT ... FOR UPDATE SKIP LOCKED
- Stale worker recovery and lease ownership enforcement
- Graceful shutdown upon SIGINT / SIGTERM with in-flight job completion
- Safe structured logging with request/job correlation IDs
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import time
from typing import Any, Optional

# Ensure project backend directory is on sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app
from app.services.job_queue_service import (
    claim_next_ai_job,
    process_claimed_job,
    recover_stale_jobs,
)

logger = logging.getLogger("mailmild.worker")
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] [AIWorker:%(process)d] %(message)s",
    )


class AIWorker:
    """Production background worker for durable AI job execution."""

    def __init__(self, app: Any = None) -> None:
        self.app = app or create_app()
        self.running = True
        self.current_job_id: Optional[str] = None
        self.start_time = time.time()
        self.worker_id = self.app.config.get("AI_WORKER_ID") or f"worker-{os.getpid()}"
        self.poll_interval = float(self.app.config.get("AI_JOB_POLL_INTERVAL", 1.0))
        self.stale_timeout = int(self.app.config.get("AI_JOB_STALE_SECONDS", 300))
        self.last_recovery_check = 0.0

        self._setup_signals()

    def _setup_signals(self) -> None:
        """Register signal handlers for graceful shutdown."""
        try:
            signal.signal(signal.SIGINT, self._handle_signal)
            signal.signal(signal.SIGTERM, self._handle_signal)
        except (ValueError, AttributeError):
            # Signal handling might not be supported in certain execution threads
            pass

    def _handle_signal(self, signum: int, frame: Any) -> None:
        sig_name = "SIGTERM" if signum == signal.SIGTERM else "SIGINT"
        if self.current_job_id:
            logger.info(
                "Received %s. Finishing active job %s before stopping...",
                sig_name, self.current_job_id
            )
        else:
            logger.info("Received %s. Initiating graceful shutdown...", sig_name)
        self.running = False

    def get_status(self) -> dict[str, Any]:
        """Return operational status and health metrics of the worker."""
        return {
            "worker_id": self.worker_id,
            "running": self.running,
            "current_job_id": self.current_job_id,
            "uptime_seconds": time.time() - self.start_time,
            "poll_interval": self.poll_interval,
            "stale_timeout": self.stale_timeout,
        }

    def run_once(self) -> bool:
        """Execute a single polling iteration. Returns True if a job was processed."""
        with self.app.app_context():
            now = time.time()
            # Run stale recovery check every 30 seconds
            if now - self.last_recovery_check >= 30.0:
                try:
                    recovered = recover_stale_jobs(self.stale_timeout)
                    if recovered > 0:
                        logger.info("Stale recovery check: recovered %d stuck job(s)", recovered)
                except Exception as exc:
                    logger.error("Error during stale job recovery: %s", exc)
                self.last_recovery_check = now

            # If stopping, do not claim new work
            if not self.running:
                return False

            # Attempt to claim next available job atomically
            try:
                claim = claim_next_ai_job(
                    worker_id=self.worker_id,
                    stale_timeout_seconds=self.stale_timeout,
                )
            except Exception as exc:
                logger.error("Error claiming next AI job: %s", exc)
                return False

            if not claim:
                return False

            job_id = claim["job_id"]
            email_id = claim["email_id"]
            user_id = claim["user_id"]
            lease_token = claim["lease_token"]
            attempts = claim["attempts"]

            self.current_job_id = job_id
            logger.info(
                "Claimed job [%s]: email=%s user=%s attempt=%d/%d worker=%s",
                job_id, email_id, user_id, attempts, claim["max_attempts"], self.worker_id
            )

            start_t = time.time()
            try:
                res = process_claimed_job(
                    job_id=job_id,
                    worker_id=self.worker_id,
                    lease_token=lease_token,
                    app=self.app,
                )
                duration = time.time() - start_t
                logger.info(
                    "Processed job [%s]: status=%s duration=%.2fs attempts=%d",
                    job_id, res.get("status"), duration, attempts
                )
                return True
            except Exception as exc:
                duration = time.time() - start_t
                logger.error(
                    "Unhandled exception processing job [%s]: %s (duration=%.2fs)",
                    job_id, exc, duration
                )
                return True
            finally:
                self.current_job_id = None

    def start(self) -> None:
        """Start the worker polling loop."""
        logger.info(
            "AI Worker started. id=%s poll_interval=%.1fs stale_timeout=%ds",
            self.worker_id, self.poll_interval, self.stale_timeout
        )

        # Initial stale job sweep on startup
        with self.app.app_context():
            try:
                recovered = recover_stale_jobs(self.stale_timeout)
                if recovered > 0:
                    logger.info("Startup stale recovery: recovered %d orphaned job(s)", recovered)
            except Exception as exc:
                logger.warning("Startup stale recovery error: %s", exc)

        while self.running:
            processed = self.run_once()
            if not processed and self.running:
                time.sleep(self.poll_interval)

        logger.info("AI Worker stopped cleanly.")


def main() -> None:
    worker = AIWorker()
    worker.start()


if __name__ == "__main__":
    main()
