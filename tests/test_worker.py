from datetime import datetime, timedelta, timezone
import random
import threading

from app.database import SessionLocal
from app.models import (
    DeadLetterJob,
    Job,
    JobExecution,
    JobLog,
    JobStatus,
    Organization,
    OrganizationMembership,
    OrganizationRole,
    Project,
    Queue,
    User,
    WorkerHeartbeat,
)
from app.worker import WorkerRuntime


def _seed_scope():
    db = SessionLocal()
    try:
        rnd = random.randint(10000, 99999)
        email = f"worker_tester_{rnd}@example.com"
        org_name = f"worker-org-{rnd}"
        project_name = f"worker-project-{rnd}"
        queue_name = f"worker-queue-{rnd}"

        user = User(email=email, hashed_password="x", is_active=True)
        db.add(user)
        db.flush()

        org = Organization(name=org_name)
        db.add(org)
        db.flush()

        membership = OrganizationMembership(
            organization_id=org.id,
            user_id=user.id,
            role=OrganizationRole.OWNER,
        )
        db.add(membership)

        project = Project(name=project_name, owner_id=user.id, organization_id=org.id)
        db.add(project)
        db.flush()

        queue = Queue(
            name=queue_name,
            project_id=project.id,
            priority=5,
            concurrency=3,
            retry_count=3,
            retry_strategy="FIXED",
            paused=False,
        )
        db.add(queue)
        db.commit()
        db.refresh(queue)
        return queue.id
    finally:
        db.close()


