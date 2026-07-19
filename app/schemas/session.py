from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.models.candidate import SubmittedFile
from app.models.session import SessionStage


class SessionStartIn(BaseModel):
    name: str = Field(min_length=2)
    email: EmailStr
    position: str = ""


class SessionTaskOut(BaseModel):
    id: str
    type: str
    title: str
    description: str
    points: int
    starter_code: str
    readme: str
    figma_url: str
    image_url: str | None
    attached_files: list[str]
    time_limit_min: int | None
    camera_required: bool
    tab_switch_lock: bool


class SessionStartOut(BaseModel):
    session_id: str
    candidate_id: str
    test_id: str
    test_name: str
    duration_min: int
    language: str
    tasks: list[SessionTaskOut] = Field(default_factory=list)


class ReplayEventIn(BaseModel):
    at_sec: int
    kind: str
    label: str
    file: str | None = None
    detail: str | None = None
    snapshot: str | None = None


class SessionEventsIn(BaseModel):
    stage: SessionStage | None = None
    current_task: str | None = None
    current_action: str | None = None
    progress_pct: int | None = None
    camera_on: bool | None = None
    tab_switches: int | None = None
    replay_events: list[ReplayEventIn] = Field(default_factory=list)


class SessionSubmitIn(BaseModel):
    files: list[SubmittedFile] = Field(default_factory=list)
    duration_sec: int | None = None


class LiveSessionOut(BaseModel):
    id: str
    candidate_name: str
    candidate_email: str
    position: str
    test_id: str
    test_name: str
    language: str
    started_at: datetime
    elapsed_sec: int
    total_sec: int
    progress_pct: int
    stage: str
    current_task: str
    current_action: str
    tab_switches: int
    camera_on: bool
