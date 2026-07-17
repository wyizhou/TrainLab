import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ImportListItem(BaseModel):
    import_id: uuid.UUID = Field(serialization_alias="importId")
    activity_id: uuid.UUID | None = Field(serialization_alias="activityId")
    source: str
    original_file_name: str = Field(serialization_alias="originalFileName")
    size_bytes: int = Field(serialization_alias="sizeBytes")
    status: Literal[
        "pending", "processing", "complete", "partial", "failed", "deleting", "delete_failed"
    ]
    created_at: datetime = Field(serialization_alias="createdAt")
    updated_at: datetime = Field(serialization_alias="updatedAt")
    attempt_count: int = Field(serialization_alias="attemptCount")
    last_attempt_at: datetime | None = Field(serialization_alias="lastAttemptAt")
    completed_at: datetime | None = Field(serialization_alias="completedAt")
    warning_count: int = Field(serialization_alias="warningCount")
    error_code: str | None = Field(serialization_alias="errorCode")
    error_message: str | None = Field(serialization_alias="errorMessage")
    retry_available: bool = Field(serialization_alias="retryAvailable")
    delete_retry_available: bool = Field(serialization_alias="deleteRetryAvailable")


class ImportListPage(BaseModel):
    items: list[ImportListItem]
    next_cursor: str | None = Field(serialization_alias="nextCursor")
