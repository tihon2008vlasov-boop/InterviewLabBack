from datetime import datetime, timezone
from typing import Literal

from beanie import Document
from pydantic import Field

from app.models.candidate import ProctorIncident

SessionStage = Literal["hardware_check", "reading", "coding", "testing", "submitting", "finished"]
RecordingStatus = Literal["none", "recording", "ready", "failed"]


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
    screen_on: bool = False
    proctoring_enabled: bool = False
    proctoring_consent_at: datetime | None = None
    proctor_token: str = ""
    proctor_risk_score: int = Field(default=0, ge=0, le=100)
    proctor_events: list[ProctorIncident] = Field(default_factory=list)
    recording_status: RecordingStatus = "none"
    recording_path: str = ""
    recording_mime_type: str = ""
    recording_size_bytes: int = Field(default=0, ge=0)
    recording_duration_sec: int = Field(default=0, ge=0)
    recording_started_at: datetime | None = None
    recording_completed_at: datetime | None = None
    recording_expires_at: datetime | None = None
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_seen_at: datetime | None = None
    ended_at: datetime | None = None

    class Settings:
        name = "sessions"
