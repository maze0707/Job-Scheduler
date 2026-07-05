import math
import os
import signal
import socket
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import DeadLetterJob, Job, JobExecution, JobStatus, RetryStrategy, WorkerHeartbeat, WorkerRegistration

SHUTDOWN_SIGNALED = False


def handle_graceful_shutdown(signum, frame):
    global SHUTDOWN_SIGNALED
    print("\n[WORKER] Graceful shutdown signal received. Draining active tasks before exit...")
    SHUTDOWN_SIGNALED = True


signal.signal(signal.SIGINT, handle_graceful_shutdown)
signal.signal(signal.SIGTERM, handle_graceful_shutdown)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def calculate_backoff(strategy: RetryStrategy | str | None, retry_count: int) -> int:
    if isinstance(strategy, RetryStrategy):
        strategy_norm = strategy.value.lower()
    else:
        strategy_norm = str(strategy or "fixed").lower()

    if strategy_norm == "fixed":
        return 5
    if strategy_norm == "linear":
        return retry_count * 5
    if strategy_norm == "exponential":
        return int(math.pow(2, retry_count)) * 2
    return 5


def _compute_next_cron_run(current_run_at: datetime | None, cron_expression: str | None) -> datetime | None:
    if not cron_expression:
        return None

    now = utcnow()
    base = current_run_at if current_run_at is not None else now
    expr = cron_expression.strip()
    parts = expr.split()
    if len(parts) != 5:
        return base + timedelta(minutes=5)

    minute_field, hour_field, _, _, _ = parts

    def _parse_step(field: str) -> int | None:
        if field.startswith("*/"):
            raw = field[2:]
            if raw.isdigit() and int(raw) > 0:
                return int(raw)
        return None

    minute_step = _parse_step(minute_field)
    hour_step = _parse_step(hour_field)

    if minute_step is not None and hour_field == "*":
        candidate = now + timedelta(minutes=minute_step)
        return candidate if candidate > now else now + timedelta(minutes=max(1, minute_step))

    if minute_field.isdigit() and hour_field == "*":
        minute_target = int(minute_field)
        if 0 <= minute_target <= 59:
            candidate = now.replace(second=0, microsecond=0, minute=minute_target)
            if candidate <= now:
                candidate = candidate + timedelta(hours=1)
            return candidate

    if minute_field == "0" and hour_field == "*":
        candidate = now.replace(second=0, microsecond=0, minute=0)
        if candidate <= now:
            candidate = candidate + timedelta(hours=1)
        return candidate

    if minute_field == "*" and hour_step is not None:
        candidate = now + timedelta(hours=hour_step)
        return candidate if candidate > now else now + timedelta(hours=max(1, hour_step))

    return now + timedelta(minutes=5)


