from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TaskInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=160)
    course: str = Field(min_length=1, max_length=80)
    due_at: datetime
    estimated_minutes: int = Field(default=60, ge=15, le=2400)
    priority: Literal["normal", "high"] = "normal"
    notes: str = Field(default="", max_length=2000)

    @field_validator("due_at")
    @classmethod
    def aware_date(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Укажите дату с часовым поясом, например +05:00")
        return value


class TaskPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    completed: bool


class BusyBlock(BaseModel):
    start: datetime
    end: datetime

    @field_validator("start", "end")
    @classmethod
    def aware_date(cls, value):
        return TaskInput.aware_date(value)


class Preferences(BaseModel):
    model_config = ConfigDict(extra="forbid")
    timezone: str = "Asia/Almaty"
    daily_minutes: int = Field(default=180, ge=30, le=480)
    start_hour: int = Field(default=16, ge=0, le=22)
    end_hour: int = Field(default=22, ge=1, le=24)
    busy: list[BusyBlock] = Field(default_factory=list, max_length=60)

    @field_validator("timezone")
    @classmethod
    def known_timezone(cls, value):
        try:
            ZoneInfo(value)
        except Exception:
            raise ValueError("Неизвестный часовой пояс")
        return value


class ChatInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    message: str = Field(min_length=1, max_length=4000)


class GitHubInput(BaseModel):
    repository: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")
