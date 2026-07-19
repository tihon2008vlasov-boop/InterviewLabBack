from pydantic import BaseModel, Field

from app.models.test import AlgorithmTestCase, Level, TaskSettings, TaskType


class GenerateTaskTestContext(BaseModel):
    name: str = ""
    description: str = ""
    level: Level = "middle"
    language: str
    duration_min: int = 60


class GenerateTaskCurrentTask(BaseModel):
    type: TaskType
    points: int = 25
    time_limit_min: int | None = None
    camera_required: bool = True
    tab_switch_lock: bool = True


class GenerateTaskIn(BaseModel):
    prompt: str = Field(min_length=8, max_length=4000)
    test: GenerateTaskTestContext
    task: GenerateTaskCurrentTask


class GeneratedTaskOut(BaseModel):
    title: str = Field(min_length=3, max_length=120)
    description: str = Field(min_length=20)
    readme: str = Field(min_length=20)
    starter_code: str = ""
    points: int = Field(ge=1, le=100)
    settings: TaskSettings
    test_cases: list[AlgorithmTestCase] = Field(default_factory=list, max_length=6)


class GeneratedTasksOut(BaseModel):
    tasks: list[GeneratedTaskOut] = Field(min_length=1, max_length=10)


class GenerateMockupIn(BaseModel):
    prompt: str = Field(min_length=8, max_length=4000)
    language: str = "react"
    level: Level = "middle"


class GeneratedMockupOut(BaseModel):
    html: str = Field(min_length=50)
