from datetime import datetime, timezone
from typing import Literal

from beanie import Document
from pydantic import EmailStr, Field

InvitationStatus = Literal["sent", "opened", "started", "completed"]


class Invitation(Document):
    company_id: str
    test_id: str
    email: EmailStr
    message: str = ""
    status: InvitationStatus = "sent"
    sent_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "invitations"
