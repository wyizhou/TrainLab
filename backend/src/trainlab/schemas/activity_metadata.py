from pydantic import BaseModel


class ActivityNameUpdate(BaseModel):
    name: str | None
