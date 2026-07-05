import enum
from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Enum, Text, JSON
from sqlalchemy.orm import relationship
from app.database import Base
from sqlalchemy.sql import func

class JobStatus(str, enum.Enum):
    SCHEDULED = "SCHEDULED"
    QUEUED = "QUEUED"
    CLAIMED = "CLAIMED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    DEAD = "DEAD"

class RetryStrategy(str, enum.Enum):
    FIXED = "FIXED"
    LINEAR = "LINEAR"
    EXPONENTIAL = "EXPONENTIAL"

class OrganizationRole(str, enum.Enum):
    OWNER = "OWNER"
    ADMIN = "ADMIN"
    MEMBER = "MEMBER"

class Organization(Base):
    __tablename__ = "organizations"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True, nullable=False)

    memberships = relationship("OrganizationMembership", back_populates="organization", cascade="all, delete-orphan")
    projects = relationship("Project", back_populates="organization")

class OrganizationMembership(Base):
    __tablename__ = "organization_memberships"
    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    role = Column(Enum(OrganizationRole), default=OrganizationRole.MEMBER, nullable=False)

    organization = relationship("Organization", back_populates="memberships")
    user = relationship("User", back_populates="organization_memberships")

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)

    projects = relationship("Project", back_populates="owner")
    organization_memberships = relationship("OrganizationMembership", back_populates="user", cascade="all, delete-orphan")

class Project(Base):
    __tablename__ = "projects"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    owner_id = Column(Integer, ForeignKey("users.id"))
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)

    owner = relationship("User", back_populates="projects")
    organization = relationship("Organization", back_populates="projects")
    queues = relationship("Queue", back_populates="project")

class Queue(Base):
    __tablename__ = "queues"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True, nullable=False)
    priority = Column(Integer, default=1)  # Higher number -> higher execution priority
    concurrency = Column(Integer, default=5)
    retry_count = Column(Integer, default=3)
    retry_strategy = Column(Enum(RetryStrategy), default=RetryStrategy.FIXED)
    paused = Column(Boolean, default=False)
    project_id = Column(Integer, ForeignKey("projects.id"))

    project = relationship("Project", back_populates="queues")
    jobs = relationship("Job", back_populates="queue")

class Job(Base):
    __tablename__ = "jobs"
    id = Column(Integer, primary_key=True, index=True)
    payload = Column(JSON, nullable=False)
    status = Column(Enum(JobStatus), default=JobStatus.QUEUED, index=True, nullable=False)
    retries_left = Column(Integer, nullable=False)
    run_at = Column(DateTime, default=datetime.utcnow, index=True)
    cron_expression = Column(String, nullable=True)
    queue_id = Column(Integer, ForeignKey("queues.id"), nullable=False)

    priority = Column(Integer, default=0)
    retry_count = Column(Integer, default=0)
    max_retries = Column(Integer, default=3)
    retry_strategy = Column(Enum(RetryStrategy), default=RetryStrategy.EXPONENTIAL, nullable=False)

    claimed_by = Column(String, nullable=True, index=True)
    claimed_at = Column(DateTime, nullable=True, index=True)
    heartbeat_at = Column(DateTime, nullable=True, index=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)

    queue = relationship("Queue", back_populates="jobs")
    executions = relationship("JobExecution", back_populates="job")

class WorkerRegistration(Base):
    __tablename__ = "worker_registrations"
    id = Column(Integer, primary_key=True, index=True)
    worker_id = Column(String, unique=True, index=True, nullable=False)
    hostname = Column(String, nullable=False)
    pid = Column(Integer, nullable=False)
    status = Column(String, nullable=False, default="ACTIVE")
    started_at = Column(DateTime, nullable=False, server_default=func.now())
    last_heartbeat_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
    shutdown_at = Column(DateTime, nullable=True)

    heartbeats = relationship("WorkerHeartbeat", back_populates="worker", cascade="all, delete-orphan")

class WorkerHeartbeat(Base):
    __tablename__ = "worker_heartbeats"
    id = Column(Integer, primary_key=True, index=True)
    worker_id = Column(String, ForeignKey("worker_registrations.worker_id"), nullable=False, index=True)
    heartbeat_at = Column(DateTime, nullable=False, server_default=func.now(), index=True)
    status = Column(String, nullable=False, default="ACTIVE")
    note = Column(String, nullable=True)

    worker = relationship("WorkerRegistration", back_populates="heartbeats")

class DeadLetterJob(Base):
    __tablename__ = "dead_letter_jobs"
    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False, index=True)
    queue_id = Column(Integer, ForeignKey("queues.id"), nullable=False, index=True)
    payload = Column(JSON, nullable=False)
    failure_reason = Column(Text, nullable=True)
    failed_at = Column(DateTime, nullable=False, server_default=func.now(), index=True)
    retry_count = Column(Integer, nullable=False, default=0)
    max_retries = Column(Integer, nullable=False, default=0)
    worker_id = Column(String, nullable=True, index=True)

class JobExecution(Base):
    __tablename__ = "job_executions"
    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False)
    worker_id = Column(String, nullable=False)
    started_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)
    logs = Column(Text, nullable=True)  # Integrated task logs for evaluation visibility
    status = Column(String, nullable=False)

    job = relationship("Job", back_populates="executions")