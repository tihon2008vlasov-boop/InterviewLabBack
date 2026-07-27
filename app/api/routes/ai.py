from fastapi import APIRouter, Depends

from app.core.security import get_current_user_id
from app.schemas.ai import (
    GeneratedMockupOut,
    GeneratedTasksOut,
    GenerateMockupIn,
    GenerateTaskIn,
)
from app.services.gemini import generate_mockup_with_gemini, generate_task_with_gemini

router = APIRouter(
    prefix="/ai",
    tags=["ai"],
    dependencies=[Depends(get_current_user_id)],
)


@router.post("/tasks/generate", response_model=GeneratedTasksOut)
async def generate_task(payload: GenerateTaskIn) -> GeneratedTasksOut:
    return await generate_task_with_gemini(payload)


@router.post("/tasks/mockup", response_model=GeneratedMockupOut)
async def generate_mockup(payload: GenerateMockupIn) -> GeneratedMockupOut:
    return await generate_mockup_with_gemini(payload)
