from fastapi import APIRouter, Depends

from app.core.lookup import get_or_none
from app.core.security import get_current_user_id
from app.models.user import User

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