class WorkerRuntime:
    def __init__(
        self,
        poll_interval_seconds: float = 1.0,
        heartbeat_interval_seconds: int = 10,
        claim_timeout_seconds: int = 60,
        max_workers: int = 4,
    ):
        self.poll_interval_seconds = poll_interval_seconds
        self.heartbeat_interval_seconds = heartbeat_interval_seconds
        self.claim_timeout_seconds = claim_timeout_seconds
        self.max_workers = max_workers

        self.worker_id = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
        self._in_flight_lock = threading.Lock()
        self._in_flight_job_ids: set[int] = set()
        self._pool = ThreadPoolExecutor(max_workers=self.max_workers, thread_name_prefix="scheduler-worker")

    def register_worker(self) -> None:
        db = SessionLocal()
        try:
            row = db.query(WorkerRegistration).filter(WorkerRegistration.worker_id == self.worker_id).first()
            if not row:
                row = WorkerRegistration(
                    worker_id=self.worker_id,
                    hostname=socket.gethostname(),
                    pid=os.getpid(),
                    status="ACTIVE",
                    started_at=utcnow(),
                    last_heartbeat_at=utcnow(),
                )
                db.add(row)
            else:
                row.hostname = socket.gethostname()
                row.pid = os.getpid()
                row.status = "ACTIVE"
                row.shutdown_at = None
                row.last_heartbeat_at = utcnow()
            db.commit()
            print(f"[WORKER] Registered worker_id={self.worker_id}")
        finally:
            db.close()

    def heartbeat(self) -> None:
        db = SessionLocal()
        try:
            now = utcnow()
            row = db.query(WorkerRegistration).filter(WorkerRegistration.worker_id == self.worker_id).first()
            if row:
                row.last_heartbeat_at = now
                row.status = "ACTIVE"
                db.add(
                    WorkerHeartbeat(
                        worker_id=self.worker_id,
                        heartbeat_at=now,
                        status="ACTIVE",
                    )
                )
                db.commit()
        finally:
            db.close()

    def mark_shutdown(self) -> None:
        db = SessionLocal()
        try:
            row = db.query(WorkerRegistration).filter(WorkerRegistration.worker_id == self.worker_id).first()
            if row:
                row.status = "STOPPED"
                row.shutdown_at = utcnow()
                row.last_heartbeat_at = utcnow()
                db.commit()
        finally:
            db.close()

    def recover_stale_claims(self) -> None:
        db = SessionLocal()
        try:
            threshold = utcnow() - timedelta(seconds=self.claim_timeout_seconds)
            stale_jobs = (
                db.query(Job)
                .filter(
                    Job.status.in_([JobStatus.CLAIMED, JobStatus.RUNNING]),
                    or_(Job.heartbeat_at.is_(None), Job.heartbeat_at < threshold),
                )
                .all()
            )
            if not stale_jobs:
                return
            for job in stale_jobs:
                job.status = JobStatus.QUEUED
                job.claimed_by = None
                job.claimed_at = None
                job.heartbeat_at = None
                job.started_at = None
                job.last_error = "Recovered stale claim due to heartbeat timeout"
            db.commit()
            print(f"[WORKER] Recovered {len(stale_jobs)} stale claimed/running jobs.")
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def claim_job(self) -> Job | None:
        db = SessionLocal()
        try:
            now = utcnow()
            query = (
                db.query(Job)
                .filter(
                    and_(
                        Job.run_at <= now,
                        Job.status.in_([JobStatus.QUEUED, JobStatus.SCHEDULED]),
                        Job.retry_strategy.in_([RetryStrategy.FIXED, RetryStrategy.LINEAR, RetryStrategy.EXPONENTIAL]),
                    )
                )
                .order_by(Job.priority.desc(), Job.id.asc())
            )

            candidate = query.with_for_update(skip_locked=True).first()

            if not candidate:
                db.commit()
                return None

            with self._in_flight_lock:
                if candidate.id in self._in_flight_job_ids:
                    db.commit()
                    return None
                self._in_flight_job_ids.add(candidate.id)

            candidate.status = JobStatus.CLAIMED
            candidate.claimed_by = self.worker_id
            candidate.claimed_at = now
            candidate.heartbeat_at = now
            candidate.last_error = None
            db.commit()
            db.refresh(candidate)
            return candidate
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _upsert_execution_start(self, db: Session, job_id: int) -> JobExecution:
        execution = (
            db.query(JobExecution)
            .filter(
                JobExecution.job_id == job_id,
                JobExecution.worker_id == self.worker_id,
                JobExecution.finished_at.is_(None),
            )
            .order_by(JobExecution.id.desc())
            .first()
        )
        if execution:
            execution.status = JobStatus.RUNNING.value
            execution.started_at = utcnow()
            execution.logs = "Job moved to RUNNING"
            return execution

        execution = JobExecution(
            job_id=job_id,
            worker_id=self.worker_id,
            started_at=utcnow(),
            status=JobStatus.RUNNING.value,
            logs="Job moved to RUNNING",
        )
        db.add(execution)
        return execution

    def _set_running(self, job_id: int) -> Job | None:
        db = SessionLocal()
        try:
            job = (
                db.query(Job)
                .filter(Job.id == job_id, Job.status == JobStatus.CLAIMED, Job.claimed_by == self.worker_id)
                .first()
            )
            if not job:
                db.commit()
                return None

            now = utcnow()
            job.status = JobStatus.RUNNING
            job.started_at = now
            job.heartbeat_at = now
            self._upsert_execution_start(db, job_id)
            db.commit()
            db.refresh(job)
            return job
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _mark_success(self, job_id: int) -> None:
        db = SessionLocal()
        try:
            job = db.query(Job).filter(Job.id == job_id).first()
            if not job:
                db.commit()
                return

            now = utcnow()
            if job.cron_expression:
                next_run = _compute_next_cron_run(job.run_at, job.cron_expression) or (now + timedelta(minutes=5))
                job.run_at = next_run
                job.status = JobStatus.SCHEDULED if next_run > now else JobStatus.QUEUED
                job.retry_count = 0
                job.finished_at = None
            else:
                job.status = JobStatus.COMPLETED
                job.finished_at = now

            execution = (
                db.query(JobExecution)
                .filter(
                    JobExecution.job_id == job_id,
                    JobExecution.worker_id == self.worker_id,
                    JobExecution.finished_at.is_(None),
                )
                .order_by(JobExecution.id.desc())
                .first()
            )
            if execution:
                execution.finished_at = now
                execution.status = JobStatus.COMPLETED.value
                execution.logs = "Job completed successfully"

            job.claimed_by = None
            job.claimed_at = None
            job.heartbeat_at = None
            job.last_error = None
            db.commit()
            print(f"[WORKER] Job {job_id} completed successfully.")
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _mark_failure(self, job_id: int, err: Exception) -> None:
        db = SessionLocal()
        try:
            job = db.query(Job).filter(Job.id == job_id).first()
            if not job:
                db.commit()
                return

            job.retry_count = int(job.retry_count or 0) + 1
            job.last_error = str(err)
            now = utcnow()

            if job.retry_count >= int(job.max_retries or 0):
                job.status = JobStatus.DEAD
                job.finished_at = now
                db.add(
                    DeadLetterJob(
                        job_id=job.id,
                        queue_id=job.queue_id,
                        payload=job.payload,
                        failure_reason=str(err),
                        failed_at=now,
                        retry_count=int(job.retry_count or 0),
                        max_retries=int(job.max_retries or 0),
                        worker_id=self.worker_id,
                    )
                )
                print(f"[WORKER DLQ] Job {job.id} moved to DEAD after {job.retry_count} attempts.")
            else:
                delay = calculate_backoff(job.retry_strategy or "fixed", job.retry_count)
                job.run_at = now + timedelta(seconds=delay)
                job.status = JobStatus.SCHEDULED if delay > 0 else JobStatus.QUEUED
                job.finished_at = None
                print(f"[WORKER RETRY] Job {job.id} failed, retry in {delay}s (attempt {job.retry_count}/{job.max_retries}).")

            execution = (
                db.query(JobExecution)
                .filter(
                    JobExecution.job_id == job_id,
                    JobExecution.worker_id == self.worker_id,
                    JobExecution.finished_at.is_(None),
                )
                .order_by(JobExecution.id.desc())
                .first()
            )
            if execution:
                execution.finished_at = now
                execution.status = JobStatus.DEAD.value if job.status == JobStatus.DEAD else JobStatus.FAILED.value
                execution.logs = str(err)

            job.claimed_by = None
            job.claimed_at = None
            job.heartbeat_at = None
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _execute_job(self, claimed_job: Job) -> None:
        try:
            running_job = self._set_running(claimed_job.id)
            if not running_job:
                return

            print(f"[WORKER] Executing Job ID {running_job.id} (Priority: {running_job.priority})")
            if "fail" in str(running_job.payload).lower():
                raise Exception("Simulated runtime processing pipeline exception.")

            self._mark_success(running_job.id)
        except Exception as err:
            self._mark_failure(claimed_job.id, err)
        finally:
            with self._in_flight_lock:
                self._in_flight_job_ids.discard(claimed_job.id)

    def run_forever(self) -> None:
        self.register_worker()
        last_heartbeat = 0.0
        print("[WORKER] Distributed Engine Worker initialized. Polling active...")

        try:
            while not SHUTDOWN_SIGNALED:
                now_ts = time.time()
                if now_ts - last_heartbeat >= self.heartbeat_interval_seconds:
                    self.heartbeat()
                    self.recover_stale_claims()
                    last_heartbeat = now_ts

                with self._in_flight_lock:
                    in_flight = len(self._in_flight_job_ids)

                if in_flight < self.max_workers:
                    job = self.claim_job()
                    if job:
                        self._pool.submit(self._execute_job, job)

                time.sleep(self.poll_interval_seconds)
        finally:
            self._pool.shutdown(wait=True)
            self.mark_shutdown()
            print("[WORKER] Engine safely stopped. Active tasks drained, worker marked STOPPED.")


if __name__ == "__main__":
    runtime = WorkerRuntime()
    runtime.run_forever()
    sys.exit(0)
