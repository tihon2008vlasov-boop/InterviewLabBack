from typing import Literal

from beanie import Document


class Company(Document):
    name: str
    website: str = ""
    logo_url: str = ""
    plan: Literal["free", "pro", "scale", "enterprise"] = "free"
    seats: int = 3
    status: Literal["active", "trial", "churned"] = "trial"

    class Settings:
        name = "companies"
