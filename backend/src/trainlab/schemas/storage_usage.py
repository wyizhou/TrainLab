from pydantic import BaseModel, Field


class StorageUsageResponse(BaseModel):
    used_bytes: int = Field(serialization_alias="usedBytes")
    file_count: int = Field(serialization_alias="fileCount")
    max_bytes: int = Field(serialization_alias="maxBytes")
    max_files: int = Field(serialization_alias="maxFiles")
    remaining_bytes: int = Field(serialization_alias="remainingBytes")
    remaining_files: int = Field(serialization_alias="remainingFiles")
