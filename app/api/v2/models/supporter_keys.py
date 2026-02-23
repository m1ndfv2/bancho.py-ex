from __future__ import annotations

from datetime import datetime

from pydantic import Field

from . import BaseModel


class RedeemSupporterKeyRequest(BaseModel):
    code: str = Field(pattern=r"^[A-Z0-9]{8}-[A-Z0-9]{8}-[A-Z0-9]{8}$")


class GenerateSupporterKeysRequest(BaseModel):
    amount: int = Field(ge=1, le=500)
    duration_days: int = Field(alias="durationDays", ge=1, le=3650)
    note: str | None = Field(default=None, max_length=255)
    batch_id: str | None = Field(default=None, alias="batchId", max_length=64)


class SupporterKeyItem(BaseModel):
    id: int
    code: str
    duration_days: int
    created_by: int
    used_by: int
    created_at: datetime
    used_at: datetime | None
    batch_id: str | None
    note: str | None
