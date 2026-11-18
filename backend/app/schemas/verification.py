from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.verification import RecordedVerificationStatus, VerificationSubject


class VerificationEventCreate(BaseModel):
    subject_type: VerificationSubject
    subject_id: int
    result_status: RecordedVerificationStatus
    method: str = Field(min_length=3, max_length=200)
    archive_url: str | None = Field(default=None, max_length=2048)
    snapshot_hash: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def require_evidence(self):
        archive = (self.archive_url or "").strip()
        snapshot = (self.snapshot_hash or "").strip()
        if not archive and not snapshot:
            raise ValueError("A verification event requires an archive URL or a snapshot hash")
        self.archive_url = archive or None
        self.snapshot_hash = snapshot or None
        self.method = self.method.strip()
        return self


class VerificationEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    subject_type: VerificationSubject
    subject_id: int
    result_status: RecordedVerificationStatus
    actor_user_id: int
    method: str
    archive_url: str | None
    snapshot_hash: str | None
    created_at: datetime
