import secrets
import string
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.config import settings
from app.core.lookup import get_or_none
from app.core.security import get_current_user_id
from app.core.tenant import current_company_id
from app.models.company import Company
from app.models.invitation import Invitation
from app.models.test import InviteLink, Test
from app.models.user import User
from app.schemas.test import InvitationsIn, LinkIn, TestIn, TestPatch
from app.services.emailer import build_invitation_email, send_bulk_email

router = APIRouter(prefix="/tests", tags=["tests"], dependencies=[Depends(get_current_user_id)])

LINK_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def make_link_code() -> str:
    return "".join(secrets.choice(LINK_ALPHABET) for _ in range(6))


async def get_test_or_404(test_id: str, company_id: str | None = None) -> Test:
    test = await get_or_none(Test, test_id)
    # Чужой тест не отличаем от несуществующего, чтобы не раскрывать наличие id.
    if test is None or (company_id is not None and test.company_id != company_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Test not found")
    return test


@router.get("/")
async def list_tests(company_id: str = Depends(current_company_id)) -> list[Test]:
    return await Test.find(Test.company_id == company_id).sort(-Test.updated_at).to_list()


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_test(
    payload: TestIn,
    user_id: str = Depends(get_current_user_id),
    company_id: str = Depends(current_company_id),
) -> Test:
    test = Test(company_id=company_id, created_by=user_id, **payload.model_dump())
    return await Test.insert_one(test)


@router.get("/{test_id}")
async def get_test(test_id: str, company_id: str = Depends(current_company_id)) -> Test:
    return await get_test_or_404(test_id, company_id)


@router.patch("/{test_id}")
async def update_test(
    test_id: str, payload: TestPatch, company_id: str = Depends(current_company_id)
) -> Test:
    test = await get_test_or_404(test_id, company_id)
    updates = payload.model_dump(exclude_none=True)
    for key, value in updates.items():
        setattr(test, key, value)
    test.updated_at = datetime.now(timezone.utc)
    await test.save()
    return test


@router.delete("/{test_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_test(test_id: str, company_id: str = Depends(current_company_id)) -> None:
    test = await get_test_or_404(test_id, company_id)
    await test.delete()


@router.post("/{test_id}/duplicate", status_code=status.HTTP_201_CREATED)
async def duplicate_test(
    test_id: str,
    user_id: str = Depends(get_current_user_id),
    company_id: str = Depends(current_company_id),
) -> Test:
    source = await get_test_or_404(test_id, company_id)
    copy = Test(
        company_id=source.company_id,
        created_by=user_id,
        name=f"{source.name} (copy)",
        description=source.description,
        level=source.level,
        language=source.language,
        duration_min=source.duration_min,
        status="draft",
        tasks=source.tasks,
    )
    return await Test.insert_one(copy)


@router.post("/{test_id}/links", status_code=status.HTTP_201_CREATED)
async def create_link(
    test_id: str, payload: LinkIn, company_id: str = Depends(current_company_id)
) -> dict:
    test = await get_test_or_404(test_id, company_id)
    link = InviteLink(
        id=str(uuid4()),
        code=make_link_code(),
        expires_at=(
            datetime.now(timezone.utc) + timedelta(days=payload.expires_in_days)
            if payload.expires_in_days
            else None
        ),
        max_uses=payload.max_uses,
    )
    test.links.insert(0, link)
    await test.save()
    return {**link.model_dump(), "url": f"{settings.invite_link_base_url}/{link.code}"}


@router.post("/{test_id}/links/{link_id}/toggle")
async def toggle_link(
    test_id: str, link_id: str, company_id: str = Depends(current_company_id)
) -> InviteLink:
    test = await get_test_or_404(test_id, company_id)
    for link in test.links:
        if link.id == link_id:
            link.active = not link.active
            await test.save()
            return link
    raise HTTPException(status.HTTP_404_NOT_FOUND, "Link not found")


@router.post("/{test_id}/invitations", status_code=status.HTTP_201_CREATED)
async def send_invitations(
    test_id: str,
    payload: InvitationsIn,
    user_id: str = Depends(get_current_user_id),
    company_id: str = Depends(current_company_id),
) -> list[Invitation]:
    test = await get_test_or_404(test_id, company_id)

    # Кандидату нужна рабочая ссылка: берём активную, иначе заводим новую.
    link = next((l for l in test.links if l.active), None)
    if link is None:
        link = InviteLink(id=str(uuid4()), code=make_link_code())
        test.links.insert(0, link)
        await test.save()
    invite_url = f"{settings.invite_link_base_url}/{link.code}"

    user = await get_or_none(User, user_id)
    company = await get_or_none(Company, company_id)
    company_name = company.name if company else "InterviewLab"
    html = build_invitation_email(
        test.name, invite_url, test.duration_min, company_name, payload.message
    )

    invitations = [
        Invitation(company_id=test.company_id, test_id=str(test.id), email=email, message=payload.message)
        for email in payload.emails
    ]
    await Invitation.insert_many(invitations)

    # Письма шлём после записи в БД: приглашение не потеряется,
    # даже если почтовый сервер откажет.
    await send_bulk_email(
        list(payload.emails),
        f"Приглашение на тест «{test.name}» — {company_name}",
        html,
        from_name=company_name,
        reply_to=str(user.email) if user else "",
    )
    return invitations
