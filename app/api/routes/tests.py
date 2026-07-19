import secrets
import string
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.config import settings
from app.core.security import get_current_user_id
from app.models.invitation import Invitation
from app.models.test import InviteLink, Test
from app.models.user import User
from app.schemas.test import InvitationsIn, LinkIn, TestIn, TestPatch

router = APIRouter(prefix="/tests", tags=["tests"], dependencies=[Depends(get_current_user_id)])

LINK_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def make_link_code() -> str:
    return "".join(secrets.choice(LINK_ALPHABET) for _ in range(6))


async def get_test_or_404(test_id: str) -> Test:
    test = await Test.get(test_id)
    if test is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Test not found")
    return test


@router.get("/")
async def list_tests() -> list[Test]:
    return await Test.find_all().sort(-Test.updated_at).to_list()


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_test(payload: TestIn, user_id: str = Depends(get_current_user_id)) -> Test:
    user = await User.get(user_id)
    test = Test(
        company_id=user.company_id if user else "",
        created_by=user_id,
        **payload.model_dump(),
    )
    return await Test.insert_one(test)


@router.get("/{test_id}")
async def get_test(test_id: str) -> Test:
    return await get_test_or_404(test_id)


@router.patch("/{test_id}")
async def update_test(test_id: str, payload: TestPatch) -> Test:
    test = await get_test_or_404(test_id)
    updates = payload.model_dump(exclude_none=True)
    for key, value in updates.items():
        setattr(test, key, value)
    test.updated_at = datetime.now(timezone.utc)
    await test.save()
    return test


@router.delete("/{test_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_test(test_id: str) -> None:
    test = await get_test_or_404(test_id)
    await test.delete()


@router.post("/{test_id}/duplicate", status_code=status.HTTP_201_CREATED)
async def duplicate_test(test_id: str, user_id: str = Depends(get_current_user_id)) -> Test:
    source = await get_test_or_404(test_id)
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
async def create_link(test_id: str, payload: LinkIn) -> dict:
    test = await get_test_or_404(test_id)
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
async def toggle_link(test_id: str, link_id: str) -> InviteLink:
    test = await get_test_or_404(test_id)
    for link in test.links:
        if link.id == link_id:
            link.active = not link.active
            await test.save()
            return link
    raise HTTPException(status.HTTP_404_NOT_FOUND, "Link not found")


@router.post("/{test_id}/invitations", status_code=status.HTTP_201_CREATED)
async def send_invitations(test_id: str, payload: InvitationsIn) -> list[Invitation]:
    test = await get_test_or_404(test_id)
    invitations = [
        Invitation(company_id=test.company_id, test_id=str(test.id), email=email, message=payload.message)
        for email in payload.emails
    ]
    await Invitation.insert_many(invitations)
    return invitations
