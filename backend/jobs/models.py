from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel

from backend.core.db import from_json


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    RETRYING = "retrying"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_final(self) -> bool:
        return self in (JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED)


class Job(BaseModel):
    id: str
    type: str
    status: JobStatus
    resource: str
    params: dict[str, Any]
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    progress: float = 0.0
    message: str = ""
    attempts: int = 0
    max_attempts: int = 1
    provider: str | None = None
    parent_id: str | None = None
    retry_of: str | None = None
    project: str | None = None
    label: str | None = None
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    updated_at: str

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> Job:
        data = dict(row)
        data["params"] = from_json(data.get("params"), {})
        data["result"] = from_json(data.get("result"))
        data["error"] = from_json(data.get("error"))
        return cls(**data)

    @property
    def is_final(self) -> bool:
        return self.status.is_final
