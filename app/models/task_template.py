from datetime import datetime, timezone
from typing import Literal

from beanie import Document
from pydantic import Field

from app.models.test import Level, TaskType, TestTask

TaskSource = Literal["interviewlab", "codeforces", "leetcode", "codewars", "other"]


class TaskTemplate(Document):
    company_id: str
    created_by: str
    title: str
    description: str = ""
    task_type: TaskType
    level: Level = "middle"
    language: str = "python"
    tags: list[str] = Field(default_factory=list)
    source: TaskSource = "interviewlab"
    source_url: str = ""
    task: TestTask
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "task_templates"
