import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=512)


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID
    username: str
    display_name: str = Field(serialization_alias="displayName")
    is_owner: bool = Field(serialization_alias="isOwner")


class SessionResponse(BaseModel):
    user: UserResponse
    expires_at: datetime = Field(serialization_alias="expiresAt")


class LogoutResponse(BaseModel):
    status: str = "logged_out"
