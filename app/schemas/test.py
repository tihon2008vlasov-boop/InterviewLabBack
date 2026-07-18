from pydantic import BaseModel, EmailStr, Field

from app.models.test import Level, TestStatus, TestTask


class TestIn(BaseModel):
    name: str = Field(min_length=3)
    description: str = ""
    level: Level = "middle"
    language: str
    duration_min: int = 60
    tasks: list[TestTask] = Field(default_factory=list)


class TestPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    level: Level | None = None
    language: str | None = None
    duration_min: int | None = None
    status: TestStatus | None = None
    tasks: list[TestTask] | None = None


class LinkIn(BaseModel):
    expires_in_days: int | None = None
    max_uses: int | None = None


class InvitationsIn(BaseModel):
    emails: list[EmailStr] = Field(min_length=1)
    message: str = ""
