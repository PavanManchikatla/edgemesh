from datetime import datetime, timezone

from pydantic import BaseModel, Field

from models.enums import JobStatus, TaskType


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Job(BaseModel):
    id: str = Field(min_length=1, max_length=128)
    type: TaskType
    status: JobStatus = JobStatus.QUEUED
    payload_ref: str | None = Field(default=None, max_length=512)
    assigned_node_id: str | None = Field(default=None, max_length=128)
    attempts: int = Field(default=0, ge=0)
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = Field(default=None, max_length=2048)
