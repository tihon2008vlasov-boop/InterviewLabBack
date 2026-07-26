from fastapi import APIRouter, Depends, HTTPException, status

from app.core.lookup import get_or_none
from app.core.security import get_current_user_id, hash_password
from app.models.user import User
from app.schemas.settings import TeamMemberCreate

router = APIRouter(tags=["team"], dependencies=[Depends(get_current_user_id)])


@router.get("/team")
async def team(user_id: str = Depends(get_current_user_id)) -> list[dict]:
    current = await get_or_none(User, user_id)
    if current is None:
        return []
    members = await User.find(User.company_id == current.company_id).to_list()
    return [
        {
            "id": str(m.id),
            "name": m.name,
            "email": m.email,
            "role": m.role,
            "status": "active",
            "joined_at": m.created_at.isoformat(),
        }
        for m in members
    ]


@router.post("/team", status_code=status.HTTP_201_CREATED)
async def create_team_member(
    payload: TeamMemberCreate,
    user_id: str = Depends(get_current_user_id),
) -> dict:
    current = await get_or_none(User, user_id)
    if current is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    if current.role not in {"owner", "admin"}:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only owners and admins can add team members")

    email = str(payload.email).lower()
    if await User.find_one(User.email == email):
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists")

    member = await User.insert_one(
        User(
            name=payload.name.strip(),
            email=email,
            password_hash=hash_password(payload.password),
            role=payload.role,
            company_id=current.company_id,
        )
    )
    return {
        "id": str(member.id),
        "name": member.name,
        "email": member.email,
        "role": member.role,
        "status": "active",
        "joined_at": member.created_at.isoformat(),
    }
