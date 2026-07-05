from fastapi import APIRouter, Depends
from sqlalchemy import func, text
from sqlalchemy.orm import Session
from sqlalchemy import delete

from app.auth import get_current_user
from app.database import get_db
from app.models import (
    DeadLetterJob,
    Job,
    JobExecution,
    Queue,
    User,
    WorkerHeartbeat,
    WorkerRegistration,
)

router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])


@router.get("/health")
def dashboard_health(current_user: User = Depends(get_current_user)):
    return {"status": "ok", "user_id": current_user.id}


@router.get("/queues")
def dashboard_queues(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    total = db.query(func.count(Queue.id)).scalar() or 0
    paused = db.query(func.count(Queue.id)).filter(Queue.paused.is_(True)).scalar() or 0
    active = total - paused
    return {"total_queues": total, "active_queues": active, "paused_queues": paused}


@router.get("/jobs")
def dashboard_jobs(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    # Use raw SQL for resilience against historical enum casing drift in existing DB rows.
    by_status_rows = db.execute(
        text("SELECT status, COUNT(id) AS c FROM jobs GROUP BY status")
    ).all()

    recent_rows = db.execute(
        text(
            """
            SELECT id, status, queue_id, priority, run_at
            FROM jobs
            ORDER BY id DESC
            LIMIT 10
            """
        )
    ).all()

    return {
        "by_status": {str(row[0]).upper(): row[1] for row in by_status_rows},
        "recent_jobs": [
            {
                "id": row[0],
                "status": str(row[1]).upper() if row[1] is not None else None,
                "queue_id": row[2],
                "priority": row[3],
                "run_at": row[4].isoformat() if row[4] else None,
            }
            for row in recent_rows
        ],
    }


@router.get("/workers")
def dashboard_workers(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    workers = db.query(WorkerRegistration).order_by(WorkerRegistration.id.desc()).limit(20).all()
    recent_heartbeats = db.query(WorkerHeartbeat).order_by(WorkerHeartbeat.id.desc()).limit(20).all()

    return {
        "workers": [
            {
                "worker_id": w.worker_id,
                "hostname": w.hostname,
                "pid": w.pid,
                "status": w.status,
                "last_heartbeat_at": w.last_heartbeat_at.isoformat() if w.last_heartbeat_at else None,
                "shutdown_at": w.shutdown_at.isoformat() if w.shutdown_at else None,
            }
            for w in workers
        ],
        "recent_heartbeats": [
            {
                "worker_id": hb.worker_id,
                "heartbeat_at": hb.heartbeat_at.isoformat() if hb.heartbeat_at else None,
                "status": hb.status,
                "note": hb.note,
            }
            for hb in recent_heartbeats
        ],
    }


@router.get("/executions")
def dashboard_executions(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    exec_total = db.query(func.count(JobExecution.id)).scalar() or 0
    dlq_total = db.query(func.count(DeadLetterJob.id)).scalar() or 0
    recent_exec = db.query(JobExecution).order_by(JobExecution.id.desc()).limit(20).all()
    recent_dlq = db.query(DeadLetterJob).order_by(DeadLetterJob.id.desc()).limit(20).all()

    return {
        "execution_total": exec_total,
        "dlq_total": dlq_total,
        "recent_executions": [
            {
                "id": e.id,
                "job_id": e.job_id,
                "worker_id": e.worker_id,
                "status": e.status,
                "started_at": e.started_at.isoformat() if e.started_at else None,
                "finished_at": e.finished_at.isoformat() if e.finished_at else None,
                "logs": e.logs,
            }
            for e in recent_exec
        ],
        "recent_dlq": [
            {
                "id": d.id,
                "job_id": d.job_id,
                "queue_id": d.queue_id,
                "failure_reason": d.failure_reason,
                "failed_at": d.failed_at.isoformat() if d.failed_at else None,
                "retry_count": d.retry_count,
                "max_retries": d.max_retries,
                "worker_id": d.worker_id,
            }
            for d in recent_dlq
        ],
    }


@router.delete("/cleanup")
def cleanup_demo_data(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    deleted_heartbeats = db.query(WorkerHeartbeat).delete(synchronize_session=False)
    deleted_execs = db.query(JobExecution).delete(synchronize_session=False)
    deleted_dlq = db.query(DeadLetterJob).delete(synchronize_session=False)
    deleted_workers = db.query(WorkerRegistration).delete(synchronize_session=False)
    deleted_jobs = db.query(Job).delete(synchronize_session=False)
    db.commit()
    return {
        "deleted_jobs": deleted_jobs,
        "deleted_executions": deleted_execs,
        "deleted_dlq": deleted_dlq,
        "deleted_workers": deleted_workers,
        "deleted_heartbeats": deleted_heartbeats,
    }
