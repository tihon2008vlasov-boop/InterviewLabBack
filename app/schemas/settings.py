from typing import Literal

from pydantic import BaseModel, EmailStr, Field

# Картинка приходит либо ссылкой `/files/<id>`, либо data URL. Base64 раздувает
# файл примерно в 1.37 раза, поэтому потолок поля выше реального лимита в 2 МБ —
# точную проверку размера делает app.services.images с понятной ошибкой.
IMAGE_FIELD_MAX_CHARS = 3_000_000


class ProfilePatch(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    email: EmailStr
    avatar_url: str = Field(default="", max_length=IMAGE_FIELD_MAX_CHARS)


class CompanyPatch(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    website: str = Field(default="", max_length=300)
    logo_url: str = Field(default="", max_length=IMAGE_FIELD_MAX_CHARS)


class NotificationPatch(BaseModel):
    candidate_completed: bool
    weekly_report: bool
    ai_analysis: bool
    team_activity: bool
    product_updates: bool


class PasswordChangeIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=72)


class TeamMemberCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    role: Literal["admin", "recruiter", "viewer"] = "recruiter"
