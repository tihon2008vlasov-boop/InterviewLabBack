from datetime import datetime, timezone
from typing import Literal

from beanie import Document, Indexed
from pydantic import EmailStr, Field

Role = Literal["owner", "admin", "recruiter", "viewer"]


class User(Document):
    name: str
    email: Indexed(EmailStr, unique=True)
    password_hash: str
    role: Role = "owner"
    company_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "users"
