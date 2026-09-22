from datetime import date, datetime
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ScheduleRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: datetime  # Local wall-clock time, accompanied by an IANA timezone.
    timezone: str = "Asia/Beirut"
    frequency: Literal["once", "daily", "weekly", "monthly"] = "once"
    interval: int = Field(default=1, ge=1, le=365)
    end_date: date | None = None

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(
                "Choose a valid IANA timezone, such as Asia/Beirut."
            ) from exc
        return value

    @model_validator(mode="after")
    def valid_dates(self):
        if self.start.tzinfo is not None:
            raise ValueError("Start must be a local time without an offset.")
        if self.end_date is not None and self.end_date < self.start.date():
            raise ValueError("End date cannot be before the start date.")
        return self


class SubmitPreview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    preview_id: UUID
    schedule: ScheduleRule | None = None
    draft_id: UUID | None = None
    draft_revision: int | None = Field(default=None, ge=1)


class ScheduleEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schedule: ScheduleRule
    revision: int = Field(ge=1)


class DraftInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    selected_company_rows: list[int] = Field(default_factory=list, max_length=100)
    subject: str = Field(default="", max_length=200)
    content: str = Field(default="", max_length=20_000)
    schedule: ScheduleRule | None = None
    revision: int | None = Field(default=None, ge=1)

    @field_validator("selected_company_rows")
    @classmethod
    def valid_rows(cls, rows: list[int]) -> list[int]:
        if any(row < 1 for row in rows):
            raise ValueError("Recipient rows must be positive integers.")
        return list(dict.fromkeys(rows))


class MessageAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["graph", "draft", "job"]
    id: str = Field(min_length=1, max_length=2048)
    action: Literal["trash", "restore", "delete", "read", "unread", "resume", "pause"]
    destination: Literal["inbox", "sentitems"] | None = None


class BulkAction(BaseModel):
    items: list[MessageAction] = Field(min_length=1, max_length=100)
