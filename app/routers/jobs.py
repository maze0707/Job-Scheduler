from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from datetime import datetime, timezone
from app.database import get_db
from app.models import Job, Queue, JobStatus, User, Project, OrganizationMembership
from app.schemas import JobCreate, JobBatchCreate, PaginatedMeta
from app.auth import get_current_user

router = APIRouter(prefix="/api/jobs", tags=["Job Operations"])


def _normalize_to_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _validate_cron_expression(expr: str | None) -> None:
    if not expr:
        return
    parts = expr.strip().split()
    if len(parts) != 5:
        raise HTTPException(status_code=400, detail="Invalid cron_expression. Expected 5 fields.")
    for idx, part in enumerate(parts):
        if part == "*":
            continue
        if part.startswith("*/"):
            step = part[2:]
            if not step.isdigit() or int(step) <= 0:
                raise HTTPException(status_code=400, detail=f"Invalid cron_expression step in field {idx + 1}")
            continue
        if part.isdigit():
            continue
        raise HTTPException(status_code=400, detail=f"Invalid cron_expression token '{part}' in field {idx + 1}")


def _get_accessible_queue(db: Session, user_id: int, queue_id: int) -> Queue | None:
    return (
        db.query(Queue)
        .join(Project, Project.id == Queue.project_id)
        .join(OrganizationMembership, OrganizationMembership.organization_id == Project.organization_id)
        .filter(
            Queue.id == queue_id,
            OrganizationMembership.user_id == user_id,
        )
        .first()
    )


@router.post("", status_code=status.HTTP_201_CREATED)
def create_job(j: JobCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    q = _get_accessible_queue(db, current_user.id, j.queue_id)
    if not q:
        raise HTTPException(status_code=404, detail="Target Queue does not exist or is inaccessible")

    _validate_cron_expression(j.cron_expression)
    now = datetime.now(timezone.utc)
    run_time = _normalize_to_utc(j.run_at) if j.run_at else now
    initial_status = JobStatus.SCHEDULED if run_time > now else JobStatus.QUEUED

    retry_strategy = j.retry_strategy if j.retry_strategy is not None else q.retry_strategy
    max_retries = j.max_retries if j.max_retries is not None else q.retry_count
    priority = j.priority if j.priority is not None else q.priority

    new_job = Job(
        payload=j.payload,
        queue_id=j.queue_id,
        retries_left=max_retries,
        run_at=run_time,
        cron_expression=j.cron_expression,
        status=initial_status,
        priority=priority,
        retry_count=0,
        max_retries=max_retries,
        retry_strategy=retry_strategy,
    )
    db.add(new_job)
    db.commit()
    db.refresh(new_job)
    return {"message": "Job scheduled successfully", "job_id": new_job.id, "status": new_job.status}


@router.post("/batch", status_code=status.HTTP_201_CREATED)
def create_batch_jobs(batch: JobBatchCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    q = _get_accessible_queue(db, current_user.id, batch.queue_id)
    if not q:
        raise HTTPException(status_code=404, detail="Target Queue does not exist or is inaccessible")

    _validate_cron_expression(batch.cron_expression)
    now = datetime.now(timezone.utc)
    run_time = _normalize_to_utc(batch.run_at) if batch.run_at else now
    initial_status = JobStatus.SCHEDULED if run_time > now else JobStatus.QUEUED
    retry_strategy = batch.retry_strategy if batch.retry_strategy is not None else q.retry_strategy
    max_retries = batch.max_retries if batch.max_retries is not None else q.retry_count
    priority = batch.priority if batch.priority is not None else q.priority

    for item in batch.jobs:
        new_job = Job(
            payload=item,
            queue_id=batch.queue_id,
            retries_left=max_retries,
            run_at=run_time,
            cron_expression=batch.cron_expression,
            status=initial_status,
            priority=priority,
            retry_count=0,
            max_retries=max_retries,
            retry_strategy=retry_strategy,
        )
        db.add(new_job)
    db.commit()
    return {"message": f"Batch of {len(batch.jobs)} jobs queued successfully.", "status": initial_status}


@router.get("")
def list_jobs(
    limit: int = 20,
    offset: int = 0,
    status_filter: JobStatus | None = None,
    queue_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = (
        db.query(Job)
        .join(Queue, Queue.id == Job.queue_id)
        .join(Project, Project.id == Queue.project_id)
        .join(OrganizationMembership, OrganizationMembership.organization_id == Project.organization_id)
        .filter(OrganizationMembership.user_id == current_user.id)
    )

    if status_filter is not None:
        query = query.filter(Job.status == status_filter)
    if queue_id is not None:
        query = query.filter(Job.queue_id == queue_id)

    total = query.count()
    rows = query.order_by(Job.id.desc()).offset(offset).limit(limit).all()

    return {
        "data": [
            {
                "id": job.id,
                "queue_id": job.queue_id,
                "status": job.status.value if hasattr(job.status, "value") else str(job.status),
                "priority": job.priority,
                "retry_count": job.retry_count,
                "max_retries": job.max_retries,
                "run_at": job.run_at.isoformat() if job.run_at else None,
                "cron_expression": job.cron_expression,
                "claimed_by": job.claimed_by,
                "created_payload": job.payload,
            }
            for job in rows
        ],
        "meta": PaginatedMeta(limit=limit, offset=offset, count=total).model_dump(),
    }
