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
    library_stale: bool = False
    library_entry_id: int | None = None
    library_served: bool = False
    library_last_reviewed_at: datetime | None = None
    library_reevaluation_pending: bool = False
    library_notice: str | None = None
    created_at: datetime
