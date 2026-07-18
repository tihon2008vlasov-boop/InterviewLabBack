from typing import Literal

from beanie import Document, Indexed
from pydantic import EmailStr

Role = Literal["owner", "admin", "recruiter", "viewer"]


class User(Document):
    name: str
    email: Indexed(EmailStr, unique=True)
    password_hash: str
    role: Role = "owner"
    company_id: str

    class Settings:
        name = "users"
