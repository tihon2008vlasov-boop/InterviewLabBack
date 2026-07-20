from datetime import datetime, timezone
from typing import Literal

from beanie import Document
from pydantic import BaseModel, EmailStr, Field

CandidateStatus = Literal["invited", "in_progress", "completed", "reviewed", "hired", "rejected"]
AIRecommendation = Literal["strong_hire", "hire", "consider", "reject"]


class SkillScore(BaseModel):
    name: str
    score: int
    comment: str = ""


class TaskScore(BaseModel):
    task: str
    score: int = Field(ge=0, le=100)
    comment: str = ""


class CodeFinding(BaseModel):
    file: str
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)
    severity: Literal["info", "warning", "error"]
    title: str
    explanation: str
    suggestion: str = ""


class Authenticity(BaseModel):
    verdict: Literal["typed", "mixed", "likely_pasted", "no_data"] = "no_data"
    confidence: int = Field(default=0, ge=0, le=100)
    summary: str = ""
    signals: list[str] = Field(default_factory=list)
    interview_questions: list[str] = Field(default_factory=list)


class AIReport(BaseModel):
    summary: str = ""
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    verdict: str = ""
    skills: list[SkillScore] = Field(default_factory=list)
    task_scores: list[TaskScore] = Field(default_factory=list)
    code_findings: list[CodeFinding] = Field(default_factory=list)
    authenticity: Authenticity = Field(default_factory=Authenticity)


class SubmittedFile(BaseModel):
    name: str
    language: str
    code: str


class ReplayEvent(BaseModel):
    at_sec: int
    kind: str
    label: str
    file: str | None = None
    detail: str | None = None
    snapshot: str | None = None


class ActivityEvent(BaseModel):
    at: datetime
    kind: str
    label: str
    detail: str | None = None


class ProctorIncident(BaseModel):
    at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    kind: str
    severity: Literal["info", "warning", "critical"] = "warning"
    label: str
    detail: str | None = None
    confidence: int = Field(default=0, ge=0, le=100)


class Integrity(BaseModel):
    tab_switches: int = 0
    paste_events: int = 0
    camera_uptime: int = 100
    phone_detections: int = 0
    multiple_people: int = 0
    face_absence_events: int = 0
    identity_mismatches: int = 0
    screen_share_interruptions: int = 0
    proctor_risk_score: int = Field(default=0, ge=0, le=100)
    proctor_events: list[ProctorIncident] = Field(default_factory=list)


class Candidate(Document):
    company_id: str
    test_id: str
    name: str
    email: EmailStr
    phone: str = ""
    position: str = ""
    status: CandidateStatus = "invited"
    score: int | None = None
    ai_recommendation: AIRecommendation | None = None
    ai_report: AIReport = Field(default_factory=AIReport)
    submitted_files: list[SubmittedFile] = Field(default_factory=list)
    replay: list[ReplayEvent] = Field(default_factory=list)
    activity: list[ActivityEvent] = Field(default_factory=list)
    integrity: Integrity = Field(default_factory=Integrity)
    invited_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    duration_sec: int | None = None
    analysis_status: Literal["not_started", "pending", "completed", "failed"] = "not_started"
    analyzed_at: datetime | None = None

    class Settings:
        name = "candidates"
