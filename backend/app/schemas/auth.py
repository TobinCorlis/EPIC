from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from app.core.email import normalize_email
from app.models.auth import UserRole

EmailAddress = Annotated[str, BeforeValidator(normalize_email)]

class RegisterRequest(BaseModel):
    email: EmailAddress
    display_name: str = Field(min_length=2, max_length=120)
    password: str = Field(min_length=8, max_length=128)

class LoginRequest(BaseModel):
    email: EmailAddress
    password: str

class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: str
    display_name: str
    role: UserRole
    created_at: datetime

class TokenRead(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    user: UserRead
