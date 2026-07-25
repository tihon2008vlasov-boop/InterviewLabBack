from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.lookup import get_or_none
from app.core.security import get_current_user_id
from app.core.tenant import current_company_id
from app.models.task_template import TaskTemplate
from app.models.test import Level, TaskType
from app.schemas.task_template import TaskTemplateIn, TaskTemplatePatch

router = APIRouter(
    prefix="/task-library",
    tags=["task-library"],
    dependencies=[Depends(get_current_user_id)],
)


async def get_template_or_404(template_id: str, company_id: str) -> TaskTemplate:
    template = await get_or_none(TaskTemplate, template_id)
    if template is None or template.company_id != company_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task template not found")
    return template


@router.get("/")
async def list_templates(
    query: str = Query(default="", max_length=120),
    task_type: TaskType | None = None,
    level: Level | None = None,
    language: str | None = None,
    company_id: str = Depends(current_company_id),
) -> list[TaskTemplate]:
    filters = [TaskTemplate.company_id == company_id]
    if task_type:
        filters.append(TaskTemplate.task_type == task_type)
    if level:
        filters.append(TaskTemplate.level == level)
    if language:
        filters.append(TaskTemplate.language == language)

    templates = await TaskTemplate.find(*filters).sort(-TaskTemplate.updated_at).to_list()
    templates.sort(
        key=lambda template: (
            template.task.id != "library-leetcode-target-pair",
            -template.updated_at.timestamp(),
        )
    )
    normalized_query = query.strip().casefold()
    if not normalized_query:
        return templates
    return [
        template
        for template in templates
        if normalized_query
        in " ".join(
            [
                template.title,
                template.description,
                template.source,
                *template.tags,
            ]
        ).casefold()
    ]


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_template(
    payload: TaskTemplateIn,
    user_id: str = Depends(get_current_user_id),
    company_id: str = Depends(current_company_id),
) -> TaskTemplate:
    template = TaskTemplate(
        company_id=company_id,
        created_by=user_id,
        **payload.model_dump(),
    )
    return await TaskTemplate.insert_one(template)


@router.patch("/{template_id}")
async def update_template(
    template_id: str,
    payload: TaskTemplatePatch,
    company_id: str = Depends(current_company_id),
) -> TaskTemplate:
    template = await get_template_or_404(template_id, company_id)
    for key, value in payload.model_dump(exclude_none=True).items():
        setattr(template, key, value)
    if payload.task is not None:
        template.task_type = payload.task.type
    template.updated_at = datetime.now(timezone.utc)
    await template.save()
    return template


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(
    template_id: str,
    company_id: str = Depends(current_company_id),
) -> None:
    template = await get_template_or_404(template_id, company_id)
    await template.delete()
