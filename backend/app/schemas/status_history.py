from datetime import datetime

from pydantic import BaseModel, ConfigDict


class StatusHistoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    subject_type: str
    subject_id: int
    previous_status: str
    new_status: str
    note: str
    verification_event_id: int | None = None
    created_at: datetime
