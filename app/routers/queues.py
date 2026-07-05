from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Queue, User, Project, OrganizationMembership, Job
from app.schemas import QueueCreate, QueueOut, PaginatedMeta
from app.auth import get_current_user

router = APIRouter(prefix="/api/queues", tags=["Queue Management"])

def _user_has_project_access(db: Session, user_id: int, project_id: int) -> bool:
    return (
        db.query(Project)
        .join(OrganizationMembership, OrganizationMembership.organization_id == Project.organization_id)
        .filter(
            Project.id == project_id,
            OrganizationMembership.user_id == user_id,
        )
        .first()
        is not None
    )

def _user_has_queue_access(db: Session, user_id: int, queue_id: int) -> Queue | None:
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

@router.post("", response_model=QueueOut)
def create_queue(q: QueueCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    # 1. Deduplication Guard
    if db.query(Queue).filter(Queue.name == q.name).first():
        raise HTTPException(status_code=400, detail="Queue name already exists")

    # 2. Ensure authenticated user can access target project through org membership
    if not _user_has_project_access(db, current_user.id, q.project_id):
        raise HTTPException(status_code=403, detail="Not authorized to create queue in this project")

    # 3. Extract explicit parameters safely to dodge database structural default gaps
    new_queue = Queue(
        name=q.name,
        priority=q.priority,
        concurrency=q.concurrency,
        retry_count=q.retry_count,
        retry_strategy=q.retry_strategy,
        project_id=q.project_id,
        paused=False
    )

    try:
        db.add(new_queue)
        db.commit()
        db.refresh(new_queue)
        return new_queue
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database instantiation failure: {str(e)}")

@router.patch("/{queue_id}/pause")
def pause_queue(queue_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    q = _user_has_queue_access(db, current_user.id, queue_id)
    if not q:
        raise HTTPException(status_code=404, detail="Queue not found or inaccessible")
    q.paused = True
    db.commit()
    return {"message": f"Queue '{q.name}' paused successfully"}

@router.delete("/{queue_id}")
def delete_queue(queue_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    q = _user_has_queue_access(db, current_user.id, queue_id)
    if not q:
        raise HTTPException(status_code=404, detail="Queue not found or inaccessible")

    if db.query(Job).filter(Job.queue_id == queue_id).first():
        raise HTTPException(status_code=409, detail="Cannot delete a queue that still has jobs")

    db.delete(q)
    db.commit()
    return {"message": f"Queue '{q.name}' deleted successfully"}

@router.patch("/{queue_id}/resume")
def resume_queue(queue_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    q = _user_has_queue_access(db, current_user.id, queue_id)
    if not q:
        raise HTTPException(status_code=404, detail="Queue not found or inaccessible")
    q.paused = False
    db.commit()
    return {"message": f"Queue '{q.name}' resumed successfully"}

@router.get("")
def list_queues(
    limit: int = Query(20, ge=0, le=100),
    offset: int = Query(0, ge=0),
    project_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = (
        db.query(Queue)
        .join(Project, Project.id == Queue.project_id)
        .join(OrganizationMembership, OrganizationMembership.organization_id == Project.organization_id)
        .filter(OrganizationMembership.user_id == current_user.id)
    )
    if project_id is not None:
        query = query.filter(Queue.project_id == project_id)

    total = query.count()
    rows = query.order_by(Queue.id.desc()).offset(offset).limit(limit).all()

    return {
        "data": [
            {
                "id": q.id,
                "name": q.name,
                "priority": q.priority,
                "concurrency": q.concurrency,
                "retry_count": q.retry_count,
                "retry_strategy": q.retry_strategy.value if hasattr(q.retry_strategy, "value") else str(q.retry_strategy),
                "paused": q.paused,
                "project_id": q.project_id,
            }
            for q in rows
        ],
        "meta": PaginatedMeta(limit=limit, offset=offset, count=total).model_dump(),
    }


@router.get("/{queue_id}/stats")
def queue_stats(queue_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    q = _user_has_queue_access(db, current_user.id, queue_id)
    if not q:
        raise HTTPException(status_code=404, detail="Queue not found or inaccessible")

    status_rows = (
        db.query(Job.status, func.count(Job.id))
        .filter(Job.queue_id == queue_id)
        .group_by(Job.status)
        .all()
    )

    status_counts = {
        (status.value if hasattr(status, "value") else str(status)): count
        for status, count in status_rows
    }
    total_jobs = sum(status_counts.values())

    return {
        "queue_id": q.id,
        "queue_name": q.name,
        "paused": q.paused,
        "total_jobs": total_jobs,
        "by_status": status_counts,
    }
