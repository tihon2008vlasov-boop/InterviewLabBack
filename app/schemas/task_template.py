from pydantic import BaseModel, Field

from app.models.task_template import TaskSource
from app.models.test import Level, TaskType, TestTask


class TaskTemplateIn(BaseModel):
    title: str = Field(min_length=3, max_length=120)
    description: str = ""
    task_type: TaskType
    level: Level = "middle"
    language: str = "python"
    tags: list[str] = Field(default_factory=list, max_length=12)
    source: TaskSource = "interviewlab"
    source_url: str = ""
    task: TestTask


class TaskTemplatePatch(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=120)
    description: str | None = None
    level: Level | None = None
    language: str | None = None
    tags: list[str] | None = Field(default=None, max_length=12)
    source: TaskSource | None = None
    source_url: str | None = None
    task: TestTask | None = None
