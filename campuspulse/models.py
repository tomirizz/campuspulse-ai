from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SourceRef(BaseModel):
    model_config = ConfigDict(extra="ignore")
    material_id: str = Field(min_length=1, max_length=64)
    page: int = Field(ge=1, le=20)
    line: int = Field(ge=1)
    start: int = Field(ge=0)
    quote: str = Field(min_length=1, max_length=1000)


class TaskInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=160)
    course: str = Field(min_length=1, max_length=80)
    due_at: datetime
    estimated_minutes: int = Field(default=60, ge=15, le=2400)
    priority: Literal["normal", "high"] = "normal"
    notes: str = Field(default="", max_length=2000)
    source: SourceRef | None = None

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
    busy: list[BusyBlock] = Field(default_factory=list, max_length=5000)
    event_minutes: int = Field(default=60, ge=5, le=1440)

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


class SearchInput(BaseModel):
    query: str = Field(min_length=2, max_length=500)


class ScenarioInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    daily_minutes: int | None = Field(default=None, ge=30, le=480)
    start_hour: int | None = Field(default=None, ge=0, le=22)
    end_hour: int | None = Field(default=None, ge=1, le=24)
    busy: list[BusyBlock] | None = Field(default=None, max_length=60)
    delay_days: int = Field(default=0, ge=0, le=13)
    days: int = Field(default=7, ge=1, le=14)


class GradeComponent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    weight: float = Field(gt=0, le=100, allow_inf_nan=False)
    score: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    max_score: float = Field(gt=0, le=100000, allow_inf_nan=False)


class GradeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target: float = Field(ge=0, le=100, allow_inf_nan=False)
    components: list[GradeComponent] = Field(min_length=2, max_length=20)
    source: SourceRef | None = None
    confirmed: Literal[True]


class DiagnosticInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=1, max_length=60000)
    language: Literal["python", "json"] = "python"
    filename: str = Field(default="snippet.py", min_length=1, max_length=160)


class QuestStart(BaseModel):
    model_config = ConfigDict(extra="forbid")
    material_id: str = Field(min_length=1, max_length=64)
    question_ids: list[str] = Field(min_length=1, max_length=20)
    confirmed: Literal[True]


class QuestAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question_id: str = Field(min_length=1, max_length=64)
    answer: str = Field(min_length=1, max_length=300)
