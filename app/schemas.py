from pydantic import BaseModel, EmailStr, ConfigDict
from typing import Optional, List, Dict, Any
from datetime import datetime
from app.models import RetryStrategy, OrganizationRole

# User Data Layouts
class UserCreate(BaseModel):
    email: EmailStr
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str

# Organization Data Layouts
class OrganizationCreate(BaseModel):
    name: str

class OrganizationOut(BaseModel):
    id: int
    name: str
    role: OrganizationRole

# Project Data Layouts
class ProjectCreate(BaseModel):
    name: str
    organization_id: int

class ProjectOut(BaseModel):
    id: int
    name: str
    organization_id: int
    model_config = ConfigDict(from_attributes=True)

# Queue Data Layouts
class QueueCreate(BaseModel):
    name: str
    priority: Optional[int] = 1
    concurrency: Optional[int] = 5
    retry_count: Optional[int] = 3
    retry_strategy: Optional[RetryStrategy] = RetryStrategy.FIXED
    project_id: int

class QueueOut(BaseModel):
    id: int
    name: str
    priority: int
    concurrency: int
    retry_count: int
    retry_strategy: RetryStrategy
    paused: bool
    model_config = ConfigDict(from_attributes=True)

# Job Data Layouts
class JobCreate(BaseModel):
    payload: Dict[str, Any]
    queue_id: int
    run_at: Optional[datetime] = None
    cron_expression: Optional[str] = None
    priority: Optional[int] = None
    max_retries: Optional[int] = None
    retry_strategy: Optional[RetryStrategy] = None

class JobBatchCreate(BaseModel):
    jobs: List[Dict[str, Any]]
    queue_id: int
    run_at: Optional[datetime] = None
    cron_expression: Optional[str] = None
    priority: Optional[int] = None
    max_retries: Optional[int] = None
    retry_strategy: Optional[RetryStrategy] = None

# API Response Envelopes
class ErrorEnvelope(BaseModel):
    error: str
    detail: Optional[Any] = None
    path: Optional[str] = None

class PaginatedMeta(BaseModel):
    limit: int
    offset: int
    count: int

class PaginatedResponse(BaseModel):
    data: List[Any]
    meta: PaginatedMeta
