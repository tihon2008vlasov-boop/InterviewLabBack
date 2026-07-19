from fastapi import APIRouter
from app.schemas.ai import GeneratedTasksOut, GenerateTaskIn
from app.services.gemini import generate_task_with_gemini

router = APIRouter(prefix="/ai", tags=["ai"])


@router.post("/tasks/generate", response_model=GeneratedTasksOut)
async def generate_task(payload: GenerateTaskIn) -> GeneratedTasksOut:
    return await generate_task_with_gemini(payload)