def _create_job(
    queue_id: int,
    payload: dict,
    status: JobStatus = JobStatus.QUEUED,
    run_at=None,
    max_retries=3,
    retry_strategy="FIXED",
    priority=999,
):
    db = SessionLocal()
    try:
        job = Job(
            payload=payload,
            queue_id=queue_id,
            retries_left=max_retries,
            run_at=run_at or datetime.now(timezone.utc),
            status=status,
            priority=priority,
            retry_count=0,
            max_retries=max_retries,
            retry_strategy=retry_strategy,
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        return job.id
    finally:
        db.close()


def _get_job(job_id: int) -> Job:
    db = SessionLocal()
    try:
        return db.query(Job).filter(Job.id == job_id).first()
    finally:
        db.close()


def test_worker_claim_run_complete_lifecycle():
    queue_id = _seed_scope()
    job_id = _create_job(queue_id, {"task": "ok"})

    runtime = WorkerRuntime(max_workers=1)

    runtime.register_worker()
    claimed = runtime.claim_job()
    assert claimed is not None
    assert claimed.id == job_id
    assert claimed.status == JobStatus.CLAIMED

    runtime._execute_job(claimed)

    job = _get_job(job_id)
    assert job.status == JobStatus.COMPLETED
    assert job.claimed_by is None
    assert job.claimed_at is None
    assert job.heartbeat_at is None
    assert job.finished_at is not None

    runtime.mark_shutdown()


def test_worker_retry_and_dead_routing():
    queue_id = _seed_scope()
    job_id = _create_job(queue_id, {"task": "fail"}, max_retries=1, retry_strategy="FIXED", priority=999)

    runtime = WorkerRuntime(max_workers=1)

    runtime.register_worker()
    claimed = runtime.claim_job()
    assert claimed is not None
    assert claimed.id == job_id

    runtime._execute_job(claimed)

    job = _get_job(job_id)
    assert job.status == JobStatus.DEAD
    assert job.retry_count == 1
    assert job.last_error is not None
    assert "Simulated runtime" in job.last_error

    db = SessionLocal()
    try:
        dead = db.query(DeadLetterJob).filter(DeadLetterJob.job_id == job_id).first()
        assert dead is not None
        assert dead.queue_id == queue_id
    finally:
        db.close()

    runtime.mark_shutdown()


def test_worker_persists_execution_logs_on_failure():
    queue_id = _seed_scope()
    job_id = _create_job(queue_id, {"task": "log-fail"}, max_retries=1, retry_strategy="FIXED", priority=999)

    runtime = WorkerRuntime(max_workers=1)
    runtime.register_worker()
    claimed = runtime.claim_job()
    assert claimed is not None
    assert claimed.id == job_id

    runtime._execute_job(claimed)

    db = SessionLocal()
    try:
        execution = (
            db.query(JobExecution)
            .filter(JobExecution.job_id == job_id)
            .order_by(JobExecution.id.desc())
            .first()
        )
        assert execution is not None
        logs = db.query(JobLog).filter(JobLog.job_execution_id == execution.id).all()
        assert logs
        assert any("Simulated runtime" in entry.message for entry in logs)
    finally:
        db.close()

    runtime.mark_shutdown()


def test_worker_stale_claim_recovery():
    queue_id = _seed_scope()
    old_time = datetime.now(timezone.utc) - timedelta(minutes=10)
    job_id = _create_job(queue_id, {"task": "stale"})

    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        job.status = JobStatus.CLAIMED
        job.claimed_by = "stale-worker"
        job.claimed_at = old_time
        job.heartbeat_at = old_time
        db.commit()
    finally:
        db.close()

    runtime = WorkerRuntime(max_workers=1, claim_timeout_seconds=30)
    runtime.recover_stale_claims()

    job = _get_job(job_id)
    assert job.status == JobStatus.QUEUED
    assert job.claimed_by is None
    assert job.claimed_at is None
    assert job.heartbeat_at is None
    assert job.last_error is not None


def test_worker_records_execution_and_heartbeat():
    queue_id = _seed_scope()
    job_id = _create_job(queue_id, {"task": "ok-audit"}, retry_strategy="FIXED")

    runtime = WorkerRuntime(max_workers=1)
    runtime.register_worker()
    runtime.heartbeat()

    db = SessionLocal()
    try:
        hb = db.query(WorkerHeartbeat).order_by(WorkerHeartbeat.id.desc()).first()
        assert hb is not None
        assert hb.worker_id == runtime.worker_id
    finally:
        db.close()

    # Drain claims until our seeded job is claimed (suite DB may contain residual queued jobs).
    claimed_target = None
    for _ in range(10):
        claimed = runtime.claim_job()
        if not claimed:
            break
        if claimed.id == job_id:
            claimed_target = claimed
            break

    assert claimed_target is not None
    runtime._execute_job(claimed_target)

    db = SessionLocal()
    try:
        exec_row = (
            db.query(JobExecution)
            .filter(JobExecution.job_id == job_id)
            .order_by(JobExecution.id.desc())
            .first()
        )
        assert exec_row is not None
        assert exec_row.started_at is not None
        assert exec_row.finished_at is not None
        assert exec_row.status in ("COMPLETED", "FAILED")
    finally:
        db.close()

    runtime.mark_shutdown()


def test_worker_claim_contention_only_one_claims_same_job():
    queue_id = _seed_scope()
    target_job_id = _create_job(queue_id, {"task": "contention"}, status=JobStatus.QUEUED)

    runtime_a = WorkerRuntime(max_workers=1)
    runtime_b = WorkerRuntime(max_workers=1)
    runtime_a.register_worker()
    runtime_b.register_worker()

    barrier = threading.Barrier(2)
    results = []
    results_lock = threading.Lock()

    def _claim(runtime):
        barrier.wait()
        claimed = runtime.claim_job()
        with results_lock:
            results.append(claimed.id if claimed else None)

    t1 = threading.Thread(target=_claim, args=(runtime_a,))
    t2 = threading.Thread(target=_claim, args=(runtime_b,))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    claimed_ids = [r for r in results if r is not None]
    target_claims = [cid for cid in claimed_ids if cid == target_job_id]

    assert len(target_claims) == 1

    runtime_a.mark_shutdown()
    runtime_b.mark_shutdown()
