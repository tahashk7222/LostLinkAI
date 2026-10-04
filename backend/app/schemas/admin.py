from pydantic import BaseModel, Field

from app.models.enums import ModerationReason


class RejectIn(BaseModel):
    reason: ModerationReason
    note: str | None = Field(default=None, max_length=500)
