from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.debate import DebateStatus


class DebateCreate(BaseModel):
    title: str = Field(min_length=3, max_length=250)
    fixed_question: str = Field(min_length=5)
    description: str | None = None
    question_population: str | None = Field(default=None, max_length=300)
    question_timeframe: str | None = Field(default=None, max_length=300)
    question_geography: str | None = Field(default=None, max_length=300)
    question_metric: str | None = Field(default=None, max_length=300)


class DebateRead(DebateCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: DebateStatus
    owner_user_id: int | None = None
    created_at: datetime
