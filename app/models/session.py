from datetime import datetime, timezone
from typing import Literal

from beanie import Document
from pydantic import Field

SessionStage = Literal["hardware_check", "reading", "coding", "testing", "submitting", "finished"]


class Session(Document):
    company_id: str
    test_id: str
    candidate_id: str
    stage: SessionStage = "hardware_check"
    current_task: str = ""
    current_action: str = ""
    progress_pct: int = 0
    tab_switches: int = 0
    paste_events: int = 0
    camera_on: bool = False
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_seen_at: datetime | None = None
    ended_at: datetime | None = None

    class Settings:
        name = "sessions"
