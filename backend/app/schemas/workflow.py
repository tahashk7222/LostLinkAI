from typing import Literal

from pydantic import BaseModel, Field

from app.models.enums import CaseStatus


class VerificationAnswersIn(BaseModel):
    answers: dict[str, str] = Field(max_length=5)


class VerifyDecisionIn(BaseModel):
    decision: Literal["ACCEPT", "REJECT"]
    note: str | None = Field(default=None, max_length=500)


class CaseStatusIn(BaseModel):
    status: CaseStatus


class MessageIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


class FlagIn(BaseModel):
    entity_type: Literal["report", "user"]
    entity_id: int
    reason: str = Field(min_length=5, max_length=500)
