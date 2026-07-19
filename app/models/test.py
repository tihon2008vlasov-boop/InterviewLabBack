from datetime import datetime, timezone
from typing import Literal

from beanie import Document
from pydantic import BaseModel, Field

TaskType = Literal["code", "bugfix", "feature", "quiz", "algorithm", "sql"]
Level = Literal["junior", "middle", "senior"]
TestStatus = Literal["draft", "active", "archived"]


class TaskSettings(BaseModel):
    time_limit_min: int | None = None
    camera_required: bool = True
    tab_switch_lock: bool = True


class AlgorithmTestCase(BaseModel):
    id: str
    input: str = ""
    expected_output: str = ""


class TaskContentBlock(BaseModel):
    id: str
    title: str = ""
    description: str = ""
    starter_code: str = ""
    readme: str = ""
    test_cases: list[AlgorithmTestCase] = Field(default_factory=list)


class TestTask(BaseModel):
    id: str
    type: TaskType
    title: str
    description: str = ""
    points: int = 25
    starter_code: str = ""
    readme: str = ""
    figma_url: str = ""
    image_url: str | None = None
    mockup_html: str = ""
    attached_files: list[str] = Field(default_factory=list)
    subtasks: list[TaskContentBlock] = Field(default_factory=list)
    test_cases: list[AlgorithmTestCase] = Field(default_factory=list)
    settings: TaskSettings = Field(default_factory=TaskSettings)


class InviteLink(BaseModel):
    id: str
    code: str
    active: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime | None = None
    max_uses: int | None = None
    uses: int = 0


class Test(Document):
    company_id: str
    created_by: str
    name: str
    description: str = ""
    level: Level = "middle"
    language: str
    duration_min: int = 60
    status: TestStatus = "draft"
    tasks: list[TestTask] = Field(default_factory=list)
    links: list[InviteLink] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "tests"
